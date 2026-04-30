#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"
export CRAWL_INTERFACE="${CRAWL_INTERFACE:-enp0s5}"
export EXCLUDED_LOCAL_IPS="${EXCLUDED_LOCAL_IPS:-}"
export M3_IP_POOL_MIN_EXPECTED="${M3_IP_POOL_MIN_EXPECTED:-1}"
export M3_IP_POOL_MAX_EXPECTED="${M3_IP_POOL_MAX_EXPECTED:-0}"
export M3_IP_POOL_EXPECTED_RANGE="${M3_IP_POOL_EXPECTED_RANGE:-}"

"${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import json
import os
import socket
from typing import Dict, List

from crawler.ip_pool import LocalIpPool, discover_local_ips


def csv_env(name: str) -> List[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def interface_ipv4_snapshot() -> Dict[str, List[str]]:
    try:
        import psutil
    except ImportError:
        return {}

    snapshot: Dict[str, List[str]] = {}
    for name, addrs in psutil.net_if_addrs().items():
        ipv4 = [
            addr.address
            for addr in addrs
            if getattr(addr, "family", None) == socket.AF_INET and getattr(addr, "address", None)
        ]
        if ipv4:
            snapshot[name] = ipv4
    return snapshot


interface = os.environ["CRAWL_INTERFACE"]
excluded = csv_env("EXCLUDED_LOCAL_IPS")
min_expected = int(os.environ["M3_IP_POOL_MIN_EXPECTED"])
max_expected = int(os.environ["M3_IP_POOL_MAX_EXPECTED"])
expected_range = os.environ["M3_IP_POOL_EXPECTED_RANGE"].strip()
discovered = discover_local_ips(interface, excluded)
snapshot = interface_ipv4_snapshot()

if expected_range:
    left, sep, right = expected_range.partition("-")
    if not sep:
        raise SystemExit(f"invalid M3_IP_POOL_EXPECTED_RANGE: {expected_range}")
    min_expected = int(left)
    max_expected = int(right)

pool_size = 0
pool_error = ""
try:
    pool = LocalIpPool(discovered)
    pool_size = len(pool.ip_pool)
except Exception as exc:
    pool_error = str(exc)

payload = {
    "hostname": socket.gethostname(),
    "crawl_interface": interface,
    "excluded_local_ips": excluded,
    "all_interface_ipv4": snapshot,
    "discovered_ip_count": len(discovered),
    "discovered_ips": discovered,
    "min_expected": min_expected,
    "max_expected": max_expected,
    "expected_range": expected_range,
    "local_ip_pool_size": pool_size,
    "local_ip_pool_error": pool_error,
}

print("m3_ip_pool_inspect_result")
print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))

if len(discovered) < min_expected:
    raise SystemExit(
        "m3_ip_pool_inspect_failed "
        f"interface={interface} discovered={len(discovered)} min_expected={min_expected}"
    )

unexpected_excluded = sorted(set(discovered).intersection(excluded))
if unexpected_excluded:
    raise SystemExit(
        "m3_ip_pool_inspect_failed "
        f"interface={interface} excluded_ip_present={','.join(unexpected_excluded)}"
    )

if max_expected and len(discovered) > max_expected:
    raise SystemExit(
        "m3_ip_pool_inspect_failed "
        f"interface={interface} discovered={len(discovered)} max_expected={max_expected}"
    )

if discovered and pool_size != len(discovered):
    raise SystemExit(
        "m3_ip_pool_inspect_failed "
        f"interface={interface} discovered={len(discovered)} local_ip_pool_size={pool_size}"
    )

print(f"m3_ip_pool_inspect_ok interface={interface} discovered={len(discovered)} pool_size={pool_size}")
PY
