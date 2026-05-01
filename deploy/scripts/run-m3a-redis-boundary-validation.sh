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

import os

from crawler.fetch_safety_state import audit_redis_key_diff

prefix = os.getenv("EXECUTION_STATE_REDIS_PREFIX", "crawler:exec:safety")
stream = os.getenv("FETCH_QUEUE_STREAM", "crawl:tasks")

before = {stream}
after = {
    stream,
    f"{prefix}:host_ip:hosthash:identityhash",
    f"{prefix}:ip:identityhash",
    f"{prefix}:host:hosthash",
    f"{prefix}:signal:host_ip:combined:http_429",
}
ttl_by_key = {key: 300 for key in after if key != stream}
result = audit_redis_key_diff(
    before_keys=before,
    after_keys=after,
    prefix=prefix,
    ttl_by_key=ttl_by_key,
    allowed_extra_prefixes=(stream,),
)

if not result.passed:
    raise SystemExit(
        "m3a_redis_boundary_validation_failed: "
        f"out_of_prefix={sorted(result.out_of_prefix_keys)} "
        f"forbidden={sorted(result.forbidden_keys)} "
        f"missing_ttl={sorted(result.missing_ttl_keys)}"
    )

negative = audit_redis_key_diff(
    before_keys=set(),
    after_keys={f"{prefix}:priority:bad", "crawler:scheduler:queue"},
    prefix=prefix,
    ttl_by_key={f"{prefix}:priority:bad": 300, "crawler:scheduler:queue": 300},
)
if negative.passed:
    raise SystemExit("m3a_redis_boundary_validation_failed: negative audit did not detect forbidden keys")

print("m3a_redis_boundary_validation_ok")
print("allowed_new_keys=" + ",".join(sorted(result.new_keys)))
PY
