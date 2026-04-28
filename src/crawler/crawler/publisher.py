from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol


DEFAULT_SSL_CA_LOCATION = "/etc/pki/tls/certs/ca-bundle.crt"
COMMON_SSL_CA_LOCATIONS = (
    DEFAULT_SSL_CA_LOCATION,
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/certs/ca-bundle.crt",
    "/etc/ssl/cert.pem",
)


class PublishError(RuntimeError):
    pass


class PageMetadataPublisher(Protocol):
    topic: str

    def publish_page_metadata(self, key: str, payload: Dict[str, object]) -> None:
        ...


@dataclass(frozen=True)
class KafkaPublisherConfig:
    bootstrap_servers: str
    topic_page_metadata: str
    security_protocol: str = "SASL_SSL"
    sasl_mechanism: str = "SCRAM-SHA-512"
    username: str = ""
    password: str = ""
    ssl_ca_location: str = DEFAULT_SSL_CA_LOCATION
    batch_size: int = 100
    retries: int = 3
    request_timeout_ms: int = 30000
    delivery_timeout_ms: int = 120000
    flush_timeout_ms: int = 130000


class ConfluentKafkaPageMetadataPublisher:
    def __init__(self, config: KafkaPublisherConfig, producer: Optional[object] = None) -> None:
        self.config = config
        self.topic = config.topic_page_metadata
        self.producer = producer or self._build_producer(config)

    @staticmethod
    def _build_producer(config: KafkaPublisherConfig):
        try:
            from confluent_kafka import Producer
        except ImportError as exc:
            raise PublishError("confluent-kafka package is required for Kafka publishing") from exc

        producer_config = {
            "bootstrap.servers": config.bootstrap_servers,
            "security.protocol": config.security_protocol,
            "sasl.mechanisms": config.sasl_mechanism,
            "sasl.username": config.username,
            "sasl.password": config.password,
            "ssl.ca.location": resolve_ssl_ca_location(config.ssl_ca_location),
            "acks": "all",
            "enable.idempotence": True,
            "retries": config.retries,
            "request.timeout.ms": config.request_timeout_ms,
            "delivery.timeout.ms": config.delivery_timeout_ms,
            "message.timeout.ms": config.delivery_timeout_ms,
            "socket.timeout.ms": config.request_timeout_ms,
            "reconnect.backoff.ms": 250,
            "reconnect.backoff.max.ms": 1000,
            "batch.num.messages": config.batch_size,
        }
        return Producer(producer_config)

    def publish_page_metadata(self, key: str, payload: Dict[str, object]) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        delivery_errors: List[BaseException] = []

        def on_delivery(error, _message):
            if error is not None:
                delivery_errors.append(PublishError(str(error)))

        try:
            self.producer.produce(self.topic, key=key.encode("utf-8"), value=encoded, on_delivery=on_delivery)
            pending = self.producer.flush(configured_flush_timeout_seconds(self.config))
        except Exception as exc:
            raise PublishError(f"failed to publish page metadata key={key}") from exc

        if delivery_errors:
            raise PublishError(f"failed to publish page metadata key={key}") from delivery_errors[0]
        if pending:
            try:
                self.producer.purge()
                self.producer.flush(1.0)
            except Exception:
                pass
            raise PublishError(f"failed to publish page metadata key={key}: flush timeout with {pending} pending message(s)")


class FakePageMetadataPublisher:
    def __init__(self, topic: str = "crawler.page-metadata.v1", fail_publish: bool = False) -> None:
        self.topic = topic
        self.fail_publish = fail_publish
        self.messages: List[Dict[str, object]] = []

    def publish_page_metadata(self, key: str, payload: Dict[str, object]) -> None:
        if self.fail_publish:
            raise PublishError(f"fake publish failure key={key}")
        self.messages.append({"topic": self.topic, "key": key, "payload": payload})


def resolve_ssl_ca_location(configured_path: str) -> str:
    if configured_path and os.path.exists(configured_path):
        return configured_path

    for candidate in COMMON_SSL_CA_LOCATIONS:
        if os.path.exists(candidate):
            return candidate

    return configured_path or DEFAULT_SSL_CA_LOCATION


def configured_flush_timeout_seconds(config: KafkaPublisherConfig) -> float:
    timeout_ms = config.flush_timeout_ms or config.delivery_timeout_ms
    return max(timeout_ms / 1000.0, 1.0)


def build_page_metadata_publisher(settings) -> PageMetadataPublisher:
    config = KafkaPublisherConfig(
        bootstrap_servers=settings.get("KAFKA_BOOTSTRAP_SERVERS"),
        topic_page_metadata=settings.get("KAFKA_TOPIC_PAGE_METADATA", "crawler.page-metadata.v1"),
        security_protocol=settings.get("KAFKA_SECURITY_PROTOCOL", "SASL_SSL"),
        sasl_mechanism=settings.get("KAFKA_SASL_MECHANISM", "SCRAM-SHA-512"),
        username=settings.get("KAFKA_USERNAME", ""),
        password=settings.get("KAFKA_PASSWORD", ""),
        ssl_ca_location=settings.get("KAFKA_SSL_CA_LOCATION", DEFAULT_SSL_CA_LOCATION),
        batch_size=settings.getint("KAFKA_BATCH_SIZE", 100),
        retries=settings.getint("KAFKA_PRODUCER_RETRIES", 3),
        request_timeout_ms=settings.getint("KAFKA_REQUEST_TIMEOUT_MS", 30000),
        delivery_timeout_ms=settings.getint("KAFKA_DELIVERY_TIMEOUT_MS", 120000),
        flush_timeout_ms=settings.getint("KAFKA_FLUSH_TIMEOUT_MS", 130000),
    )
    return ConfluentKafkaPageMetadataPublisher(config)
