#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

"${PYTHON_BIN}" - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

import shlex
import sys
from pathlib import Path

root = Path(sys.argv[1])
production = root / "deploy" / "environments" / "production.env"
staging = root / "deploy" / "environments" / "staging.env"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = shlex.split(value, comments=False, posix=True)[0] if value.strip() else ""
    return values


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"m3a_config_audit_failed: {message}")


prod = load_env(production)
stage = load_env(staging)

require(prod.get("EGRESS_SELECTION_STRATEGY") == "STICKY_POOL", "production EGRESS_SELECTION_STRATEGY must be STICKY_POOL")
require(prod.get("IP_SELECTION_STRATEGY") == "STICKY_POOL", "production IP_SELECTION_STRATEGY must be STICKY_POOL during 005")
require(prod.get("STOP_READING_WHEN_DELAYED_BUFFER_FULL") == "true", "production delayed-buffer backpressure must be enabled")
require(int(prod.get("LOCAL_DELAYED_BUFFER_CAPACITY", "0")) > 0, "production LOCAL_DELAYED_BUFFER_CAPACITY must be positive")
require(int(prod.get("MAX_LOCAL_DELAY_SECONDS", "0")) > 0, "production MAX_LOCAL_DELAY_SECONDS must be positive")
require(int(prod.get("FETCH_QUEUE_CLAIM_MIN_IDLE_MS", "0")) >= 600000,
        "production FETCH_QUEUE_CLAIM_MIN_IDLE_MS must cover delayed buffer and publish window")
require(prod.get("EXECUTION_STATE_WRITE_ENABLED") == "true", "production execution-state writes must be enabled")
require(stage.get("EGRESS_SELECTION_STRATEGY") == "STICKY_POOL", "staging EGRESS_SELECTION_STRATEGY must mirror production")
require(stage.get("IP_SELECTION_STRATEGY") == "STICKY_POOL", "staging IP_SELECTION_STRATEGY must mirror production")
require(stage.get("EXECUTION_STATE_WRITE_ENABLED") == "true", "staging execution-state writes must be enabled for mirrored validation")
require(int(stage.get("FETCH_QUEUE_CLAIM_MIN_IDLE_MS", "0")) == int(prod.get("FETCH_QUEUE_CLAIM_MIN_IDLE_MS", "0")),
        "staging FETCH_QUEUE_CLAIM_MIN_IDLE_MS should mirror production")
require(stage.get("M3_K8S_NAMESPACE") == prod.get("M3_K8S_NAMESPACE"), "staging namespace should match production in isolated cluster")
require(stage.get("M3_NODE_SELECTOR_KEY") == prod.get("M3_NODE_SELECTOR_KEY"), "staging node selector key should match production")
require(stage.get("M3_NODE_LABEL") == prod.get("M3_NODE_LABEL"), "staging node label should match production")

exec_prefix = prod.get("EXECUTION_STATE_REDIS_PREFIX", "").rstrip(":")
stream = prod.get("FETCH_QUEUE_STREAM", "").rstrip(":")
group = prod.get("FETCH_QUEUE_GROUP", "").rstrip(":")
require(bool(exec_prefix), "EXECUTION_STATE_REDIS_PREFIX is required")
require(exec_prefix != stream, "EXECUTION_STATE_REDIS_PREFIX must not equal FETCH_QUEUE_STREAM")
require(exec_prefix != group, "EXECUTION_STATE_REDIS_PREFIX must not equal FETCH_QUEUE_GROUP")
require(not exec_prefix.startswith(f"{stream}:") and not stream.startswith(f"{exec_prefix}:"),
        "execution-state prefix must be isolated from fetch stream prefix")

stage_exec_prefix = stage.get("EXECUTION_STATE_REDIS_PREFIX", "").rstrip(":")
require(stage_exec_prefix != exec_prefix,
        "staging and production execution-state prefixes must differ")
stage_stream = stage.get("FETCH_QUEUE_STREAM", "").rstrip(":")
stage_group = stage.get("FETCH_QUEUE_GROUP", "").rstrip(":")
require(bool(stage_exec_prefix), "staging EXECUTION_STATE_REDIS_PREFIX is required")
require(stage_exec_prefix != stage_stream, "staging EXECUTION_STATE_REDIS_PREFIX must not equal FETCH_QUEUE_STREAM")
require(stage_exec_prefix != stage_group, "staging EXECUTION_STATE_REDIS_PREFIX must not equal FETCH_QUEUE_GROUP")

print("m3a_config_audit_ok")
print(f"production_egress_strategy={prod.get('EGRESS_SELECTION_STRATEGY')}")
print(f"production_execution_state_prefix={exec_prefix}")
print(f"staging_egress_strategy={stage.get('EGRESS_SELECTION_STRATEGY')}")
print(f"staging_execution_state_prefix={stage_exec_prefix}")
PY
