#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"

"${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import json
import time
from urllib.error import HTTPError
from urllib.request import urlopen

from crawler.health import (
    HealthCheckServer,
    RuntimeHealthState,
    mark_worker_initialized,
    record_consumer_heartbeat,
)
from crawler.metrics import metrics


def get_json(url: str):
    try:
        response = urlopen(url, timeout=3)
    except HTTPError as exc:
        response = exc
    with response:
        body = response.read().decode("utf-8")
        return response.code, json.loads(body)


state = RuntimeHealthState(live=True)
server = HealthCheckServer(port=0, state=state, max_heartbeat_age_seconds=30)
server.start()
port = server._server.server_address[1]
base_url = f"http://127.0.0.1:{port}"

try:
    liveness_status, liveness_payload = get_json(f"{base_url}/health/liveness")
    if liveness_status != 200:
        raise SystemExit(f"m3_health_probe_failed liveness_status={liveness_status}")

    readiness_status, _readiness_payload = get_json(f"{base_url}/health/readiness")
    if readiness_status != 503:
        raise SystemExit(f"m3_health_probe_failed readiness_before_init_status={readiness_status}")

    for dependency in ("redis", "kafka", "oci"):
        metrics.record_dependency_health(dependency, False)

    liveness_after_failure_status, liveness_after_failure_payload = get_json(f"{base_url}/health/liveness")
    if liveness_after_failure_status != 200:
        raise SystemExit(
            "m3_health_probe_failed "
            f"liveness_after_dependency_failure_status={liveness_after_failure_status}"
        )

    now = time.time()
    mark_worker_initialized(state, now=now)
    record_consumer_heartbeat(state, now=now)
    readiness_after_heartbeat_status, readiness_after_heartbeat_payload = get_json(f"{base_url}/health/readiness")
    if readiness_after_heartbeat_status != 200:
        raise SystemExit(
            "m3_health_probe_failed "
            f"readiness_after_heartbeat_status={readiness_after_heartbeat_status}"
        )

    print("m3_health_probe_validation_ok")
    print(json.dumps({
        "liveness": liveness_payload,
        "liveness_after_dependency_failures": liveness_after_failure_payload,
        "readiness_after_heartbeat": readiness_after_heartbeat_payload,
    }, ensure_ascii=False, sort_keys=True, indent=2))
finally:
    if server._server is not None:
        server._server.shutdown()
PY
