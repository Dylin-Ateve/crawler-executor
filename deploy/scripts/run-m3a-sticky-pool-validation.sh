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

from crawler.egress_identity import resolve_egress_identities
from crawler.egress_policy import build_sticky_pool_assignment, select_from_sticky_pool

host = os.getenv("M3A_TEST_HOST", "example.com")
pool_size = int(os.getenv("STICKY_POOL_SIZE", "4"))
bind_ips = [item.strip() for item in os.getenv("LOCAL_IP_POOL", "10.0.0.2,10.0.0.3,10.0.0.4,10.0.0.5,10.0.0.6").split(",") if item.strip()]
if not bind_ips:
    raise SystemExit("m3a_sticky_pool_validation_failed: LOCAL_IP_POOL is empty")

identities = resolve_egress_identities(
    bind_ips,
    identity_source=os.getenv("EGRESS_IDENTITY_SOURCE", "auto"),
    allow_bind_ip=os.getenv("ALLOW_BIND_IP_AS_EGRESS_IDENTITY", "true").lower() in {"1", "true", "yes", "on"},
    hash_salt=os.getenv("EGRESS_IDENTITY_HASH_SALT", "validation"),
)

first = build_sticky_pool_assignment(host, identities, pool_size=pool_size, hash_salt="validation", now_ms=1000)
second = build_sticky_pool_assignment(host, identities, pool_size=pool_size, hash_salt="validation", now_ms=2000)
expected_size = min(pool_size, len(identities))

if first.pool_size_actual != expected_size:
    raise SystemExit(f"m3a_sticky_pool_validation_failed: pool_size_actual={first.pool_size_actual}, expected={expected_size}")
if first.candidate_identity_hashes != second.candidate_identity_hashes:
    raise SystemExit("m3a_sticky_pool_validation_failed: candidate pool is not stable")

cooled = first.candidate_identities[0]
selected = select_from_sticky_pool(first, is_in_cooldown=lambda identity: identity.identity_hash == cooled.identity_hash)
if selected.identity_hash == cooled.identity_hash and len(first.candidate_identities) > 1:
    raise SystemExit("m3a_sticky_pool_validation_failed: cooldown identity was selected despite alternatives")

print("m3a_sticky_pool_validation_ok")
print(f"host={first.host} requested_pool_size={pool_size} actual_pool_size={first.pool_size_actual}")
print("candidate_identity_hashes=" + ",".join(first.candidate_identity_hashes))
PY
