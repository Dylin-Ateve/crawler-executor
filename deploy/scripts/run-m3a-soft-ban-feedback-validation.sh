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

from crawler.fetch_safety_state import FetchSafetyStateStore
from crawler.response_signals import FeedbackSignal, SIGNAL_CAPTCHA_CHALLENGE, SIGNAL_HTTP_429
from crawler.soft_ban_feedback import SoftBanFeedbackConfig, SoftBanFeedbackController


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.ttls = {}

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update({field: str(value) for field, value in mapping.items()})

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def hincrby(self, key, field, amount):
        self.hashes.setdefault(key, {})
        self.hashes[key][field] = str(int(self.hashes[key].get(field, 0)) + int(amount))
        return int(self.hashes[key][field])

    def expire(self, key, ttl):
        self.ttls[key] = int(ttl)
        return True


def signal(host_hash: str, identity_hash: str, signal_type: str):
    return FeedbackSignal(
        signal_type=signal_type,
        host="example.com",
        host_hash=host_hash,
        identity_hash=identity_hash,
        status_code=429 if signal_type == SIGNAL_HTTP_429 else 200,
        matched_pattern="challenge" if signal_type == SIGNAL_CAPTCHA_CHALLENGE else None,
        weight=5,
        observed_at_ms=1000,
    )


redis = FakeRedis()
controller = SoftBanFeedbackController(
    FetchSafetyStateStore(redis),
    config=SoftBanFeedbackConfig(
        host_ip_soft_ban_threshold=2,
        ip_cross_host_challenge_threshold=2,
        host_cross_ip_challenge_threshold=2,
        host_asn_soft_limit_enabled=True,
    ),
)

first = controller.record_signal(signal("host-a", "ip-a", SIGNAL_HTTP_429), now_ms=1000)
second = controller.record_signal(signal("host-a", "ip-a", SIGNAL_HTTP_429), now_ms=2000)
controller.record_signal(signal("host-a", "ip-a", SIGNAL_CAPTCHA_CHALLENGE), asn="AS31898", now_ms=3000)
cross_ip = controller.record_signal(signal("host-a", "ip-b", SIGNAL_CAPTCHA_CHALLENGE), asn="AS31898", now_ms=4000)
cross_host = controller.record_signal(signal("host-b", "ip-a", SIGNAL_CAPTCHA_CHALLENGE), now_ms=5000)

if first.host_ip_backoff or not second.host_ip_backoff:
    raise SystemExit("m3a_soft_ban_feedback_validation_failed: host-ip backoff threshold mismatch")
if not cross_ip.host_slowdown:
    raise SystemExit("m3a_soft_ban_feedback_validation_failed: host slowdown was not triggered")
if not cross_ip.host_asn_soft_limit:
    raise SystemExit("m3a_soft_ban_feedback_validation_failed: host ASN soft limit was not triggered")
if not cross_host.ip_cooldown:
    raise SystemExit("m3a_soft_ban_feedback_validation_failed: IP cooldown was not triggered")
if not all(ttl > 0 for ttl in redis.ttls.values()):
    raise SystemExit("m3a_soft_ban_feedback_validation_failed: missing TTL on execution state")

print("m3a_soft_ban_feedback_validation_ok")
print("keys=" + ",".join(sorted(redis.hashes)))
PY
