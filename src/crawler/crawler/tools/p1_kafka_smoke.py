from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone

from crawler.attempts import build_attempt_id
from crawler.publisher import PublishError, build_crawl_attempt_publisher
from crawler.schemas import CRAWL_ATTEMPT_SCHEMA_VERSION, validate_crawl_attempt
from crawler.tools._env import EnvSettings


def main() -> int:
    settings = EnvSettings()
    publisher = build_crawl_attempt_publisher(settings)
    now = datetime.now(timezone.utc)
    url = "https://example.com/p1-kafka-smoke"
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    snapshot_id = f"{url_hash}:{int(now.timestamp() * 1000)}"
    attempt_id = build_attempt_id(url_hash, now)
    payload = {
        "schema_version": CRAWL_ATTEMPT_SCHEMA_VERSION,
        "attempt_id": attempt_id,
        "snapshot_id": snapshot_id,
        "url_hash": url_hash,
        "canonical_url": url,
        "original_url": url,
        "host": "example.com",
        "attempted_at": now.isoformat().replace("+00:00", "Z"),
        "finished_at": now.isoformat().replace("+00:00", "Z"),
        "fetch_result": "succeeded",
        "status_code": 200,
        "content_type": "text/html",
        "response_headers": {"content-type": "text/html"},
        "response_time_ms": 1,
        "bytes_downloaded": 14,
        "error_type": None,
        "error_message": None,
        "content_result": "html_snapshot_candidate",
        "outlinks_count": 0,
        "outlinks_external_count": 0,
        "storage_result": "stored",
        "content_sha256": hashlib.sha256(b"p1 kafka smoke").hexdigest(),
        "storage_provider": "oci",
        "bucket": settings.get("OCI_OBJECT_STORAGE_BUCKET", "clawer_content_staging"),
        "storage_key": f"smoke/p1/kafka-smoke-{snapshot_id}.html.gz",
        "storage_etag": None,
        "compression": "gzip",
        "uncompressed_size": 14,
        "compressed_size": 34,
        "egress_local_ip": None,
        "observed_egress_ip": None,
    }
    validate_crawl_attempt(payload)
    try:
        publisher.publish_crawl_attempt(attempt_id, payload)
    except PublishError as exc:
        print(f"p1_kafka_smoke_failed error={exc}", file=sys.stderr)
        return 1

    print("p1_kafka_smoke_ok")
    print(f"topic={publisher.topic}")
    print(f"key={attempt_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
