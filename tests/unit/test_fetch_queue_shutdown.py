"""单元测试：T015c / FR-022 / ADR-0009 优雅停机语义。

覆盖：
- spider_closed 信号 handler 触发 consumer.request_shutdown() 与 shutdown 指标。
- engine_stopped 信号 handler 输出退出总结日志（acked、in-flight 估算、drain 是否超时）。
- 重复触发 spider_closed 不重复进入停机入口。
- max_messages 自然完成路径下，engine_stopped 不重复打印总结。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from crawler.queues import RedisStreamsFetchConsumer
from crawler.spiders.fetch_queue import FetchQueueSpider


class _NullRedis:
    """用于构造 consumer，不会被实际调用 xreadgroup / xautoclaim。"""

    def xgroup_create(self, *_args, **_kwargs):
        # 模拟 group 已存在场景，consumer.ensure_group() 静默吞掉。
        raise Exception("BUSYGROUP Consumer Group name already exists")

    def xreadgroup(self, *_args, **_kwargs):
        raise AssertionError(
            "xreadgroup must not be called when consumer is shutting down"
        )

    def xautoclaim(self, *_args, **_kwargs):
        raise AssertionError(
            "xautoclaim must not be called when consumer is shutting down"
        )


def _build_spider(*, drain_seconds: int = 25) -> FetchQueueSpider:
    spider = FetchQueueSpider(name="fetch_queue")
    spider.consumer = RedisStreamsFetchConsumer(
        _NullRedis(),
        stream="crawl:tasks:test",
        group="group-test",
        consumer="worker-test",
    )
    spider.shutdown_drain_seconds = drain_seconds
    # 通常由 from_crawler 注入；这里直接构造 spider，需要补齐。
    spider.default_max_messages = 0
    return spider


def test_on_spider_closed_triggers_consumer_shutdown_and_metric(monkeypatch):
    spider = _build_spider()

    captured = []

    def fake_record(name: str) -> None:
        captured.append(name)

    monkeypatch.setattr(
        "crawler.spiders.fetch_queue.metrics.record_fetch_queue_event", fake_record
    )

    assert spider.consumer.is_shutting_down is False
    spider._on_spider_closed(spider, reason="shutdown")

    assert spider.consumer.is_shutting_down is True
    assert spider._shutdown_started_at is not None
    assert captured == ["shutdown"]


def test_on_spider_closed_ignores_other_spiders():
    spider_a = _build_spider()
    spider_b = _build_spider()

    spider_a._on_spider_closed(spider_b, reason="shutdown")

    assert spider_a.consumer.is_shutting_down is False
    assert spider_a._shutdown_started_at is None


def test_on_spider_closed_is_idempotent(monkeypatch):
    spider = _build_spider()

    captured = []
    monkeypatch.setattr(
        "crawler.spiders.fetch_queue.metrics.record_fetch_queue_event",
        lambda name: captured.append(name),
    )

    spider._on_spider_closed(spider, reason="shutdown")
    started_first = spider._shutdown_started_at
    spider._on_spider_closed(spider, reason="shutdown")

    assert spider.consumer.is_shutting_down is True
    assert spider._shutdown_started_at == started_first
    assert captured == ["shutdown"]


def test_on_engine_stopped_logs_summary_when_in_shutdown(caplog):
    spider = _build_spider(drain_seconds=25)
    spider.seen_messages = 5
    spider.consumer.acked_count = 3
    spider._on_spider_closed(spider, reason="shutdown")

    with caplog.at_level("INFO", logger=spider.logger.name):
        spider._on_engine_stopped()

    summary_logs = [
        record.message
        for record in caplog.records
        if "fetch_queue_shutdown_loop_exit" in record.message
    ]
    assert len(summary_logs) == 1
    summary = summary_logs[0]
    assert "seen_messages=5" in summary
    assert "acked_count=3" in summary
    assert "in_flight_estimate=2" in summary
    assert "drain_timeout=false" in summary


def test_on_engine_stopped_marks_drain_timeout(caplog):
    spider = _build_spider(drain_seconds=0)
    spider.consumer.request_shutdown()
    # 模拟 1 秒前进入停机态，drain_seconds=0 → 必然超时
    spider._shutdown_started_at = time.monotonic() - 1.0

    with caplog.at_level("INFO", logger=spider.logger.name):
        spider._on_engine_stopped()

    summary_logs = [
        record.message
        for record in caplog.records
        if "fetch_queue_shutdown_loop_exit" in record.message
    ]
    assert len(summary_logs) == 1
    assert "drain_timeout=true" in summary_logs[0]


def test_on_engine_stopped_skips_when_not_in_shutdown(caplog):
    spider = _build_spider()

    with caplog.at_level("INFO", logger=spider.logger.name):
        spider._on_engine_stopped()

    summary_logs = [
        record.message
        for record in caplog.records
        if "fetch_queue_shutdown_loop_exit" in record.message
    ]
    assert summary_logs == []


def test_on_engine_stopped_logs_only_once(caplog):
    spider = _build_spider()
    spider._on_spider_closed(spider, reason="shutdown")

    with caplog.at_level("INFO", logger=spider.logger.name):
        spider._on_engine_stopped()
        spider._on_engine_stopped()

    summary_logs = [
        record.message
        for record in caplog.records
        if "fetch_queue_shutdown_loop_exit" in record.message
    ]
    assert len(summary_logs) == 1


def test_start_loop_exits_when_consumer_in_shutdown_at_entry():
    spider = _build_spider()
    spider.consumer.request_shutdown()

    async def collect():
        items = []
        async for request in spider.start():
            items.append(request)
        return items

    requests = asyncio.run(collect())
    assert requests == []


def test_start_loop_offloads_blocking_redis_calls(monkeypatch):
    spider = _build_spider()
    calls = []

    def fake_ensure_group():
        calls.append("ensure_group")

    def fake_read():
        calls.append("read")
        return []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append(f"to_thread:{func.__name__}")
        return func(*args, **kwargs)

    spider.consumer.ensure_group = fake_ensure_group
    spider.consumer.read = fake_read
    spider.max_messages = 1

    monkeypatch.setattr("crawler.spiders.fetch_queue.asyncio.to_thread", fake_to_thread)

    async def collect():
        return [request async for request in spider.start()]

    requests = asyncio.run(collect())

    assert requests == []
    assert calls == ["to_thread:fake_ensure_group", "ensure_group", "to_thread:fake_read", "read"]


def test_pause_file_overrides_env_pause_flag(tmp_path):
    spider = _build_spider()
    pause_file = tmp_path / "crawler_paused"
    spider.pause_file = str(pause_file)
    spider.paused = False

    pause_file.write_text("true\n", encoding="utf-8")
    assert spider._is_paused() is True

    pause_file.write_text("false\n", encoding="utf-8")
    assert spider._is_paused() is False


def test_pause_file_read_failure_falls_back_to_env_flag(tmp_path, caplog):
    spider = _build_spider()
    spider.pause_file = str(tmp_path / "missing")
    spider.paused = True

    with caplog.at_level("WARNING", logger=spider.logger.name):
        assert spider._is_paused() is True

    assert any("fetch_queue_pause_file_read_failed" in record.message for record in caplog.records)
