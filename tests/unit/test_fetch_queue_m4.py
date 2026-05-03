from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crawler.policy_provider import StaticRuntimePolicyProvider
from crawler.queues import FetchCommandError, parse_fetch_command
from crawler.runtime_policy import policy_document_from_mapping
from crawler.spiders.fetch_queue import FetchQueueSpider


class DummyConsumer:
    is_shutting_down = False
    max_deliveries = 3


def _policy_doc(*, paused=False, max_retries=2):
    return policy_document_from_mapping(
        {
            "schema_version": "1.0",
            "version": "policy-test",
            "generated_at": "2026-05-03T10:00:00Z",
            "default_policy": {
                "enabled": True,
                "paused": paused,
                "pause_reason": "manual_pause" if paused else None,
                "egress_selection_strategy": "STICKY_BY_HOST",
                "download_timeout_seconds": 30,
                "max_retries": max_retries,
            },
            "scope_policies": [
                {
                    "scope_type": "politeness_key",
                    "scope_id": "site:paused",
                    "policy": {"paused": True, "pause_reason": "scope_pause"},
                }
            ],
        }
    )


def _spider(document=None):
    spider = FetchQueueSpider(name="fetch_queue")
    spider.consumer = DummyConsumer()
    spider.default_max_messages = 0
    spider.policy_provider = StaticRuntimePolicyProvider(document or _policy_doc())
    return spider


def _command(**overrides):
    payload = {
        "url": "https://example.com/page",
        "canonical_url": "https://example.com/page",
        "job_id": "job-1",
    }
    payload.update(overrides)
    return parse_fetch_command(payload, stream_id="1-0")


def test_parse_fetch_command_rejects_invalid_deadline_at():
    try:
        _command(deadline_at="not-a-date")
    except FetchCommandError as exc:
        assert "deadline_at must be an ISO-8601 timestamp" in str(exc)
    else:
        raise AssertionError("expected invalid deadline")


def test_parse_fetch_command_rejects_negative_max_retries():
    try:
        _command(max_retries="-1")
    except FetchCommandError as exc:
        assert "max_retries must be >= 0" in str(exc)
    else:
        raise AssertionError("expected invalid max_retries")


def test_pause_policy_builds_terminal_item_without_request():
    spider = _spider()
    command = _command(politeness_key="site:paused")

    item = spider._build_or_delay_request(command, "1-0")

    assert isinstance(item, dict)
    assert item["fetch_failed"] is True
    assert item["error_type"] == "paused"
    assert item["error_message"] == "scope_pause"
    assert item["policy_version"] == "policy-test"
    assert item["matched_policy_scope_type"] == "politeness_key"


def test_expired_deadline_builds_terminal_item_without_request():
    spider = _spider()
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    command = _command(deadline_at=expired)

    item = spider._build_or_delay_request(command, "1-0")

    assert isinstance(item, dict)
    assert item["error_type"] == "deadline_expired"
    assert item["attempt_id"] == command.attempt_id


def test_future_deadline_builds_request_with_policy_retry_budget():
    spider = _spider(_policy_doc(max_retries=1))
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    command = _command(deadline_at=future)

    request = spider._build_or_delay_request(command, "1-0")

    assert request.meta["effective_max_retries"] == 1
    assert request.meta["policy_version"] == "policy-test"
    assert request.meta["download_timeout"] == 30


def test_command_max_retries_overrides_policy():
    spider = _spider(_policy_doc(max_retries=5))
    command = _command(max_retries="0")

    request = spider._build_or_delay_request(command, "1-0")

    assert request.meta["effective_max_retries"] == 0
    assert spider._should_retry_request(request) is False
