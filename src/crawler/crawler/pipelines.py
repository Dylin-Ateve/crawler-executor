from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional
from urllib.parse import urljoin, urlsplit

from crawler.attempts import build_attempt_id
from crawler.contracts.canonical_url import CanonicalUrl, build_canonical_url, canonical_url_hash
from crawler.metrics import metrics
from crawler.publisher import CrawlAttemptPublisher, PublishError, build_crawl_attempt_publisher
from crawler.schemas import CRAWL_ATTEMPT_SCHEMA_VERSION, filter_headers, validate_crawl_attempt
from crawler.storage import ObjectStorageClient, StorageError, build_object_storage_client


HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
DEFAULT_HEADER_ALLOWLIST = (
    "content-type",
    "content-length",
    "last-modified",
    "etag",
    "cache-control",
    "server",
)


@dataclass(frozen=True)
class ContentArtifact:
    raw_body: bytes
    compressed_body: bytes
    content_sha256: str
    uncompressed_size: int
    compressed_size: int


class ContentPersistencePipeline:
    def __init__(
        self,
        storage_client: ObjectStorageClient,
        publisher: CrawlAttemptPublisher,
        *,
        compression: str = "gzip",
        header_allowlist: Iterable[str] = DEFAULT_HEADER_ALLOWLIST,
    ) -> None:
        if compression != "gzip":
            raise ValueError(f"unsupported CONTENT_COMPRESSION: {compression}")
        self.storage_client = storage_client
        self.publisher = publisher
        self.compression = compression
        self.header_allowlist = tuple(header_allowlist)

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        return cls(
            storage_client=build_object_storage_client(settings),
            publisher=build_crawl_attempt_publisher(settings),
            compression=settings.get("CONTENT_COMPRESSION", "gzip"),
        )

    def process_item(self, item, spider):
        if not item.get("p1_candidate"):
            return item

        finished_at = item.get("fetched_at_dt") or datetime.now(timezone.utc)
        attempted_at = item.get("attempted_at_dt") or finished_at
        canonical = build_item_canonical_url(item)
        attempt_id = item.get("attempt_id") or build_attempt_id(canonical.url_hash, attempted_at)
        host = canonical_host(canonical.canonical_url)
        outlink_counts = count_outlinks(str(item["url"]), item.get("outlinks") or [])

        if item.get("fetch_failed"):
            payload = build_crawl_attempt_payload(
                item=item,
                canonical_url=canonical.canonical_url,
                url_hash=canonical.url_hash,
                attempt_id=str(attempt_id),
                attempted_at=attempted_at,
                finished_at=finished_at,
                fetch_result="failed",
                content_result="unknown",
                storage_result="skipped",
                outlinks_count=0,
                outlinks_external_count=0,
                header_allowlist=self.header_allowlist,
            )
            return self._publish_attempt(item, payload, "fetch_failed", spider)

        status_code = int(item.get("status_code") or 0)
        content_type = str(item.get("content_type") or "")
        if status_code != 200:
            payload = build_crawl_attempt_payload(
                item=item,
                canonical_url=canonical.canonical_url,
                url_hash=canonical.url_hash,
                attempt_id=str(attempt_id),
                attempted_at=attempted_at,
                finished_at=finished_at,
                fetch_result="succeeded",
                content_result="non_snapshot",
                storage_result="skipped",
                outlinks_count=outlink_counts["total"],
                outlinks_external_count=outlink_counts["external"],
                header_allowlist=self.header_allowlist,
            )
            return self._publish_attempt(item, payload, "non_200_status", spider)
        if not is_html_content_type(content_type):
            payload = build_crawl_attempt_payload(
                item=item,
                canonical_url=canonical.canonical_url,
                url_hash=canonical.url_hash,
                attempt_id=str(attempt_id),
                attempted_at=attempted_at,
                finished_at=finished_at,
                fetch_result="succeeded",
                content_result="non_snapshot",
                storage_result="skipped",
                outlinks_count=outlink_counts["total"],
                outlinks_external_count=outlink_counts["external"],
                header_allowlist=self.header_allowlist,
            )
            return self._publish_attempt(item, payload, "non_html_content", spider)

        snapshot_id = build_snapshot_id(canonical.url_hash, finished_at)
        artifact = build_content_artifact(bytes(item.get("body") or b""))
        storage_key = build_storage_key(host, canonical.url_hash, snapshot_id, finished_at)

        metadata = {
            "url_hash": canonical.url_hash,
            "snapshot_id": snapshot_id,
            "canonical_url": canonical.canonical_url,
        }

        try:
            stored = self.storage_client.put_object(
                storage_key,
                artifact.compressed_body,
                content_type="text/html",
                content_encoding=None,
                metadata={**metadata, "compression": self.compression},
            )
            metrics.record_storage_upload(self.storage_client.provider, self.storage_client.bucket, "success")
        except StorageError as exc:
            metrics.record_storage_upload(self.storage_client.provider, self.storage_client.bucket, "failure")
            spider.logger.error(
                "p1_storage_upload_failed url=%s storage_key=%s error=%s",
                item.get("url"),
                storage_key,
                exc,
            )
            item["p1_persisted"] = False
            item["p1_skip_reason"] = "storage_upload_failed"
            payload = build_crawl_attempt_payload(
                item=item,
                canonical_url=canonical.canonical_url,
                url_hash=canonical.url_hash,
                attempt_id=str(attempt_id),
                attempted_at=attempted_at,
                finished_at=finished_at,
                fetch_result="succeeded",
                content_result="html_snapshot_candidate",
                storage_result="failed",
                artifact=artifact,
                outlinks_count=outlink_counts["total"],
                outlinks_external_count=outlink_counts["external"],
                header_allowlist=self.header_allowlist,
            )
            return self._publish_attempt(item, payload, "storage_upload_failed", spider)

        payload = build_crawl_attempt_payload(
            item=item,
            canonical_url=canonical.canonical_url,
            url_hash=canonical.url_hash,
            attempt_id=str(attempt_id),
            attempted_at=attempted_at,
            finished_at=finished_at,
            fetch_result="succeeded",
            content_result="html_snapshot_candidate",
            storage_result="stored",
            snapshot_id=snapshot_id,
            artifact=artifact,
            storage_provider=stored.provider,
            bucket=stored.bucket,
            storage_key=stored.key,
            storage_etag=stored.etag,
            outlinks_count=outlink_counts["total"],
            outlinks_external_count=outlink_counts["external"],
            header_allowlist=self.header_allowlist,
        )
        validate_crawl_attempt(payload)
        try:
            self.publisher.publish_crawl_attempt(str(attempt_id), payload)
            metrics.record_kafka_publish(self.publisher.topic, "success")
        except PublishError as exc:
            metrics.record_kafka_publish(self.publisher.topic, "failure")
            spider.logger.error(
                "p1_kafka_publish_failed url=%s attempt_id=%s storage_result=stored snapshot_id=%s storage_key=%s error=%s",
                item.get("url"),
                attempt_id,
                snapshot_id,
                stored.key,
                exc,
            )
            item["p1_persisted"] = True
            item["p1_published"] = False
            item["p1_storage_key"] = stored.key
            return item

        item["p1_persisted"] = True
        item["p1_published"] = True
        item["p1_storage_key"] = stored.key
        item["p1_snapshot_id"] = snapshot_id
        item["p1_attempt_id"] = str(attempt_id)
        item["p1_url_hash"] = canonical.url_hash
        ack_stream_message(item, spider)
        spider.logger.info(
            "p1_crawl_attempt_published url=%s attempt_id=%s storage_result=stored snapshot_id=%s storage_key=%s",
            item.get("url"),
            attempt_id,
            snapshot_id,
            stored.key,
        )
        return item

    def _publish_attempt(self, item, payload: Dict[str, object], reason: str, spider):
        validate_crawl_attempt(payload)
        try:
            self.publisher.publish_crawl_attempt(str(payload["attempt_id"]), payload)
            metrics.record_kafka_publish(self.publisher.topic, "success")
        except PublishError as exc:
            metrics.record_kafka_publish(self.publisher.topic, "failure")
            spider.logger.error(
                "p1_kafka_publish_failed url=%s attempt_id=%s storage_result=%s error=%s",
                item.get("url"),
                payload["attempt_id"],
                payload["storage_result"],
                exc,
            )
            item.setdefault("p1_persisted", False)
            item["p1_published"] = False
            return item

        if payload["storage_result"] == "skipped":
            metrics.record_content_skip(reason)
        item.setdefault("p1_persisted", False)
        item["p1_skip_reason"] = reason
        item["p1_attempt_id"] = payload["attempt_id"]
        item["p1_published"] = True
        ack_stream_message(item, spider)
        spider.logger.info(
            "p1_crawl_attempt_published url=%s attempt_id=%s storage_result=%s reason=%s",
            item.get("url"),
            payload["attempt_id"],
            payload["storage_result"],
            reason,
        )
        return item


