from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional
from urllib.parse import urljoin, urlsplit

from crawler.contracts.canonical_url import build_canonical_url
from crawler.metrics import metrics
from crawler.publisher import PageMetadataPublisher, PublishError, build_page_metadata_publisher
from crawler.schemas import PAGE_METADATA_SCHEMA_VERSION, filter_headers, validate_page_metadata
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
        publisher: PageMetadataPublisher,
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
            publisher=build_page_metadata_publisher(settings),
            compression=settings.get("CONTENT_COMPRESSION", "gzip"),
        )

    def process_item(self, item, spider):
        if not item.get("p1_candidate"):
            return item

        status_code = int(item.get("status_code") or 0)
        content_type = str(item.get("content_type") or "")
        if status_code != 200:
            return self._skip(item, "non_200_status", spider)
        if not is_html_content_type(content_type):
            return self._skip(item, "non_html_content", spider)

        now = item.get("fetched_at_dt") or datetime.now(timezone.utc)
        canonical = build_canonical_url(str(item["url"]))
        snapshot_id = build_snapshot_id(canonical.url_hash, now)
        artifact = build_content_artifact(bytes(item.get("body") or b""))
        host = canonical_host(canonical.canonical_url)
        storage_key = build_storage_key(host, canonical.url_hash, snapshot_id, now)
        outlink_counts = count_outlinks(str(item["url"]), item.get("outlinks") or [])

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
            return item

        payload = build_page_metadata_payload(
            item=item,
            canonical_url=canonical.canonical_url,
            url_hash=canonical.url_hash,
            snapshot_id=snapshot_id,
            fetched_at=now,
            artifact=artifact,
            storage_provider=stored.provider,
            bucket=stored.bucket,
            storage_key=stored.key,
            storage_etag=stored.etag,
            outlinks_count=outlink_counts["total"],
            outlinks_external_count=outlink_counts["external"],
            header_allowlist=self.header_allowlist,
        )
        validate_page_metadata(payload)

        try:
            self.publisher.publish_page_metadata(snapshot_id, payload)
            metrics.record_kafka_publish(self.publisher.topic, "success")
        except PublishError as exc:
            metrics.record_kafka_publish(self.publisher.topic, "failure")
            spider.logger.error(
                "p1_kafka_publish_failed url=%s snapshot_id=%s storage_key=%s error=%s",
                item.get("url"),
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
        item["p1_url_hash"] = canonical.url_hash
        spider.logger.info(
            "p1_page_metadata_published url=%s snapshot_id=%s storage_key=%s",
            item.get("url"),
            snapshot_id,
            stored.key,
        )
        return item

    @staticmethod
    def _skip(item, reason: str, spider):
        metrics.record_content_skip(reason)
        item["p1_persisted"] = False
        item["p1_published"] = False
        item["p1_skip_reason"] = reason
        spider.logger.info("p1_content_skipped url=%s reason=%s", item.get("url"), reason)
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


def build_page_metadata_payload(
    *,
    item: Dict[str, object],
    canonical_url: str,
    url_hash: str,
    snapshot_id: str,
    fetched_at: datetime,
    artifact: ContentArtifact,
    storage_provider: str,
    bucket: str,
    storage_key: str,
    storage_etag: Optional[str],
    outlinks_count: int,
    outlinks_external_count: int,
    header_allowlist: Iterable[str],
) -> Dict[str, object]:
    headers = item.get("response_headers") or {}
    return {
        "schema_version": PAGE_METADATA_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "url_hash": url_hash,
        "canonical_url": canonical_url,
        "original_url": item["url"],
        "host": canonical_host(canonical_url),
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
        "status_code": int(item.get("status_code") or 0),
        "content_type": item.get("content_type"),
        "response_headers": filter_headers(headers, header_allowlist),
        "content_sha256": artifact.content_sha256,
        "storage_provider": storage_provider,
        "bucket": bucket,
        "storage_key": storage_key,
        "storage_etag": storage_etag,
        "compression": "gzip",
        "uncompressed_size": artifact.uncompressed_size,
        "compressed_size": artifact.compressed_size,
        "outlinks_count": outlinks_count,
        "outlinks_external_count": outlinks_external_count,
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
