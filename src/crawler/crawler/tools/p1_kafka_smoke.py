from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone

from crawler.publisher import PublishError, build_page_metadata_publisher
from crawler.schemas import PAGE_METADATA_SCHEMA_VERSION, validate_page_metadata
from crawler.tools._env import EnvSettings


def main() -> int:
    settings = EnvSettings()
    publisher = build_page_metadata_publisher(settings)
    now = datetime.now(timezone.utc)
    url = "https://example.com/p1-kafka-smoke"
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    snapshot_id = f"{url_hash}:{int(now.timestamp() * 1000)}"
    payload = {
        "schema_version": PAGE_METADATA_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "url_hash": url_hash,
        "canonical_url": url,
        "original_url": url,
        "host": "example.com",
        "fetched_at": now.isoformat().replace("+00:00", "Z"),
        "status_code": 200,
        "content_type": "text/html",
        "response_headers": {"content-type": "text/html"},
        "content_sha256": hashlib.sha256(b"p1 kafka smoke").hexdigest(),
        "storage_provider": "oci",
        "bucket": settings.get("OCI_OBJECT_STORAGE_BUCKET", "clawer_content_staging"),
        "storage_key": f"smoke/p1/kafka-smoke-{snapshot_id}.html.gz",
        "storage_etag": None,
        "compression": "gzip",
        "uncompressed_size": 14,
        "compressed_size": 34,
        "outlinks_count": 0,
        "outlinks_external_count": 0,
        "egress_local_ip": None,
        "observed_egress_ip": None,
    }
    validate_page_metadata(payload)
    try:
        publisher.publish_page_metadata(snapshot_id, payload)
    except PublishError as exc:
        print(f"p1_kafka_smoke_failed error={exc}", file=sys.stderr)
        return 1

    print("p1_kafka_smoke_ok")
    print(f"topic={publisher.topic}")
    print(f"key={snapshot_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
