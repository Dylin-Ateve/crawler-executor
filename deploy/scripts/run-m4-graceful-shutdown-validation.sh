#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python"
fi

"${PYTHON_BIN}" - <<'PY'
from crawler.queues import RedisStreamsFetchConsumer


class Redis:
    def xreadgroup(self, *_args, **_kwargs):
        raise AssertionError("xreadgroup must not be called after shutdown")

    def xautoclaim(self, *_args, **_kwargs):
        raise AssertionError("xautoclaim must not be called after shutdown")


consumer = RedisStreamsFetchConsumer(
    Redis(),
    stream="crawl:tasks:test",
    group="crawler-executor",
    consumer="m4-shutdown",
)
consumer.request_shutdown()

assert consumer.read() == []
assert consumer.reclaim_pending() == []
print("m4_graceful_shutdown_validation_ok")
PY
