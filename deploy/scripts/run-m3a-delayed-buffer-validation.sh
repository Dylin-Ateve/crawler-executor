#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi
export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"

"${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

from crawler.queues import parse_fetch_command
from crawler.spiders.fetch_queue import LocalDelayedBuffer, LocalDelayedFetchCommand


def command(url: str = "https://example.com/page"):
    return parse_fetch_command({"url": url, "canonical_url": url, "job_id": "validation"}, stream_id="1-0")


buffer = LocalDelayedBuffer(capacity=1)
first = LocalDelayedFetchCommand(command(), "1-0", 3000, 1000, "host_ip_pacer", "identity-a")
second = LocalDelayedFetchCommand(command(), "2-0", 2000, 1000, "host_ip_pacer", "identity-b")

if not buffer.add(first):
    raise SystemExit("m3a_delayed_buffer_validation_failed: first delayed command was rejected")
if buffer.add(second):
    raise SystemExit("m3a_delayed_buffer_validation_failed: buffer accepted item beyond capacity")
if not buffer.is_full:
    raise SystemExit("m3a_delayed_buffer_validation_failed: full buffer was not reported")
if buffer.pop_due(2999):
    raise SystemExit("m3a_delayed_buffer_validation_failed: command popped before eligible_at_ms")
due = buffer.pop_due(3000)
if due != [first]:
    raise SystemExit("m3a_delayed_buffer_validation_failed: due command order mismatch")

print("m3a_delayed_buffer_validation_ok")
print("capacity=1 suppressed_read_expected=true unacked_until_executed=true")
PY
