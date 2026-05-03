#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python"
fi

"${PYTHON_BIN}" - <<'PY'
import json
import tempfile
from pathlib import Path

from crawler.policy_provider import FileRuntimePolicyProvider
from crawler.runtime_policy import make_bootstrap_policy_document


class Settings:
    def get(self, name, default=None):
        return default

    def getint(self, name, default=0):
        return default


def policy(version, delay):
    return {
        "schema_version": "1.0",
        "version": version,
        "generated_at": "2026-05-03T10:00:00Z",
        "default_policy": {
            "enabled": True,
            "paused": False,
            "egress_selection_strategy": "STICKY_POOL",
            "host_ip_min_delay_ms": delay,
            "max_retries": 2,
        },
    }


with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "policy.json"
    path.write_text(json.dumps(policy("policy-m4-001", 2000)), encoding="utf-8")
    provider = FileRuntimePolicyProvider(
        str(path),
        bootstrap_document=make_bootstrap_policy_document(Settings()),
        reload_interval_seconds=1,
    )
    first = provider.current(force=True)
    path.write_text(json.dumps(policy("policy-m4-002", 5000)), encoding="utf-8")
    second = provider.current(force=True)

assert first.document.version == "policy-m4-001"
assert second.document.version == "policy-m4-002"
assert second.document.default_policy.host_ip_min_delay_ms == 5000
print("m4_policy_reload_validation_ok")
PY
