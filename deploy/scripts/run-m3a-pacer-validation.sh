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

from crawler.politeness import HostIpPacerConfig, HostIpPacerState, mark_backoff, mark_request_started, pacer_decision

min_delay = int(os.getenv("HOST_IP_MIN_DELAY_MS", "2000"))
config = HostIpPacerConfig(
    min_delay_ms=min_delay,
    jitter_ms=0,
    backoff_base_ms=int(os.getenv("HOST_IP_BACKOFF_BASE_MS", "5000")),
    backoff_max_ms=int(os.getenv("HOST_IP_BACKOFF_MAX_MS", "300000")),
    backoff_multiplier=float(os.getenv("HOST_IP_BACKOFF_MULTIPLIER", "2.0")),
)

started = mark_request_started(HostIpPacerState(), config, 100000, host_slowdown_factor=1.0)
decision_before = pacer_decision(started, 100000 + min_delay - 1)
decision_at = pacer_decision(started, 100000 + min_delay)
backoff = mark_backoff(started, config, 200000, signal_type="http_429")

if decision_before.eligible:
    raise SystemExit("m3a_pacer_validation_failed: request became eligible before min delay")
if not decision_at.eligible:
    raise SystemExit("m3a_pacer_validation_failed: request did not become eligible at min delay")
if backoff.next_allowed_at_ms <= 200000:
    raise SystemExit("m3a_pacer_validation_failed: backoff did not advance next_allowed_at_ms")

print("m3a_pacer_validation_ok")
print(f"min_delay_ms={min_delay} delay_before_ms={decision_before.delay_ms} backoff_delay_ms={backoff.next_allowed_at_ms - 200000}")
PY
