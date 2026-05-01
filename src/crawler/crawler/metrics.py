from __future__ import annotations

from typing import Optional


M3A_METRIC_LABELS = {
    "strategy",
    "egress_identity_type",
    "host_hash",
    "egress_identity_hash",
    "consumer",
    "reason",
    "signal_type",
    "dimension",
    "state_type",
    "result",
    "asn",
    "pattern",
}


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
            self.fetch_queue_consumer_heartbeat_timestamp = _NoopMetric()
            self.dependency_health_status = _NoopMetric()
            self.dependency_health_events_total = _NoopMetric()
            self.egress_identity_selected_total = _NoopMetric()
            self.sticky_pool_assignments_total = _NoopMetric()
            self.sticky_pool_size = _NoopMetric()
            self.egress_identity_unavailable_total = _NoopMetric()
            self.pacer_delay_seconds = _NoopMetric()
            self.delayed_buffer_size = _NoopMetric()
            self.delayed_buffer_oldest_age_seconds = _NoopMetric()
            self.delayed_buffer_full_total = _NoopMetric()
            self.delayed_message_expired_total = _NoopMetric()
            self.xreadgroup_suppressed_total = _NoopMetric()
            self.feedback_signal_total = _NoopMetric()
            self.host_ip_backoff_active = _NoopMetric()
            self.host_ip_backoff_seconds = _NoopMetric()
            self.ip_cooldown_active = _NoopMetric()
            self.ip_cooldown_total = _NoopMetric()
            self.host_slowdown_active = _NoopMetric()
            self.host_slowdown_total = _NoopMetric()
            self.host_asn_soft_limit_total = _NoopMetric()
            self.execution_state_writes_total = _NoopMetric()
            self.execution_state_reads_total = _NoopMetric()
            self.execution_state_ttl_seconds = _NoopMetric()
            self.execution_state_forbidden_key_detected_total = _NoopMetric()
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
        self.fetch_queue_consumer_heartbeat_timestamp = Gauge(
            "crawler_fetch_queue_consumer_heartbeat_timestamp_seconds",
            "Unix timestamp for the latest fetch queue consumer loop heartbeat.",
        )
        self.dependency_health_status = Gauge(
            "crawler_dependency_health_status",
            "Latest dependency health status, 1 for healthy and 0 for unhealthy.",
            ["dependency"],
        )
        self.dependency_health_events_total = Counter(
            "crawler_dependency_health_events_total",
            "Total dependency health observations by dependency and result.",
            ["dependency", "result"],
        )
        self.egress_identity_selected_total = Counter(
            "crawler_egress_identity_selected_total",
            "Total selected egress identities.",
            ["strategy", "egress_identity_type"],
        )
        self.sticky_pool_assignments_total = Counter(
            "crawler_sticky_pool_assignments_total",
            "Total sticky-pool assignments.",
            ["strategy"],
        )
        self.sticky_pool_size = Histogram(
            "crawler_sticky_pool_size",
            "Sticky-pool candidate count per assignment.",
            ["strategy"],
        )
        self.egress_identity_unavailable_total = Counter(
            "crawler_egress_identity_unavailable_total",
            "Total unavailable egress identity observations.",
            ["reason"],
        )
        self.pacer_delay_seconds = Histogram(
            "crawler_pacer_delay_seconds",
            "Pacer delay seconds before a Fetch Command becomes eligible.",
            ["reason"],
        )
        self.delayed_buffer_size = Gauge(
            "crawler_delayed_buffer_size",
            "Current local delayed Fetch Command buffer size.",
            ["consumer"],
        )
        self.delayed_buffer_oldest_age_seconds = Gauge(
            "crawler_delayed_buffer_oldest_age_seconds",
            "Age of the oldest local delayed Fetch Command.",
            ["consumer"],
        )
        self.delayed_buffer_full_total = Counter(
            "crawler_delayed_buffer_full_total",
            "Total delayed buffer full events.",
            ["consumer"],
        )
        self.delayed_message_expired_total = Counter(
            "crawler_delayed_message_expired_total",
            "Total delayed messages that exceeded the local delay budget.",
            ["reason"],
        )
        self.xreadgroup_suppressed_total = Counter(
            "crawler_xreadgroup_suppressed_total",
            "Total XREADGROUP suppressions by reason.",
            ["reason"],
        )
        self.feedback_signal_total = Counter(
            "crawler_feedback_signal_total",
            "Total normalized feedback signals.",
            ["signal_type", "dimension"],
        )
        self.host_ip_backoff_active = Gauge(
            "crawler_host_ip_backoff_active",
            "Observed active host and egress identity backoff states.",
            ["reason"],
        )
        self.host_ip_backoff_seconds = Histogram(
            "crawler_host_ip_backoff_seconds",
            "Host and egress identity backoff seconds.",
            ["reason"],
        )
        self.ip_cooldown_active = Gauge(
            "crawler_ip_cooldown_active",
            "Observed active egress identity cooldown states.",
            ["reason"],
        )
        self.ip_cooldown_total = Counter(
            "crawler_ip_cooldown_total",
            "Total egress identity cooldown transitions.",
            ["reason"],
        )
        self.host_slowdown_active = Gauge(
            "crawler_host_slowdown_active",
            "Observed active host slowdown states.",
            ["reason"],
        )
        self.host_slowdown_total = Counter(
            "crawler_host_slowdown_total",
            "Total host slowdown transitions.",
            ["reason"],
        )
        self.host_asn_soft_limit_total = Counter(
            "crawler_host_asn_soft_limit_total",
            "Total host ASN soft-limit transitions.",
            ["asn", "reason"],
        )
        self.execution_state_writes_total = Counter(
            "crawler_execution_state_write_total",
            "Total Redis execution-state write attempts.",
            ["state_type", "result"],
        )
        self.execution_state_reads_total = Counter(
            "crawler_execution_state_read_total",
            "Total Redis execution-state read attempts.",
            ["state_type", "result"],
        )
        self.execution_state_ttl_seconds = Histogram(
            "crawler_execution_state_ttl_seconds",
            "TTL seconds set on Redis execution-state keys.",
            ["state_type"],
        )
        self.execution_state_forbidden_key_detected_total = Counter(
            "crawler_execution_state_forbidden_key_detected_total",
            "Total forbidden Redis key patterns detected by boundary audit.",
            ["pattern"],
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

    def set_fetch_queue_consumer_heartbeat(self, timestamp_seconds: float) -> None:
        self.fetch_queue_consumer_heartbeat_timestamp.set(timestamp_seconds)

    def record_dependency_health(self, dependency: str, healthy: bool) -> None:
        result = "success" if healthy else "failure"
        self.dependency_health_status.labels(dependency=dependency).set(1 if healthy else 0)
        self.dependency_health_events_total.labels(dependency=dependency, result=result).inc()

    def record_egress_identity_selected(self, strategy: str, egress_identity_type: str) -> None:
        self.egress_identity_selected_total.labels(
            strategy=strategy,
            egress_identity_type=egress_identity_type,
        ).inc()

    def record_sticky_pool_assignment(self, strategy: str) -> None:
        self.sticky_pool_assignments_total.labels(strategy=strategy).inc()

    def observe_sticky_pool_candidate_count(self, strategy: str, count: int) -> None:
        self.sticky_pool_size.labels(strategy=strategy).observe(count)

    def record_egress_identity_unavailable(self, reason: str) -> None:
        self.egress_identity_unavailable_total.labels(reason=reason).inc()

    def observe_pacer_delay(self, reason: str, delay_seconds: float, **_labels: str) -> None:
        self.pacer_delay_seconds.labels(reason=reason).observe(delay_seconds)

    def set_delayed_buffer_state(self, size: int, oldest_age_seconds: float, consumer: str = "unknown") -> None:
        self.delayed_buffer_size.labels(consumer=consumer or "unknown").set(size)
        self.delayed_buffer_oldest_age_seconds.labels(consumer=consumer or "unknown").set(oldest_age_seconds)

    def record_delayed_buffer_full(self, consumer: str = "unknown") -> None:
        self.delayed_buffer_full_total.labels(consumer=consumer or "unknown").inc()

    def record_delayed_message_expired(self, reason: str) -> None:
        self.delayed_message_expired_total.labels(reason=reason).inc()

    def record_xreadgroup_suppressed(self, reason: str) -> None:
        self.xreadgroup_suppressed_total.labels(reason=reason).inc()

    def record_feedback_signal(self, signal_type: str, dimension: str = "host_ip") -> None:
        self.feedback_signal_total.labels(signal_type=signal_type, dimension=dimension).inc()

    def set_host_ip_backoff_active(self, reason: str, active: bool = True) -> None:
        self.host_ip_backoff_active.labels(reason=reason).set(1 if active else 0)

    def observe_host_ip_backoff(self, reason: str, backoff_seconds: float) -> None:
        self.host_ip_backoff_seconds.labels(reason=reason).observe(backoff_seconds)

    def set_ip_cooldown_active(self, reason: str, active: bool = True) -> None:
        self.ip_cooldown_active.labels(reason=reason).set(1 if active else 0)

    def record_ip_cooldown(self, reason: str) -> None:
        self.ip_cooldown_total.labels(reason=reason).inc()

    def set_host_slowdown_active(self, reason: str, active: bool = True) -> None:
        self.host_slowdown_active.labels(reason=reason).set(1 if active else 0)

    def record_host_slowdown(self, reason: str) -> None:
        self.host_slowdown_total.labels(reason=reason).inc()

    def record_host_asn_soft_limit(self, reason: str, asn: str = "unknown") -> None:
        self.host_asn_soft_limit_total.labels(asn=asn or "unknown", reason=reason).inc()

    def record_execution_state_write(self, state_type: str, result: str) -> None:
        self.execution_state_writes_total.labels(state_type=state_type, result=result).inc()

    def record_execution_state_read(self, state_type: str, result: str) -> None:
        self.execution_state_reads_total.labels(state_type=state_type, result=result).inc()

    def observe_execution_state_ttl(self, state_type: str, ttl_seconds: int) -> None:
        self.execution_state_ttl_seconds.labels(state_type=state_type).observe(ttl_seconds)

    def record_execution_state_forbidden_key_detected(self, pattern: str) -> None:
        self.execution_state_forbidden_key_detected_total.labels(pattern=pattern).inc()


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
