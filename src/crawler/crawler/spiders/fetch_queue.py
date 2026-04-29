from __future__ import annotations

from datetime import datetime, timezone

import scrapy

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

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.consumer = RedisStreamsFetchConsumer.from_settings(crawler.settings)
        spider.default_max_messages = crawler.settings.getint("FETCH_QUEUE_MAX_MESSAGES", 0)
        return spider

    async def start(self):
        self.consumer.ensure_group()
        max_messages = self.max_messages or self.default_max_messages
        while True:
            if max_messages and self.seen_messages >= max_messages:
                return
            entries = self.consumer.read()
            if not entries:
                metrics.record_fetch_queue_event("empty")
                if max_messages:
                    return
                continue
            for entry in entries:
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
