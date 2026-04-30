from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

import scrapy
from scrapy import signals as scrapy_signals

from crawler.health import mark_worker_initialized, record_consumer_heartbeat
from crawler.metrics import metrics
from crawler.queues import FetchCommand, RedisStreamsFetchConsumer


RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504, 522, 524}


class FetchQueueSpider(scrapy.Spider):
    name = "fetch_queue"
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "HTTPERROR_ALLOW_ALL": True,
    }

    def __init__(self, max_messages=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_messages = int(max_messages or 0)
        self.seen_messages = 0
        self.paused = False
        self.pause_file = ""
        self.pause_poll_seconds = 5
        self._pause_logged = False
        self._pause_file_error_logged = False
        # ADR-0009 优雅停机相关运行态。
        self.shutdown_drain_seconds = 25
        self._shutdown_started_at = None
        self._shutdown_summary_logged = False

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.consumer = RedisStreamsFetchConsumer.from_settings(crawler.settings)
        spider.default_max_messages = crawler.settings.getint("FETCH_QUEUE_MAX_MESSAGES", 0)
        spider.pause_poll_seconds = crawler.settings.getint("CRAWLER_PAUSE_POLL_SECONDS", 5)
        spider.paused = crawler.settings.getbool("CRAWLER_PAUSED", False)
        spider.pause_file = crawler.settings.get("CRAWLER_PAUSE_FILE", "") or ""
        spider.shutdown_drain_seconds = crawler.settings.getint(
            "FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS", 25
        )
        # ADR-0009：不注册自定义 signal.signal() handler，通过 Scrapy 自身关停信号
        # 触发 consumer.request_shutdown()。spider_closed 与 engine_stopped 的连接
        # 形成 "进入停机标志 → 进入 drain → 退出总结" 的闭环。
        crawler.signals.connect(
            spider._on_spider_closed, signal=scrapy_signals.spider_closed
        )
        crawler.signals.connect(
            spider._on_engine_stopped, signal=scrapy_signals.engine_stopped
        )
        return spider

    def _on_spider_closed(self, spider, reason):
        if spider is not self:
            return
        if self.consumer.is_shutting_down:
            return
        self._shutdown_started_at = time.monotonic()
        self.consumer.request_shutdown()
        metrics.record_fetch_queue_event("shutdown")
        self.logger.info(
            "fetch_queue_shutdown_signal_received reason=%s seen_messages=%s acked_count=%s drain_seconds=%s",
            reason,
            self.seen_messages,
            self.consumer.acked_count,
            self.shutdown_drain_seconds,
        )

    def _on_engine_stopped(self):
        if self._shutdown_summary_logged:
            return
        if not self.consumer.is_shutting_down:
            return
        if self._shutdown_started_at is None:
            elapsed = 0.0
        else:
            elapsed = time.monotonic() - self._shutdown_started_at
        drain_timeout = elapsed > self.shutdown_drain_seconds
        in_flight_estimate = max(self.seen_messages - self.consumer.acked_count, 0)
        self.logger.info(
            "fetch_queue_shutdown_loop_exit elapsed_seconds=%.3f drain_timeout=%s seen_messages=%s acked_count=%s in_flight_estimate=%s",
            elapsed,
            "true" if drain_timeout else "false",
            self.seen_messages,
            self.consumer.acked_count,
            in_flight_estimate,
        )
        self._shutdown_summary_logged = True

    async def start(self):
        self.consumer.ensure_group()
        self._record_consumer_heartbeat()
        mark_worker_initialized()
        max_messages = self.max_messages or self.default_max_messages
        while True:
            self._record_consumer_heartbeat()
            if self.consumer.is_shutting_down:
                return
            if self._is_paused():
                if not self._pause_logged:
                    self.logger.info(
                        "fetch_queue_paused stream=%s group=%s",
                        self.consumer.stream,
                        self.consumer.group,
                    )
                    self._pause_logged = True
                metrics.record_fetch_queue_event("paused")
                await asyncio.sleep(self.pause_poll_seconds)
                continue
            self._pause_logged = False
            if max_messages and self.seen_messages >= max_messages:
                return
            entries = self.consumer.read()
            if not entries:
                if self.consumer.is_shutting_down:
                    return
                metrics.record_fetch_queue_event("empty")
                if max_messages:
                    return
                continue
            for entry in entries:
                self._record_consumer_heartbeat()
                if self.consumer.is_shutting_down:
                    return
                if max_messages and self.seen_messages >= max_messages:
                    return
                if not entry.is_valid:
                    metrics.record_fetch_queue_event("invalid")
                    self.logger.error(
                        "fetch_queue_invalid_message stream=%s message_id=%s error=%s",
                        entry.stream,
                        entry.message_id,
                        entry.error,
                    )
                    self.consumer.ack(entry.message_id)
                    continue
                self.seen_messages += 1
                metrics.record_fetch_queue_event("read")
                yield self._build_request(entry.command, entry.message_id)

    def _build_request(self, command: FetchCommand, message_id: str) -> scrapy.Request:
        attempted_at = datetime.now(timezone.utc)
        meta = command.to_request_meta()
        meta.update(
            {
                "attempted_at_dt": attempted_at,
                "stream_message_id": message_id,
                "fetch_queue_consumer": self.consumer,
                "handle_httpstatus_all": True,
            }
        )
        return scrapy.Request(
            url=command.url,
            callback=self.parse,
            errback=self.errback,
            dont_filter=True,
            meta=meta,
        )

    @staticmethod
    def _record_consumer_heartbeat() -> None:
        timestamp = time.time()
        record_consumer_heartbeat(now=timestamp)
        metrics.set_fetch_queue_consumer_heartbeat(timestamp)

    def _is_paused(self) -> bool:
        if not self.pause_file:
            return self.paused
        try:
            value = Path(self.pause_file).read_text(encoding="utf-8").strip().lower()
        except OSError as exc:
            if not self._pause_file_error_logged:
                self.logger.warning(
                    "fetch_queue_pause_file_read_failed path=%s error=%s",
                    self.pause_file,
                    exc,
                )
                self._pause_file_error_logged = True
            return self.paused
        self._pause_file_error_logged = False
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off", ""}:
            return False
        return self.paused

    def parse(self, response):
        content_type = self._content_type(response)
        if self._should_retry_response(response):
            metrics.record_fetch_queue_event("retryable_failure")
            self.logger.warning(
                "fetch_queue_retryable_response url=%s status=%s attempt_id=%s stream_message_id=%s deliveries=%s",
                response.url,
                response.status,
                response.meta.get("attempt_id"),
                response.meta.get("stream_message_id"),
                response.meta.get("stream_deliveries"),
            )
            return
        if response.status in RETRYABLE_HTTP_STATUS_CODES:
            yield self._terminal_fetch_failed_item(
                response.request,
                error_type="retry_exhausted",
                error_message=f"retry exhausted for HTTP status {response.status}",
                status_code=response.status,
                content_type=content_type,
                response_headers=self._headers(response),
                body=response.body or b"",
            )
            return
        item = {
            "p1_candidate": True,
            "url": response.url,
            "canonical_url": response.meta.get("canonical_url"),
            "url_hash": response.meta.get("url_hash"),
            "status_code": response.status,
            "content_type": content_type,
            "response_headers": self._headers(response),
            "body": response.body or b"",
            "outlinks": response.css("a::attr(href)").getall() if self._is_html(content_type) else [],
            "egress_local_ip": response.meta.get("egress_local_ip"),
            "observed_egress_ip": None,
            "attempt_id": response.meta.get("attempt_id"),
            "attempted_at_dt": response.meta.get("attempted_at_dt"),
            "fetched_at_dt": datetime.now(timezone.utc),
            "command_id": response.meta.get("command_id"),
            "job_id": response.meta.get("job_id"),
            "trace_id": response.meta.get("trace_id"),
            "host_id": response.meta.get("host_id"),
            "site_id": response.meta.get("site_id"),
            "stream_message_id": response.meta.get("stream_message_id"),
            "fetch_queue_consumer": response.meta.get("fetch_queue_consumer"),
        }
        self.logger.info(
            "fetch_queue_response_observed url=%s status=%s content_type=%s stream_message_id=%s",
            response.url,
            response.status,
            content_type,
            response.meta.get("stream_message_id"),
        )
        yield item

    def errback(self, failure):
        request = failure.request
        error_type = failure.type.__name__ if getattr(failure, "type", None) else type(failure.value).__name__
        error_message = str(failure.value)
        if self._should_retry_request(request):
            metrics.record_fetch_queue_event("retryable_failure")
            self.logger.warning(
                "fetch_queue_retryable_failure url=%s attempt_id=%s stream_message_id=%s deliveries=%s error_type=%s error=%s",
                request.url,
                request.meta.get("attempt_id"),
                request.meta.get("stream_message_id"),
                request.meta.get("stream_deliveries"),
                error_type,
                error_message,
            )
            return
        item = self._terminal_fetch_failed_item(
            request,
            error_type="retry_exhausted" if self._delivery_count(request.meta) >= self.consumer.max_deliveries else error_type,
            error_message=error_message,
        )
        self.logger.warning(
            "fetch_queue_fetch_failed url=%s attempt_id=%s stream_message_id=%s error_type=%s error=%s",
            request.url,
            request.meta.get("attempt_id"),
            request.meta.get("stream_message_id"),
            item["error_type"],
            item["error_message"],
        )
        yield item

    def _terminal_fetch_failed_item(
        self,
        request,
        *,
        error_type: str,
        error_message: str,
        status_code=None,
        content_type=None,
        response_headers=None,
        body: bytes = b"",
    ):
        item = {
            "p1_candidate": True,
            "fetch_failed": True,
            "url": request.url,
            "canonical_url": request.meta.get("canonical_url"),
            "url_hash": request.meta.get("url_hash"),
            "status_code": status_code,
            "content_type": content_type,
            "response_headers": response_headers or {},
            "body": body,
            "outlinks": [],
            "error_type": error_type,
            "error_message": error_message,
            "egress_local_ip": request.meta.get("egress_local_ip"),
            "observed_egress_ip": None,
            "attempt_id": request.meta.get("attempt_id"),
            "attempted_at_dt": request.meta.get("attempted_at_dt"),
            "fetched_at_dt": datetime.now(timezone.utc),
            "command_id": request.meta.get("command_id"),
            "job_id": request.meta.get("job_id"),
            "trace_id": request.meta.get("trace_id"),
            "host_id": request.meta.get("host_id"),
            "site_id": request.meta.get("site_id"),
            "stream_message_id": request.meta.get("stream_message_id"),
            "fetch_queue_consumer": request.meta.get("fetch_queue_consumer"),
        }
        return item

    def _should_retry_response(self, response) -> bool:
        return response.status in RETRYABLE_HTTP_STATUS_CODES and self._should_retry_request(response.request)

    def _should_retry_request(self, request) -> bool:
        return self._delivery_count(request.meta) < self.consumer.max_deliveries

    @staticmethod
    def _delivery_count(meta) -> int:
        try:
            return int(meta.get("stream_deliveries") or 1)
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _content_type(response) -> str:
        try:
            value = response.headers.get(b"Content-Type", b"")
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="ignore")
            return str(value)
        except Exception:
            return ""

    @staticmethod
    def _headers(response):
        headers = {}
        for key, values in response.headers.items():
            name = key.decode("utf-8", errors="ignore") if isinstance(key, bytes) else str(key)
            value = values[-1] if isinstance(values, list) else values
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="ignore")
            headers[name] = str(value)
        return headers

    @staticmethod
    def _is_html(content_type: str) -> bool:
        return (content_type or "").split(";", 1)[0].strip().lower() in {"text/html", "application/xhtml+xml"}