def is_html_content_type(content_type: str) -> bool:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    return normalized in HTML_CONTENT_TYPES


def build_content_artifact(raw_body: bytes) -> ContentArtifact:
    compressed = gzip.compress(raw_body)
    return ContentArtifact(
        raw_body=raw_body,
        compressed_body=compressed,
        content_sha256=hashlib.sha256(raw_body).hexdigest(),
        uncompressed_size=len(raw_body),
        compressed_size=len(compressed),
    )


def build_snapshot_id(url_hash: str, fetched_at: datetime) -> str:
    fetched_at_ms = int(fetched_at.timestamp() * 1000)
    return f"{url_hash}:{fetched_at_ms}"


def build_storage_key(host: str, url_hash: str, snapshot_id: str, fetched_at: datetime) -> str:
    host_hash = hashlib.sha256(host.encode("utf-8")).hexdigest()[:16]
    return (
        f"pages/v1/{fetched_at:%Y}/{fetched_at:%m}/{fetched_at:%d}/"
        f"{host_hash}/{url_hash}/{snapshot_id}.html.gz"
    )


def build_crawl_attempt_payload(
    *,
    item: Dict[str, object],
    canonical_url: str,
    url_hash: str,
    attempt_id: str,
    attempted_at: datetime,
    finished_at: datetime,
    fetch_result: str,
    content_result: str,
    storage_result: str,
    outlinks_count: int,
    outlinks_external_count: int,
    header_allowlist: Iterable[str],
    snapshot_id: Optional[str] = None,
    artifact: Optional[ContentArtifact] = None,
    storage_provider: Optional[str] = None,
    bucket: Optional[str] = None,
    storage_key: Optional[str] = None,
    storage_etag: Optional[str] = None,
) -> Dict[str, object]:
    headers = item.get("response_headers") or {}
    return {
        "schema_version": CRAWL_ATTEMPT_SCHEMA_VERSION,
        "attempt_id": attempt_id,
        "snapshot_id": snapshot_id,
        "url_hash": url_hash,
        "canonical_url": canonical_url,
        "original_url": item["url"],
        "host": canonical_host(canonical_url),
        "attempted_at": attempted_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        "fetch_result": fetch_result,
        "status_code": int(item.get("status_code") or 0) if item.get("status_code") is not None else None,
        "content_type": item.get("content_type"),
        "response_headers": filter_headers(headers, header_allowlist),
        "response_time_ms": item.get("response_time_ms"),
        "bytes_downloaded": len(bytes(item.get("body") or b"")) if item.get("body") is not None else None,
        "error_type": item.get("error_type"),
        "error_message": item.get("error_message"),
        "content_result": content_result,
        "outlinks_count": outlinks_count,
        "outlinks_external_count": outlinks_external_count,
        "storage_result": storage_result,
        "storage_provider": storage_provider,
        "bucket": bucket,
        "storage_key": storage_key,
        "storage_etag": storage_etag,
        "compression": "gzip" if storage_result == "stored" else None,
        "content_sha256": artifact.content_sha256 if artifact else None,
        "uncompressed_size": artifact.uncompressed_size if artifact else None,
        "compressed_size": artifact.compressed_size if artifact else None,
        "egress_local_ip": item.get("egress_local_ip"),
        "observed_egress_ip": item.get("observed_egress_ip"),
    }


