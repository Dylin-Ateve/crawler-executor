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
        self.hashes[key][field] = str(int(self.hashes[key].get(field, 0)) + amount)
        return int(self.hashes[key][field])

    def expire(self, key, ttl):
        self.ttls[key] = ttl
        return True


def _signal(host_hash="host-a", identity_hash="ip-a", signal_type=SIGNAL_CAPTCHA_CHALLENGE):
    return FeedbackSignal(
        signal_type=signal_type,
        host="example.com",
        host_hash=host_hash,
        identity_hash=identity_hash,
        status_code=429 if signal_type == SIGNAL_HTTP_429 else 200,
        matched_pattern="challenge" if signal_type == SIGNAL_CAPTCHA_CHALLENGE else None,
        weight=5 if signal_type == SIGNAL_CAPTCHA_CHALLENGE else 3,
        observed_at_ms=1000,
    )


def test_host_ip_backoff_triggers_after_threshold():
    redis = FakeRedis()
    controller = SoftBanFeedbackController(
        FetchSafetyStateStore(redis),
        config=SoftBanFeedbackConfig(host_ip_soft_ban_threshold=2),
    )

    first = controller.record_signal(_signal(signal_type=SIGNAL_HTTP_429), now_ms=1000)
    second = controller.record_signal(_signal(signal_type=SIGNAL_HTTP_429), now_ms=2000)

    assert first.host_ip_backoff is False
    assert second.host_ip_backoff is True
    assert "crawler:exec:safety:host_ip:host-a:ip-a" in redis.hashes


def test_ip_cooldown_counts_distinct_hosts_for_same_identity():
    redis = FakeRedis()
    controller = SoftBanFeedbackController(
        FetchSafetyStateStore(redis),
        config=SoftBanFeedbackConfig(ip_cross_host_challenge_threshold=2),
    )

    duplicate = controller.record_signal(_signal(host_hash="host-a", identity_hash="ip-a"), now_ms=1000)
    still_duplicate = controller.record_signal(_signal(host_hash="host-a", identity_hash="ip-a"), now_ms=2000)
    crossed = controller.record_signal(_signal(host_hash="host-b", identity_hash="ip-a"), now_ms=3000)

    assert duplicate.ip_cooldown is False
    assert still_duplicate.ip_cooldown is False
    assert crossed.ip_cooldown is True
    assert redis.hashes["crawler:exec:safety:ip:ip-a"]["reason"] == "cross_host_challenge"


def test_host_slowdown_counts_distinct_identities_for_same_host():
    redis = FakeRedis()
    controller = SoftBanFeedbackController(
        FetchSafetyStateStore(redis),
        config=SoftBanFeedbackConfig(host_cross_ip_challenge_threshold=2),
    )

    controller.record_signal(_signal(host_hash="host-a", identity_hash="ip-a"), now_ms=1000)
    duplicate = controller.record_signal(_signal(host_hash="host-a", identity_hash="ip-a"), now_ms=2000)
    crossed = controller.record_signal(_signal(host_hash="host-a", identity_hash="ip-b"), now_ms=3000)

    assert duplicate.host_slowdown is False
    assert crossed.host_slowdown is True
    assert redis.hashes["crawler:exec:safety:host:host-a"]["reason"] == "multi_ip_challenge"


def test_host_asn_soft_limit_is_optional_and_counts_distinct_identities():
    redis = FakeRedis()
    controller = SoftBanFeedbackController(
        FetchSafetyStateStore(redis),
        config=SoftBanFeedbackConfig(
            host_asn_soft_limit_enabled=True,
            host_cross_ip_challenge_threshold=2,
        ),
    )

    disabled_without_asn = controller.record_signal(_signal(host_hash="host-a", identity_hash="ip-a"), now_ms=1000)
    controller.record_signal(_signal(host_hash="host-a", identity_hash="ip-a"), asn="AS31898", now_ms=2000)
    crossed = controller.record_signal(_signal(host_hash="host-a", identity_hash="ip-b"), asn="AS31898", now_ms=3000)

    assert disabled_without_asn.host_asn_soft_limit is False
    assert crossed.host_asn_soft_limit is True
    assert redis.hashes["crawler:exec:safety:host_asn:host-a:AS31898"]["reason"] == "host_asn_challenge"
