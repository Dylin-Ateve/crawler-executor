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
    body = gzip.compress(b"crawler p1 object storage smoke\n")
    try:
        stored = client.put_object(
            key,
            body,
            content_type="text/plain",
            content_encoding="gzip",
            metadata={"purpose": "p1-smoke"},
        )
    except StorageError as exc:
        print(f"p1_object_storage_smoke_failed error={exc}", file=sys.stderr)
        return 1

    print("p1_object_storage_smoke_ok")
    print(f"provider={stored.provider}")
    print(f"bucket={stored.bucket}")
    print(f"key={stored.key}")
    print(f"etag={stored.etag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
