from crawler.health import (
    RedisHealthStore,
    RuntimeHealthState,
    build_liveness_payload,
    build_readiness_payload,
    contains_captcha,
    failure_reason_for_status,
    mark_worker_initialized,
    record_consumer_heartbeat,
)


class FakeRedis:
    def __init__(self):
        self.kv = {}
        self.zsets = {}
        self.hashes = {}

    def exists(self, key):
        return key in self.kv

    def setex(self, key, _ttl, value):
        self.kv[key] = value

    def delete(self, key):
        self.kv.pop(key, None)
        self.zsets.pop(key, None)

    def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    def zremrangebyscore(self, key, minimum, maximum):
        zset = self.zsets.setdefault(key, {})
        for member, score in list(zset.items()):
            if minimum <= score <= maximum:
                zset.pop(member, None)

    def expire(self, _key, _ttl):
        return True

    def zcard(self, key):
        return len(self.zsets.get(key, {}))

    def hincrby(self, key, field, amount):
        self.hashes.setdefault(key, {})
        self.hashes[key][field] = self.hashes[key].get(field, 0) + amount

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    def scan_iter(self, match=None):
        prefix = match[:-1] if match and match.endswith("*") else match
        for key in self.kv:
            if not prefix or key.startswith(prefix):
                yield key


def test_failure_threshold_sets_blacklist():
    store = RedisHealthStore(FakeRedis(), failure_threshold=2, cooldown_seconds=60)

    assert store.record_failure("example.com", "10.0.0.2", "HTTP_429", now=1000.0) is False
    assert store.record_failure("example.com", "10.0.0.2", "HTTP_429", now=1001.0) is True
    assert store.is_blacklisted("example.com", "10.0.0.2") is True


def test_record_success_clears_failure_counter():
    redis = FakeRedis()
    store = RedisHealthStore(redis, failure_threshold=2)

    store.record_failure("example.com", "10.0.0.2", "HTTP_503", now=1000.0)
    store.record_success("example.com", "10.0.0.2")

    assert redis.zcard(store.failure_key("example.com", "10.0.0.2")) == 0


def test_immediate_captcha_blacklist():
    store = RedisHealthStore(FakeRedis(), failure_threshold=5)

    assert store.record_failure("example.com", "10.0.0.2", "CAPTCHA_DETECTED", now=1000.0, immediate=True)
    assert store.is_blacklisted("example.com", "10.0.0.2")


def test_contains_captcha_marker():
    assert contains_captcha(b"<html>please verify you are human</html>", "text/html")


def test_failure_reason_for_status():
    assert failure_reason_for_status(429) == "HTTP_429"
    assert failure_reason_for_status(200) is None


def test_liveness_payload_is_ok_when_process_state_is_live():
    status_code, payload = build_liveness_payload(RuntimeHealthState(started_at=1000.0, live=True))

    assert status_code == 200
    assert payload["status"] == "ok"
    assert payload["uptime_seconds"] >= 0


def test_liveness_payload_fails_when_process_state_is_not_live():
    status_code, payload = build_liveness_payload(RuntimeHealthState(started_at=1000.0, live=False))

    assert status_code == 503
    assert payload["status"] == "failed"


def test_readiness_payload_is_ready_after_initialization_and_recent_heartbeat():
    state = RuntimeHealthState(started_at=1000.0)
    mark_worker_initialized(state, now=1010.0)
    record_consumer_heartbeat(state, now=1020.0)

    status_code, payload = build_readiness_payload(state, max_heartbeat_age_seconds=30, now=1025.0)

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["worker_initialized"] is True


def test_readiness_payload_fails_when_worker_not_initialized():
    state = RuntimeHealthState(started_at=1000.0)
    record_consumer_heartbeat(state, now=1020.0)

    status_code, payload = build_readiness_payload(state, max_heartbeat_age_seconds=30, now=1025.0)

    assert status_code == 503
    assert payload["status"] == "not_ready"


def test_readiness_payload_fails_when_heartbeat_is_stale():
    state = RuntimeHealthState(started_at=1000.0)
    mark_worker_initialized(state, now=1010.0)
    record_consumer_heartbeat(state, now=1020.0)

    status_code, payload = build_readiness_payload(state, max_heartbeat_age_seconds=30, now=1060.1)

    assert status_code == 503
    assert payload["status"] == "not_ready"
