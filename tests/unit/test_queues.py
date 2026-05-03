import pytest

from crawler.queues import (
    FetchCommandError,
    RedisStreamsFetchConsumer,
    parse_fetch_command,
    resolve_fetch_queue_consumer,
    resolve_fetch_queue_group,
    resolve_fetch_queue_stream,
)


def test_parse_fetch_command_requires_url_job_and_canonical_url():
    with pytest.raises(FetchCommandError, match="job_id is required"):
        parse_fetch_command({"url": "https://example.com", "canonical_url": "https://example.com"})


def test_parse_fetch_command_builds_attempt_id_from_job_and_canonical_url():
    command = parse_fetch_command(
        {
            "url": "https://example.com/?b=2&a=1",
            "canonical_url": "https://example.com?a=1&b=2",
            "job_id": "job-1",
            "host_id": "",
            "site_id": "",
            "max_retries": "2",
        },
        stream_id="1-0",
    )

    assert command.job_id == "job-1"
    assert command.canonical_url == "https://example.com?a=1&b=2"
    assert command.host_id is None
    assert command.site_id is None
    assert command.max_retries == 2
    assert command.stream_id == "1-0"
    assert command.attempt_id == parse_fetch_command(
        {"url": "https://example.com/?a=1&b=2", "canonical_url": "https://example.com?a=1&b=2", "job_id": "job-1"}
    ).attempt_id


def test_fetch_command_maps_context_to_request_meta():
    command = parse_fetch_command(
        {
            "url": "https://example.com/",
            "canonical_url": "https://example.com",
            "job_id": "job-1",
            "command_id": "cmd-1",
            "trace_id": "trace-1",
            "host_id": "host-1",
            "site_id": "site-1",
            "tier": "hot",
            "politeness_key": "example.com",
            "policy_scope_id": "scope-1",
        },
        stream_id="1-0",
        deliveries=2,
    )

    meta = command.to_request_meta()

    assert meta["command_id"] == "cmd-1"
    assert meta["job_id"] == "job-1"
    assert meta["trace_id"] == "trace-1"
    assert meta["host_id"] == "host-1"
    assert meta["site_id"] == "site-1"
    assert meta["tier"] == "hot"
    assert meta["politeness_key"] == "example.com"
    assert meta["policy_scope_id"] == "scope-1"
    assert meta["attempt_id"] == command.attempt_id
    assert meta["canonical_url"] == "https://example.com"
    assert meta["url_hash"] == command.url_hash
    assert meta["stream_id"] == "1-0"
    assert meta["stream_deliveries"] == 2


def test_parse_fetch_command_accepts_json_payload_field():
    command = parse_fetch_command(
        {
            b"payload": b'{"url":"https://example.com","canonical_url":"https://example.com","job_id":"job-1"}'
        }
    )

    assert command.url == "https://example.com"


class DictSettings:
    def __init__(self, values):
        self.values = values

    def get(self, name, default=None):
        return self.values.get(name, default)


def test_resolve_fetch_queue_consumer_prefers_explicit_value():
    settings = DictSettings(
        {
            "FETCH_QUEUE_CONSUMER": "manual-worker",
            "FETCH_QUEUE_CONSUMER_TEMPLATE": "${NODE_NAME}-${POD_NAME}",
            "NODE_NAME": "node-a",
            "POD_NAME": "pod-a",
        }
    )

    assert resolve_fetch_queue_consumer(settings) == "manual-worker"


def test_resolve_fetch_queue_consumer_renders_node_pod_template():
    settings = DictSettings(
        {
            "FETCH_QUEUE_CONSUMER_TEMPLATE": "${NODE_NAME}-${POD_NAME}",
            "NODE_NAME": "node-a",
            "POD_NAME": "pod-a",
        }
    )

    assert resolve_fetch_queue_consumer(settings) == "node-a-pod-a"


def test_resolve_fetch_queue_consumer_defaults_to_node_pod_when_template_missing():
    settings = DictSettings({"NODE_NAME": "node-a", "POD_NAME": "pod-a"})

    assert resolve_fetch_queue_consumer(settings) == "node-a-pod-a"


def test_resolve_fetch_queue_consumer_falls_back_to_hostname():
    settings = DictSettings({})

    assert resolve_fetch_queue_consumer(settings, hostname_factory=lambda: "host-a") == "host-a"


def test_resolve_fetch_queue_debug_stream_group_and_consumer():
    settings = DictSettings(
        {
            "CRAWLER_DEBUG_MODE": "true",
            "DEBUG_FETCH_QUEUE_STREAM_TEMPLATE": "crawl:tasks:debug:{node_name}",
            "DEBUG_FETCH_QUEUE_GROUP_TEMPLATE": "crawler-executor-debug:{node_name}",
            "DEBUG_FETCH_QUEUE_CONSUMER_TEMPLATE": "${NODE_NAME}-${POD_NAME}-debug",
            "NODE_NAME": "node-a",
            "POD_NAME": "pod-a",
        }
    )

    assert resolve_fetch_queue_stream(settings) == "crawl:tasks:debug:node-a"
    assert resolve_fetch_queue_group(settings) == "crawler-executor-debug:node-a"
    assert resolve_fetch_queue_consumer(settings) == "node-a-pod-a-debug"


class FakeStreamRedis:
    def __init__(self):
        self.acked = []
        self.claim_response = []

    def xreadgroup(self, *_args, **_kwargs):
        return [
            (
                b"crawl:tasks",
                [
                    (
                        b"1-0",
                        {
                            b"url": b"https://example.com",
                            b"canonical_url": b"https://example.com",
                            b"job_id": b"job-1",
                        },
                    ),
                    (b"2-0", {b"url": b"https://example.com"}),
                ],
            )
        ]

    def xack(self, stream, group, message_id):
        self.acked.append((stream, group, message_id))

    def xautoclaim(self, *_args, **_kwargs):
        return self.claim_response

    def xpending_range(self, *_args, **_kwargs):
        return [{"times_delivered": 3}]


