from __future__ import annotations

from datetime import datetime, timezone

from crawler.pipelines import (
    ContentPersistencePipeline,
    build_crawl_attempt_payload,
    build_content_artifact,
    build_snapshot_id,
    build_storage_key,
    count_outlinks,
)
from crawler.publisher import FakeCrawlAttemptPublisher
from crawler.schemas import CRAWL_ATTEMPT_SCHEMA_VERSION, SchemaValidationError, validate_crawl_attempt
from crawler.storage import FakeObjectStorageClient


class DummySpider:
    class Logger:
        def __init__(self):
            self.errors = []
            self.infos = []

        def error(self, *args):
            self.errors.append(args)

        def info(self, *args):
            self.infos.append(args)

        def warning(self, *args):
            self.infos.append(args)

    def __init__(self):
        self.logger = self.Logger()


def test_content_artifact_hash_and_gzip_size():
    artifact = build_content_artifact(b"<html>Hello</html>")

    assert artifact.uncompressed_size == 18
    assert artifact.compressed_size > 0
    assert len(artifact.content_sha256) == 64


def test_storage_key_contains_date_hashes_and_snapshot_id():
    fetched_at = datetime(2026, 4, 28, 1, 2, 3, tzinfo=timezone.utc)
    key = build_storage_key("example.com", "a" * 64, "snapshot-1", fetched_at)

    assert key.startswith("pages/v1/2026/04/28/")
    assert key.endswith("/" + "a" * 64 + "/snapshot-1.html.gz")


def test_snapshot_id_uses_url_hash_and_epoch_millis():
    fetched_at = datetime(2026, 4, 28, 0, 0, 0, 123000, tzinfo=timezone.utc)

    assert build_snapshot_id("abc", fetched_at) == "abc:1777334400123"


def test_count_outlinks_tracks_external_links():
    counts = count_outlinks(
        "https://example.com/a",
        ["/b", "https://example.com/c", "https://other.example/d", "mailto:test@example.com"],
    )

    assert counts == {"total": 3, "external": 1}


def test_crawl_attempt_schema_validation_accepts_valid_payload():
    artifact = build_content_artifact(b"<html>ok</html>")
    payload = build_crawl_attempt_payload(
        item={
            "url": "https://example.com/",
            "status_code": 200,
            "content_type": "text/html",
            "response_headers": {"Content-Type": "text/html", "X-Ignored": "1"},
        },
        canonical_url="https://example.com",
        url_hash="b" * 64,
        attempt_id="b" * 64 + ":attempt:1777334400000",
        attempted_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        finished_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        fetch_result="succeeded",
        content_result="html_snapshot_candidate",
        storage_result="stored",
        snapshot_id="b" * 64 + ":1777334400000",
        artifact=artifact,
        storage_provider="oci",
        bucket="bucket",
        storage_key="key",
        storage_etag=None,
        outlinks_count=0,
        outlinks_external_count=0,
        header_allowlist=("content-type",),
    )

    validate_crawl_attempt(payload)
    assert payload["schema_version"] == CRAWL_ATTEMPT_SCHEMA_VERSION
    assert payload["attempt_id"] == "b" * 64 + ":attempt:1777334400000"
    assert payload["storage_result"] == "stored"
    assert payload["response_headers"] == {"content-type": "text/html"}


def test_crawl_attempt_schema_rejects_missing_required_field():
    try:
        validate_crawl_attempt({"schema_version": CRAWL_ATTEMPT_SCHEMA_VERSION})
    except SchemaValidationError as exc:
        assert "crawl attempt missing required fields" in str(exc)
    else:
        raise AssertionError("expected schema validation failure")


def test_pipeline_persists_html_then_publishes_metadata():
    storage = FakeObjectStorageClient(bucket="clawer_content_staging")
    publisher = FakeCrawlAttemptPublisher()
    pipeline = ContentPersistencePipeline(storage, publisher)
    spider = DummySpider()

    item = pipeline.process_item(
        {
            "p1_candidate": True,
            "url": "https://example.com/index.html",
            "status_code": 200,
            "content_type": "text/html; charset=utf-8",
            "response_headers": {"Content-Type": "text/html"},
            "body": b"<html><a href='https://external.example/'>x</a></html>",
            "outlinks": ["https://external.example/"],
            "fetched_at_dt": datetime(2026, 4, 28, tzinfo=timezone.utc),
            "attempted_at_dt": datetime(2026, 4, 28, tzinfo=timezone.utc),
            "attempt_id": "attempt-1",
            "egress_local_ip": "10.0.0.2",
        },
        spider,
    )

    assert item["p1_persisted"] is True
    assert item["p1_published"] is True
    assert len(storage.objects) == 1
    assert len(publisher.messages) == 1
    stored_object = next(iter(storage.objects.values()))
    assert stored_object["content_encoding"] is None
    assert stored_object["metadata"]["compression"] == "gzip"
    payload = publisher.messages[0]["payload"]
    assert payload["bucket"] == "clawer_content_staging"
    assert payload["attempt_id"] == "attempt-1"
    assert payload["storage_result"] == "stored"
    assert payload["outlinks_count"] == 1
    assert payload["outlinks_external_count"] == 1