def count_outlinks(base_url: str, outlinks: Iterable[str]) -> Dict[str, int]:
    base_host = (urlsplit(base_url).hostname or "").lower()
    total = 0
    external = 0
    for href in outlinks:
        if not href:
            continue
        absolute = urljoin(base_url, str(href))
        host = (urlsplit(absolute).hostname or "").lower()
        if not host:
            continue
        total += 1
        if host != base_host:
            external += 1
    return {"total": total, "external": external}


def canonical_host(canonical_url: str) -> str:
    return (urlsplit(canonical_url).hostname or "").lower()


def build_item_canonical_url(item: Dict[str, object]) -> CanonicalUrl:
    original_url = str(item["url"])
    canonical_url = item.get("canonical_url")
    if canonical_url:
        canonical = str(canonical_url)
        return CanonicalUrl(
            original_url=original_url,
            canonical_url=canonical,
            url_hash=str(item.get("url_hash") or canonical_url_hash(canonical)),
        )
    return build_canonical_url(original_url)


def ack_stream_message(item: Dict[str, object], spider) -> None:
    consumer = item.get("fetch_queue_consumer")
    message_id = item.get("stream_message_id")
    if not consumer or not message_id:
        return
    try:
        consumer.ack(str(message_id))
        metrics.record_fetch_queue_event("ack")
    except Exception as exc:
        metrics.record_fetch_queue_event("ack_failed")
        spider.logger.error("fetch_queue_ack_failed message_id=%s error=%s", message_id, exc)
