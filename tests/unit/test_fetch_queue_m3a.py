import asyncio

from crawler.queues import parse_fetch_command
from crawler.fetch_safety_state import EgressCooldownState, HostSlowdownState
from crawler.egress_policy import build_sticky_pool_assignment
from crawler.politeness import HostIpPacerState
from crawler.spiders.fetch_queue import FetchQueueSpider, LocalDelayedBuffer, LocalDelayedFetchCommand


class DictSettings:
    def __init__(self, values):
        self.values = values

    def get(self, name, default=None):
        return self.values.get(name, default)

    def getint(self, name, default=0):
        return int(self.values.get(name, default))

    def getbool(self, name, default=False):
        value = self.values.get(name, default)
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "on"}

    def getlist(self, name, default=None):
        value = self.values.get(name, default or [])
        if isinstance(value, list):
            return value
        return [item.strip() for item in str(value).split(",") if item.strip()]


class DummyConsumer:
    is_shutting_down = False


class FakeSafetyStore:
    def __init__(self):
        self.host_ip_backoffs = {}
        self.ip_cooldowns = {}
        self.host_slowdowns = {}

    def get_host_ip_backoff(self, host_hash, identity_hash):
        return self.host_ip_backoffs.get((host_hash, identity_hash))

    def get_ip_cooldown(self, identity_hash):
        return self.ip_cooldowns.get(identity_hash)

    def get_host_slowdown(self, host_hash):
        return self.host_slowdowns.get(host_hash)


def _command(url="https://example.com/page"):
    return parse_fetch_command(
        {
            "url": url,
            "canonical_url": "https://example.com/page",
            "job_id": "job-1",
        },
        stream_id="1-0",
    )


def _spider(monkeypatch, now_ms=100000, sticky_pool_size=2, patch_time=True):
    if patch_time:
        monkeypatch.setattr("crawler.spiders.fetch_queue.time.time", lambda: now_ms / 1000.0)
    spider = FetchQueueSpider(name="fetch_queue")
    spider.consumer = DummyConsumer()
    spider._configure_m3a(
        DictSettings(
            {
                "EGRESS_SELECTION_STRATEGY": "STICKY_POOL",
                "LOCAL_IP_POOL": ["10.0.0.2", "10.0.0.3", "10.0.0.4"],
                "STICKY_POOL_SIZE": sticky_pool_size,
                "EGRESS_IDENTITY_SOURCE": "auto",
                "ALLOW_BIND_IP_AS_EGRESS_IDENTITY": True,
                "EGRESS_IDENTITY_HASH_SALT": "test",
                "HOST_IP_MIN_DELAY_MS": 2000,
                "HOST_IP_JITTER_MS": 0,
                "LOCAL_DELAYED_BUFFER_CAPACITY": 10,
                "MAX_LOCAL_DELAY_SECONDS": 300,
                "LOCAL_DELAYED_BUFFER_POLL_MS": 1,
            }
        )
    )
    return spider


def test_sticky_pool_build_request_sets_egress_identity_and_download_slot(monkeypatch):
    spider = _spider(monkeypatch)

    request = spider._build_or_delay_request(_command(), "1-0")

    assert request is not None
    assert request.meta["egress_local_ip"] in {"10.0.0.2", "10.0.0.3", "10.0.0.4"}
    assert request.meta["egress_bind_ip"] == request.meta["egress_local_ip"]
    assert request.meta["egress_identity"] == request.meta["egress_local_ip"]
    assert request.meta["egress_identity_type"] == "bind_ip"
    assert request.meta["egress_identity_hash"]
    assert request.meta["download_slot"] == f"example.com@{request.meta['egress_identity']}"


def test_pacer_delays_second_request_for_same_host_identity(monkeypatch):
    spider = _spider(monkeypatch, sticky_pool_size=1)

    first = spider._build_or_delay_request(_command(), "1-0")
    second = spider._build_or_delay_request(_command(), "2-0")

    assert first is not None
    assert second is None
    assert len(spider.delayed_buffer) == 1


def test_sticky_pool_avoids_redis_ip_cooldown(monkeypatch):
    spider = _spider(monkeypatch, sticky_pool_size=3)
    cooled_identity = spider.egress_identities[0]
    store = FakeSafetyStore()
    store.ip_cooldowns[cooled_identity.identity_hash] = EgressCooldownState(
        identity_hash=cooled_identity.identity_hash,
        cooldown_until_ms=120000,
        reason="cross_host_challenge",
        trigger_count=3,
        last_updated_at_ms=100000,
    )
    spider.fetch_safety_store = store

    request = spider._build_or_delay_request(_command(), "1-0")

    assert request is not None
    assert request.meta["egress_identity_hash"] != cooled_identity.identity_hash


