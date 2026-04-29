from __future__ import annotations

from typing import Optional


class _NoopMetric:
    def labels(self, **_labels):
        return self

    def inc(self, _amount: int = 1) -> None:
        return None

    def observe(self, _value: float) -> None:
        return None

    def set(self, _value: float) -> None:
        return None


class CrawlerMetrics:
    def __init__(self) -> None:
        try:
            from prometheus_client import Counter, Gauge, Histogram
        except ImportError:
            self.requests_total = _NoopMetric()
            self.response_duration_seconds = _NoopMetric()
            self.active_ip_count = _NoopMetric()
            self.blacklist_count = _NoopMetric()
            self.storage_uploads_total = _NoopMetric()
            self.kafka_publishes_total = _NoopMetric()
            self.content_skips_total = _NoopMetric()
            self.fetch_queue_events_total = _NoopMetric()
            return

        self.requests_total = Counter(
            "crawler_requests_total",
            "Total crawler requests by host, status and egress IP.",
            ["host", "status", "egress_ip"],
        )
        self.response_duration_seconds = Histogram(
            "crawler_response_duration_seconds",
            "Crawler response duration in seconds.",
            ["host", "egress_ip"],
        )
        self.active_ip_count = Gauge("crawler_ip_active_count", "Active local egress IP count.")
        self.blacklist_count = Gauge("crawler_ip_blacklist_count", "Current blacklisted host/IP pair count.")
        self.storage_uploads_total = Counter(
            "crawler_storage_uploads_total",
            "Total object storage upload attempts by provider, bucket and result.",
            ["provider", "bucket", "result"],
        )
        self.kafka_publishes_total = Counter(
            "crawler_kafka_publishes_total",
            "Total Kafka publish attempts by topic and result.",
            ["topic", "result"],
        )
        self.content_skips_total = Counter(
            "crawler_content_skips_total",
            "Total content persistence skips by reason.",
            ["reason"],
        )
        self.fetch_queue_events_total = Counter(
            "crawler_fetch_queue_events_total",
            "Total fetch queue events by result.",
            ["result"],
        )

    def record_response(self, host: str, status: str, egress_ip: str, duration_seconds: Optional[float]) -> None:
        self.requests_total.labels(host=host, status=status, egress_ip=egress_ip or "unknown").inc()
        if duration_seconds is not None:
            self.response_duration_seconds.labels(host=host, egress_ip=egress_ip or "unknown").observe(duration_seconds)

    def set_active_ip_count(self, count: int) -> None:
        self.active_ip_count.set(count)

    def set_blacklist_count(self, count: int) -> None:
        self.blacklist_count.set(count)

    def record_storage_upload(self, provider: str, bucket: str, result: str) -> None:
        self.storage_uploads_total.labels(provider=provider, bucket=bucket, result=result).inc()

    def record_kafka_publish(self, topic: str, result: str) -> None:
        self.kafka_publishes_total.labels(topic=topic, result=result).inc()

    def record_content_skip(self, reason: str) -> None:
        self.content_skips_total.labels(reason=reason).inc()

    def record_fetch_queue_event(self, result: str) -> None:
        self.fetch_queue_events_total.labels(result=result).inc()


metrics = CrawlerMetrics()


class PrometheusMetricsExtension:
    def __init__(self, port: int = 9410) -> None:
        self.port = port
        self.started = False

    @classmethod
    def from_crawler(cls, crawler):
        port = crawler.settings.getint("PROMETHEUS_PORT", 9410)
        extension = cls(port=port)
        try:
            from scrapy import signals
            crawler.signals.connect(extension.spider_opened, signal=signals.spider_opened)
        except Exception:
            pass
        return extension

    def spider_opened(self, spider) -> None:
        if self.started:
            return
        try:
            from prometheus_client import start_http_server
            start_http_server(self.port)
            self.started = True
            spider.logger.info("Prometheus metrics endpoint started on port %s", self.port)
        except Exception as exc:
            spider.logger.warning("failed to start Prometheus metrics endpoint: %s", exc)
