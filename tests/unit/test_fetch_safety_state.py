import pytest

from crawler.fetch_safety_state import (
    ExecutionStateKeyBuilder,
    FetchSafetyStateError,
    FetchSafetyStateStore,
    audit_redis_key_diff,
)
from crawler.politeness import HostIpPacerState


class FakeRedis:
    def __init__(self, fail=False):
        self.fail = fail
        self.hashes = {}
        self.ttls = {}

    def hset(self, key, mapping):
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.hashes.setdefault(key, {}).update({field: str(value) for field, value in mapping.items()})

    def hgetall(self, key):
        if self.fail:
            raise RuntimeError("redis unavailable")
        return self.hashes.get(key, {})

    def hincrby(self, key, field, amount):
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.hashes.setdefault(key, {})
        self.hashes[key][field] = str(int(self.hashes[key].get(field, 0)) + amount)
        return int(self.hashes[key][field])

    def expire(self, key, ttl):
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.ttls[key] = ttl
        return True


def test_host_ip_backoff_round_trip_sets_ttl_and_caps_to_max():
    redis = FakeRedis()
    store = FetchSafetyStateStore(
        redis,
        key_builder=ExecutionStateKeyBuilder("crawler:exec:safety"),
        max_ttl_seconds=60,
    )
    state = HostIpPacerState(
        next_allowed_at_ms=2000,
        min_delay_ms=1000,
        backoff_level=2,
        last_signal="http_429",
        last_updated_at_ms=1000,
    )

    result = store.set_host_ip_backoff("hosthash", "identityhash", state, ttl_seconds=3600)
    loaded = store.get_host_ip_backoff("hosthash", "identityhash")

    assert result.ok is True
    assert redis.ttls["crawler:exec:safety:host_ip:hosthash:identityhash"] == 60
    assert loaded == state


def test_ip_cooldown_and_host_slowdown_round_trip():
    redis = FakeRedis()
    store = FetchSafetyStateStore(redis)

    store.set_ip_cooldown(
        "identityhash",
        cooldown_until_ms=5000,
        reason="cross_host_challenge",
        trigger_count=3,
        now_ms=1000,
        ttl_seconds=1800,
    )
    store.set_host_slowdown(
        "hosthash",
        slowdown_until_ms=7000,
        slowdown_factor=3.0,
        reason="multi_ip_challenge",
        now_ms=1000,
        ttl_seconds=900,
    )

    cooldown = store.get_ip_cooldown("identityhash")
    slowdown = store.get_host_slowdown("hosthash")

    assert cooldown.cooldown_until_ms == 5000
    assert cooldown.reason == "cross_host_challenge"
    assert cooldown.trigger_count == 3
    assert slowdown.slowdown_until_ms == 7000
    assert slowdown.slowdown_factor == 3.0
    assert slowdown.reason == "multi_ip_challenge"


def test_signal_window_counter_accumulates_count_and_weight_with_ttl():
    redis = FakeRedis()
    store = FetchSafetyStateStore(redis)

    first = store.increment_signal_window(
        dimension="ip",
        dimension_hash="identityhash",
        signal_type="captcha_challenge",
        weight=5,
        window_seconds=300,
    )
    second = store.increment_signal_window(
        dimension="ip",
        dimension_hash="identityhash",
        signal_type="captcha_challenge",
        weight=5,
        window_seconds=300,
    )

    assert first.count == 1
    assert first.weight_sum == 5
    assert second.count == 2
    assert second.weight_sum == 10
    assert redis.ttls[first.key] == 300


def test_distinct_signal_window_counts_unique_members_only():
    redis = FakeRedis()
    store = FetchSafetyStateStore(redis)

    first = store.increment_distinct_signal_window(
        dimension="ip",
        dimension_hash="identityhash",
        signal_type="captcha_challenge",
        member_hash="host-a",
        weight=5,
        window_seconds=300,
    )
    duplicate = store.increment_distinct_signal_window(
        dimension="ip",
        dimension_hash="identityhash",
        signal_type="captcha_challenge",
        member_hash="host-a",
        weight=5,
        window_seconds=300,
    )
    second = store.increment_distinct_signal_window(
        dimension="ip",
        dimension_hash="identityhash",
        signal_type="captcha_challenge",
        member_hash="host-b",
        weight=5,
        window_seconds=300,
    )

    assert first.count == 1
    assert duplicate.count == 1
    assert duplicate.weight_sum == 10
    assert second.count == 2


def test_write_disabled_does_not_mutate_redis():
    redis = FakeRedis()
    store = FetchSafetyStateStore(redis, write_enabled=False)

    result = store.set_host_ip_backoff(
        "hosthash",
        "identityhash",
        HostIpPacerState(next_allowed_at_ms=1000),
        ttl_seconds=300,
    )

    assert result.ok is False
    assert result.status == "disabled"
    assert redis.hashes == {}


def test_fail_open_write_failure_returns_result_and_read_failure_returns_none():
    store = FetchSafetyStateStore(FakeRedis(fail=True), fail_open=True)

    result = store.set_host_ip_backoff(
        "hosthash",
        "identityhash",
        HostIpPacerState(next_allowed_at_ms=1000),
        ttl_seconds=300,
    )

    assert result.ok is False
    assert result.status == "failed_open"
    assert store.get_host_ip_backoff("hosthash", "identityhash") is None


def test_fail_closed_write_failure_raises():
    store = FetchSafetyStateStore(FakeRedis(fail=True), fail_open=False)

    with pytest.raises(FetchSafetyStateError):
        store.set_host_ip_backoff(
            "hosthash",
            "identityhash",
            HostIpPacerState(next_allowed_at_ms=1000),
            ttl_seconds=300,
        )


def test_key_builder_rejects_forbidden_or_unsafe_key_parts():
    builder = ExecutionStateKeyBuilder("crawler:exec:safety")

    assert builder.host_ip("hosthash", "identityhash") == "crawler:exec:safety:host_ip:hosthash:identityhash"
    with pytest.raises(FetchSafetyStateError):
        builder.host("priority-host")
    with pytest.raises(FetchSafetyStateError):
        builder.host("host:hash")


def test_redis_boundary_audit_detects_out_of_prefix_forbidden_and_missing_ttl():
    result = audit_redis_key_diff(
        before_keys={"crawl:tasks"},
        after_keys={
            "crawl:tasks",
            "crawler:exec:safety:host_ip:hosthash:identityhash",
            "crawler:exec:safety:host:missingttl",
            "crawler:exec:safety:priority:bad",
            "crawler:scheduler:queue",
        },
        prefix="crawler:exec:safety",
        ttl_by_key={
            "crawler:exec:safety:host_ip:hosthash:identityhash": 300,
            "crawler:exec:safety:host:missingttl": -1,
            "crawler:exec:safety:priority:bad": 300,
            "crawler:scheduler:queue": 300,
        },
    )

    assert result.passed is False
    assert "crawler:scheduler:queue" in result.out_of_prefix_keys
    assert "crawler:exec:safety:priority:bad" in result.forbidden_keys
    assert "crawler:exec:safety:host:missingttl" in result.missing_ttl_keys


def test_redis_boundary_audit_allows_explicit_extra_prefixes():
    result = audit_redis_key_diff(
        before_keys=set(),
        after_keys={"crawl:tasks"},
        prefix="crawler:exec:safety",
        allowed_extra_prefixes=("crawl:tasks",),
    )

    assert result.passed is True