def test_all_sticky_pool_candidates_in_cooldown_are_delayed(monkeypatch):
    now_ms = 100000
    spider = _spider(monkeypatch, now_ms=now_ms, sticky_pool_size=3)
    store = FakeSafetyStore()
    for identity in spider.egress_identities:
        store.ip_cooldowns[identity.identity_hash] = EgressCooldownState(
            identity_hash=identity.identity_hash,
            cooldown_until_ms=now_ms + 5000,
            reason="cross_host_challenge",
            trigger_count=3,
            last_updated_at_ms=now_ms,
        )
    spider.fetch_safety_store = store

    request = spider._build_or_delay_request(_command(), "1-0")

    assert request is None
    assert len(spider.delayed_buffer) == 1
    assert spider.delayed_buffer._items[0].delay_reason == "ip_cooldown"
    assert spider.delayed_buffer._items[0].eligible_at_ms == now_ms + 5000


def test_redis_host_ip_backoff_delays_request_when_only_candidate(monkeypatch):
    now_ms = 100000
    spider = _spider(monkeypatch, now_ms=now_ms, sticky_pool_size=1)
    identity = build_sticky_pool_assignment(
        "example.com",
        spider.egress_identities,
        pool_size=1,
        hash_salt="test",
        now_ms=now_ms,
    ).candidate_identities[0]
    host_hash = spider._command_host(_command())
    from crawler.egress_identity import stable_hash

    store = FakeSafetyStore()
    store.host_ip_backoffs[(stable_hash(host_hash, salt="test"), identity.identity_hash)] = HostIpPacerState(
        next_allowed_at_ms=now_ms + 2000,
        min_delay_ms=2000,
        backoff_level=1,
        last_signal="http_429",
        last_updated_at_ms=now_ms,
    )
    spider.fetch_safety_store = store

    request = spider._build_or_delay_request(_command(), "1-0")

    assert request is None
    assert len(spider.delayed_buffer) == 1


def test_redis_host_slowdown_factor_scales_started_pacer(monkeypatch):
    now_ms = 100000
    spider = _spider(monkeypatch, now_ms=now_ms, sticky_pool_size=1)
    from crawler.egress_identity import stable_hash

    host_hash = stable_hash("example.com", salt="test")
    store = FakeSafetyStore()
    store.host_slowdowns[host_hash] = HostSlowdownState(
        host_hash=host_hash,
        slowdown_until_ms=now_ms + 10000,
        slowdown_factor=5.0,
        reason="multi_ip_challenge",
        last_updated_at_ms=now_ms,
    )
    spider.fetch_safety_store = store

    request = spider._build_or_delay_request(_command(), "1-0")
    state = spider._pacer_states[(host_hash, request.meta["egress_identity_hash"])]

    assert request is not None
    assert state.min_delay_ms == 10000


def test_delayed_request_is_scheduled_after_pacer_becomes_eligible(monkeypatch):
    now = {"ms": 100000}
    monkeypatch.setattr("crawler.spiders.fetch_queue.time.time", lambda: now["ms"] / 1000.0)
    spider = _spider(monkeypatch, now_ms=now["ms"], sticky_pool_size=1, patch_time=False)

    first = spider._build_or_delay_request(_command(), "1-0")
    delayed = spider._build_or_delay_request(_command(), "2-0")
    now["ms"] += 2000

    async def collect_due():
        return [request async for request in spider._drain_due_delayed_requests()]

    due = asyncio.run(collect_due())

    assert first is not None
    assert delayed is None
    assert len(due) == 1
    assert due[0].meta["stream_message_id"] == "2-0"


def test_local_delayed_buffer_capacity_and_due_order():
    buffer = LocalDelayedBuffer(capacity=1)
    first = LocalDelayedFetchCommand(_command(), "1-0", 2000, 1000, "host_ip_pacer", "a")
    second = LocalDelayedFetchCommand(_command(), "2-0", 1500, 1000, "host_ip_pacer", "b")

    assert buffer.add(first) is True
    assert buffer.add(second) is False
    assert buffer.is_full is True
    assert buffer.pop_due(1999) == []
    assert buffer.pop_due(2000) == [first]


def test_max_local_delay_exceeded_logs_once_and_keeps_message_in_buffer(monkeypatch, caplog):
    now = {"ms": 100000}
    monkeypatch.setattr("crawler.spiders.fetch_queue.time.time", lambda: now["ms"] / 1000.0)
    spider = _spider(monkeypatch, now_ms=now["ms"])
    spider.max_local_delay_seconds = 1
    spider.delayed_buffer.add(
        LocalDelayedFetchCommand(_command(), "1-0", now["ms"] + 10000, now["ms"] - 2000, "host_ip_pacer", "a")
    )

    with caplog.at_level("WARNING", logger=spider.logger.name):
        spider._log_expired_delayed_commands()
        spider._log_expired_delayed_commands()

    assert len(spider.delayed_buffer) == 1
    assert sum("fetch_queue_max_local_delay_exceeded" in record.message for record in caplog.records) == 1
