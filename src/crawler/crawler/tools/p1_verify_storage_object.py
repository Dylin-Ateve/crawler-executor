from __future__ import annotations

import gzip
import sys

from crawler.storage import StorageError, build_object_storage_client
from crawler.tools._env import EnvSettings


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m crawler.tools.p1_verify_storage_object <storage-key>", file=sys.stderr)
        return 2

    key = args[0]
    settings = EnvSettings()
    client = build_object_storage_client(settings)
    try:
        downloaded = client.get_object(key)
        actual = gzip.decompress(downloaded)
    except StorageError as exc:
        print(f"p1_storage_object_verify_failed key={key} error={exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"p1_storage_object_verify_failed key={key} error=invalid_gzip detail={exc}", file=sys.stderr)
        return 1

    print("p1_storage_object_verify_ok")
    print(f"key={key}")
    print(f"verified_uncompressed_size={len(actual)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
