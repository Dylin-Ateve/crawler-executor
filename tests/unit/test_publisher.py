from crawler import publisher
from crawler.publisher import (
    DEFAULT_SSL_CA_LOCATION,
    ConfluentKafkaPageMetadataPublisher,
    KafkaPublisherConfig,
    PublishError,
    configured_flush_timeout_seconds,
    resolve_ssl_ca_location,
)


class StubProducer:
    def __init__(self, flush_result=0):
        self.flush_result = flush_result
        self.produced = []
        self.flush_timeout = None
        self.purged = False

    def produce(self, topic, *, key, value, on_delivery):
        self.produced.append({"topic": topic, "key": key, "value": value})

    def flush(self, timeout=None):
        self.flush_timeout = timeout
        return self.flush_result

    def purge(self):
        self.purged = True


def test_resolve_ssl_ca_location_uses_existing_configured_path(tmp_path):
    ca_file = tmp_path / "ca-bundle.crt"
    ca_file.write_text("test-ca", encoding="utf-8")

    assert resolve_ssl_ca_location(str(ca_file)) == str(ca_file)


def test_resolve_ssl_ca_location_falls_back_to_existing_common_path(tmp_path, monkeypatch):
    ca_file = tmp_path / "fallback-ca-bundle.crt"
    ca_file.write_text("test-ca", encoding="utf-8")
    monkeypatch.setattr(publisher, "COMMON_SSL_CA_LOCATIONS", (str(ca_file),))

    assert resolve_ssl_ca_location("/missing/cert.pem") == str(ca_file)


def test_resolve_ssl_ca_location_preserves_configured_path_when_no_file_exists(monkeypatch):
    monkeypatch.setattr(publisher, "COMMON_SSL_CA_LOCATIONS", ("/missing/fallback.pem",))

    assert resolve_ssl_ca_location("/missing/cert.pem") == "/missing/cert.pem"


def test_resolve_ssl_ca_location_uses_default_when_unset_and_no_file_exists(monkeypatch):
    monkeypatch.setattr(publisher, "COMMON_SSL_CA_LOCATIONS", ("/missing/fallback.pem",))

    assert resolve_ssl_ca_location("") == DEFAULT_SSL_CA_LOCATION


def test_configured_flush_timeout_seconds_uses_flush_timeout_ms():
    config = KafkaPublisherConfig(
        bootstrap_servers="localhost:9092",
        topic_page_metadata="topic",
        flush_timeout_ms=8000,
    )

    assert configured_flush_timeout_seconds(config) == 8.0


def test_publish_page_metadata_uses_bounded_flush_timeout():
    config = KafkaPublisherConfig(
        bootstrap_servers="localhost:9092",
        topic_page_metadata="topic",
        flush_timeout_ms=8000,
    )
    producer = StubProducer()
    publisher_client = ConfluentKafkaPageMetadataPublisher(config, producer=producer)

    publisher_client.publish_page_metadata("key", {"ok": True})

    assert producer.flush_timeout == 8.0


def test_publish_page_metadata_raises_when_flush_leaves_pending_messages():
    config = KafkaPublisherConfig(
        bootstrap_servers="localhost:9092",
        topic_page_metadata="topic",
        flush_timeout_ms=8000,
    )
    producer = StubProducer(flush_result=1)
    publisher_client = ConfluentKafkaPageMetadataPublisher(config, producer=producer)

    try:
        publisher_client.publish_page_metadata("key", {"ok": True})
    except PublishError as exc:
        assert "flush timeout" in str(exc)
    else:
        raise AssertionError("expected PublishError")

    assert producer.purged is True
