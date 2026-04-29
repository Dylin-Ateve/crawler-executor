import pytest

from crawler.queues import FetchCommandError, RedisStreamsFetchConsumer, parse_fetch_command


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