class FakeQueueConsumer:
    def __init__(self):
        self.acked = []

    def ack(self, message_id):
        self.acked.append(message_id)


def test_pipeline_fetch_failure_publishes_failed_attempt_and_acks_stream_message():
    storage = FakeObjectStorageClient()
    publisher = FakeCrawlAttemptPublisher()
    pipeline = ContentPersistencePipeline(storage, publisher)
    spider = DummySpider()
    consumer = FakeQueueConsumer()

    item = pipeline.process_item(
        {
            "p1_candidate": True,
            "fetch_failed": True,
            "url": "https://example.com/",
            "canonical_url": "https://example.com",
            "url_hash": "100680ad546ce6a577f42f1b8a6b614dc6f7d5b09852c1f235e95b4e2aa9ddc3",
            "attempt_id": "attempt-1",
            "attempted_at_dt": datetime(2026, 4, 28, tzinfo=timezone.utc),
            "fetched_at_dt": datetime(2026, 4, 28, tzinfo=timezone.utc),
            "error_type": "DNSLookupError",
            "error_message": "dns failed",
            "stream_message_id": "1-0",
            "fetch_queue_consumer": consumer,
        },
        spider,
    )

    assert item["p1_published"] is True
    assert consumer.acked == ["1-0"]
    assert storage.objects == {}
    payload = publisher.messages[0]["payload"]
    assert payload["fetch_result"] == "failed"
    assert payload["content_result"] == "unknown"
    assert payload["storage_result"] == "skipped"
    assert payload["error_type"] == "DNSLookupError"
    assert len(publisher.messages) == 1


def test_pipeline_skips_non_html_without_storage_but_publishes_attempt():
    storage = FakeObjectStorageClient()
    publisher = FakeCrawlAttemptPublisher()
    pipeline = ContentPersistencePipeline(storage, publisher)
    spider = DummySpider()

    item = pipeline.process_item(
        {
            "p1_candidate": True,
            "url": "https://example.com/image.png",
            "status_code": 200,
            "content_type": "image/png",
            "body": b"png",
        },
        spider,
    )

    assert item["p1_persisted"] is False
    assert item["p1_published"] is True
    assert item["p1_skip_reason"] == "non_html_content"
    assert storage.objects == {}
    assert len(publisher.messages) == 1
    payload = publisher.messages[0]["payload"]
    assert payload["storage_result"] == "skipped"
    assert payload["content_result"] == "non_snapshot"


def test_pipeline_upload_failure_publishes_failed_attempt():
    storage = FakeObjectStorageClient(fail_upload=True)
    publisher = FakeCrawlAttemptPublisher()
    pipeline = ContentPersistencePipeline(storage, publisher)
    spider = DummySpider()

    item = pipeline.process_item(
        {
            "p1_candidate": True,
            "url": "https://example.com/",
            "status_code": 200,
            "content_type": "text/html",
            "body": b"<html>ok</html>",
        },
        spider,
    )

    assert item["p1_persisted"] is False
    assert item["p1_published"] is True
    assert item["p1_skip_reason"] == "storage_upload_failed"
    assert len(publisher.messages) == 1
    payload = publisher.messages[0]["payload"]
    assert payload["storage_result"] == "failed"
    assert payload["snapshot_id"] is None
    assert payload["storage_key"] is None


def test_pipeline_publish_failure_keeps_storage_result():
    storage = FakeObjectStorageClient()
    publisher = FakeCrawlAttemptPublisher(fail_publish=True)
    pipeline = ContentPersistencePipeline(storage, publisher)
    spider = DummySpider()

    item = pipeline.process_item(
        {
            "p1_candidate": True,
            "url": "https://example.com/",
            "status_code": 200,
            "content_type": "text/html",
            "body": b"<html>ok</html>",
        },
        spider,
    )

    assert item["p1_persisted"] is True
    assert item["p1_published"] is False
    assert len(storage.objects) == 1
