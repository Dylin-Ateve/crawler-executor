from __future__ import annotations

import gzip
import sys
from datetime import datetime, timezone

from crawler.storage import StorageError, build_object_storage_client
from crawler.tools._env import EnvSettings


def main() -> int:
    settings = EnvSettings()
    client = build_object_storage_client(settings)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"smoke/p1/object-storage-smoke-{timestamp}.txt.gz"
    expected = b"crawler p1 object storage smoke\n"
    body = gzip.compress(expected)
    try:
        stored = client.put_object(
            key,
            body,
            content_type="text/plain",
            content_encoding=None,
            metadata={"purpose": "p1-smoke", "compression": "gzip"},
        )
        downloaded = client.get_object(key)
    except StorageError as exc:
        print(f"p1_object_storage_smoke_failed error={exc}", file=sys.stderr)
        return 1
    try:
        actual = gzip.decompress(downloaded)
    except OSError as exc:
        print(f"p1_object_storage_smoke_failed error=invalid_gzip key={key} detail={exc}", file=sys.stderr)
        return 1

    if actual != expected:
        print(f"p1_object_storage_smoke_failed error=content_mismatch key={key}", file=sys.stderr)
        return 1

    print("p1_object_storage_smoke_ok")
    print(f"provider={stored.provider}")
    print(f"bucket={stored.bucket}")
    print(f"key={stored.key}")
    print(f"etag={stored.etag}")
    print(f"verified_uncompressed_size={len(actual)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