def test_stream_consumer_returns_valid_and_invalid_entries():
    redis = FakeStreamRedis()
    consumer = RedisStreamsFetchConsumer(redis, stream="crawl:tasks", group="group", consumer="worker")

    entries = consumer.read()

    assert entries[0].is_valid is True
    assert entries[0].command.job_id == "job-1"
    assert entries[1].is_valid is False
    assert "job_id is required" in entries[1].error


def test_stream_consumer_ack_uses_stream_and_group():
    redis = FakeStreamRedis()
    consumer = RedisStreamsFetchConsumer(redis, stream="crawl:tasks", group="group", consumer="worker")

    consumer.ack("1-0")

    assert redis.acked == [("crawl:tasks", "group", "1-0")]


def test_stream_consumer_reads_reclaimed_pending_before_new_messages():
    redis = FakeStreamRedis()
    redis.claim_response = (
        b"0-0",
        [
            (
                b"3-0",
                {
                    b"url": b"https://example.com",
                    b"canonical_url": b"https://example.com",
                    b"job_id": b"job-1",
                },
            )
        ],
    )
    consumer = RedisStreamsFetchConsumer(redis, stream="crawl:tasks", group="group", consumer="worker", max_deliveries=3)

    entries = consumer.read()

    assert len(entries) == 1
    assert entries[0].message_id == "3-0"
    assert entries[0].command.deliveries == 3


def test_stream_consumer_records_redis_dependency_health(monkeypatch):
    redis = FakeStreamRedis()
    observed = []
    monkeypatch.setattr("crawler.queues.metrics.record_dependency_health", lambda dependency, healthy: observed.append((dependency, healthy)))
    consumer = RedisStreamsFetchConsumer(redis, stream="crawl:tasks", group="group", consumer="worker")

    consumer.read()
    consumer.ack("1-0")

    assert ("redis", True) in observed


class RecordingStreamRedis:
    """记录 xreadgroup / xautoclaim / xack 的调用次数，用于停机语义测试。"""

    def __init__(self):
        self.xreadgroup_calls = 0
        self.xautoclaim_calls = 0
        self.acked = []

    def xreadgroup(self, *_args, **_kwargs):
        self.xreadgroup_calls += 1
        return [
            (
                b"crawl:tasks",
                [
                    (
                        b"1-0",
                        {
                            b"url": b"https://example.com",
                            b"canonical_url": b"https://example.com",
                            b"job_id": b"job-1",
                        },
                    )
                ],
            )
        ]

    def xautoclaim(self, *_args, **_kwargs):
        self.xautoclaim_calls += 1
        return (b"0-0", [])

    def xack(self, stream, group, message_id):
        self.acked.append((stream, group, message_id))

    def xpending_range(self, *_args, **_kwargs):
        return [{"times_delivered": 1}]


def test_request_shutdown_sets_flag():
    consumer = RedisStreamsFetchConsumer(
        RecordingStreamRedis(), stream="crawl:tasks", group="group", consumer="worker"
    )

    assert consumer.is_shutting_down is False
    consumer.request_shutdown()
    assert consumer.is_shutting_down is True


def test_read_returns_empty_after_shutdown_without_calling_redis():
    redis = RecordingStreamRedis()
    consumer = RedisStreamsFetchConsumer(
        redis, stream="crawl:tasks", group="group", consumer="worker"
    )
    consumer.request_shutdown()

    entries = consumer.read()

    assert entries == []
    assert redis.xreadgroup_calls == 0
    assert redis.xautoclaim_calls == 0


def test_reclaim_pending_returns_empty_after_shutdown_without_calling_redis():
    redis = RecordingStreamRedis()
    consumer = RedisStreamsFetchConsumer(
        redis, stream="crawl:tasks", group="group", consumer="worker"
    )
    consumer.request_shutdown()

    assert consumer.reclaim_pending() == []
    assert redis.xautoclaim_calls == 0


def test_ack_increments_acked_count():
    redis = RecordingStreamRedis()
    consumer = RedisStreamsFetchConsumer(
        redis, stream="crawl:tasks", group="group", consumer="worker"
    )

    assert consumer.acked_count == 0
    consumer.ack("1-0")
    consumer.ack("2-0")

    assert consumer.acked_count == 2
    assert redis.acked == [
        ("crawl:tasks", "group", "1-0"),
        ("crawl:tasks", "group", "2-0"),
    ]


def test_read_skips_xreadgroup_when_shutdown_after_reclaim():
    """覆盖 reclaim_pending() 期间进入停机态的边界场景。"""

    class ShutdownDuringReclaimRedis(RecordingStreamRedis):
        def __init__(self, consumer_ref):
            super().__init__()
            self.consumer_ref = consumer_ref

        def xautoclaim(self, *args, **kwargs):
            self.xautoclaim_calls += 1
            self.consumer_ref["consumer"].request_shutdown()
            return (b"0-0", [])

    consumer_ref = {}
    redis = ShutdownDuringReclaimRedis(consumer_ref)
    consumer = RedisStreamsFetchConsumer(
        redis, stream="crawl:tasks", group="group", consumer="worker"
    )
    consumer_ref["consumer"] = consumer

    entries = consumer.read()

    assert entries == []
    # reclaim 触发停机后，read() 不应再调用 xreadgroup
    assert redis.xautoclaim_calls == 1
    assert redis.xreadgroup_calls == 0
