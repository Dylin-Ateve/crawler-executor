from __future__ import annotations

import time
from urllib.parse import urlparse

from crawler.health import (
    GLOBAL_EXCEPTION_NAMES,
    RedisHealthStore,
    classify_exception,
    contains_captcha,
    failure_reason_for_status,
)
from crawler.ip_pool import IpPoolError, LocalIpPool, discover_local_ips
from crawler.egress_identity import stable_hash
from crawler.fetch_safety_state import ExecutionStateKeyBuilder, FetchSafetyStateStore
from crawler.metrics import metrics
from crawler.politeness import HostIpPacerConfig
from crawler.response_signals import (
    FeedbackWeights,
    classify_exception_signal,
    classify_response_signal,
    parse_body_patterns,
)
from crawler.soft_ban_feedback import SoftBanFeedbackConfig, SoftBanFeedbackController

try:
    from scrapy.exceptions import IgnoreRequest, NotConfigured
except Exception:
    class IgnoreRequest(Exception):
        pass

    class NotConfigured(Exception):
        pass


def request_host(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.netloc or parsed.path).lower()


def build_redis_client(redis_url: str):
    if not redis_url:
        raise NotConfigured(
            "REDIS_URL is required, format: redis://<username>:<url-encoded-password>@<host>:<port>/<db>"
        )
    try:
        import redis
    except ImportError as exc:
        raise NotConfigured("redis package is required for P0 IP health state") from exc
    return redis.Redis.from_url(redis_url, decode_responses=True)


class LocalIpRotationMiddleware:
    def __init__(self, ip_pool: LocalIpPool, health_store: RedisHealthStore, force_close_connections: bool = True) -> None:
        self.ip_pool = ip_pool
        self.health_store = health_store
        self.force_close_connections = force_close_connections
        metrics.set_active_ip_count(len(self.ip_pool.ip_pool))

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        interface = settings.get("CRAWL_INTERFACE", "ens3")
        excluded = settings.getlist("EXCLUDED_LOCAL_IPS", [])
        ips = settings.getlist("LOCAL_IP_POOL") or discover_local_ips(interface, excluded)
        if not ips:
            raise NotConfigured(f"no local IPs discovered on interface {interface}")

        redis_client = build_redis_client(settings.get("REDIS_URL"))
        health_store = RedisHealthStore(
            redis_client=redis_client,
            failure_threshold=settings.getint("IP_FAILURE_THRESHOLD", 5),
            window_seconds=settings.getint("IP_FAILURE_WINDOW_SECONDS", 300),
            cooldown_seconds=settings.getint("IP_COOLDOWN_SECONDS", 1800),
            key_prefix=settings.get("REDIS_KEY_PREFIX", "crawler"),
        )
        ip_pool = LocalIpPool(ips, strategy=settings.get("IP_SELECTION_STRATEGY", "STICKY_BY_HOST"))
        return cls(
            ip_pool=ip_pool,
            health_store=health_store,
            force_close_connections=settings.getbool("FORCE_CLOSE_CONNECTIONS", True),
        )

    def process_request(self, request, spider):
        host = request_host(request.url)
        preselected_ip = request.meta.get("egress_bind_ip") or request.meta.get("egress_local_ip")
        if preselected_ip:
            local_ip = str(preselected_ip)
            if self.health_store.is_blacklisted(host, local_ip):
                message = f"preselected local IP is blacklisted for host={host} ip={local_ip}"
                spider.logger.warning(message)
                raise IgnoreRequest(message)
        else:
            try:
                local_ip = self.ip_pool.select_for_host(host, self.health_store.is_blacklisted)
            except IpPoolError as exc:
                spider.logger.warning("no available local IP for host=%s: %s", host, exc)
                raise IgnoreRequest(str(exc))

        request.meta["bindaddress"] = (local_ip, 0)
        request.meta["egress_local_ip"] = local_ip
        request.meta["egress_host"] = host
        request.meta["request_started_monotonic"] = time.monotonic()
        if self.force_close_connections:
            request.headers.setdefault("Connection", "close")
        return None


class IpHealthCheckMiddleware:
    def __init__(
        self,
        health_store: RedisHealthStore,
        *,
        feedback_controller: SoftBanFeedbackController = None,
        feedback_weights: FeedbackWeights = FeedbackWeights(),
        challenge_patterns=(),
        anti_bot_200_patterns=(),
        hash_salt: str = "",
    ) -> None:
        self.health_store = health_store
        self.feedback_controller = feedback_controller
        self.feedback_weights = feedback_weights
        self.challenge_patterns = tuple(challenge_patterns)
        self.anti_bot_200_patterns = tuple(anti_bot_200_patterns)
        self.hash_salt = hash_salt

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        redis_client = build_redis_client(crawler.settings.get("REDIS_URL"))
        health_store = RedisHealthStore(
            redis_client=redis_client,
            failure_threshold=settings.getint("IP_FAILURE_THRESHOLD", 5),
            window_seconds=settings.getint("IP_FAILURE_WINDOW_SECONDS", 300),
            cooldown_seconds=settings.getint("IP_COOLDOWN_SECONDS", 1800),
            key_prefix=settings.get("REDIS_KEY_PREFIX", "crawler"),
        )
        return cls(
            health_store=health_store,
            feedback_controller=build_soft_ban_feedback_controller(settings),
            feedback_weights=FeedbackWeights(
                http_429=settings.getint("HTTP_429_WEIGHT", 3),
                captcha_challenge=settings.getint("CAPTCHA_CHALLENGE_WEIGHT", 5),
                anti_bot_200=settings.getint("ANTI_BOT_200_WEIGHT", 4),
                http_5xx=settings.getint("HTTP_5XX_WEIGHT", 1),
                timeout=settings.getint("TIMEOUT_WEIGHT", 1),
                connection_failed=settings.getint("CONNECTION_FAILED_WEIGHT", 1),
            ),
            challenge_patterns=parse_body_patterns(settings.get("CHALLENGE_BODY_PATTERNS", "") or ""),
            anti_bot_200_patterns=parse_body_patterns(settings.get("ANTI_BOT_200_PATTERNS", "") or ""),
            hash_salt=settings.get("EGRESS_IDENTITY_HASH_SALT", "") or "",
        )

    def process_response(self, request, response, spider):
        host = request.meta.get("egress_host") or request_host(request.url)
        ip = request.meta.get("egress_local_ip", "")
        duration = self._duration(request)
        status = getattr(response, "status", 0)
        reason = failure_reason_for_status(status)

        body = getattr(response, "body", b"") or b""
        content_type = self._content_type(response)
        if contains_captcha(body, content_type):
            self.health_store.record_failure(host, ip, "CAPTCHA_DETECTED", immediate=True)
        elif reason:
            self.health_store.record_failure(host, ip, reason)
        else:
            self.health_store.record_success(host, ip)

        metrics.record_response(host, str(status), ip, duration)
        metrics.set_blacklist_count(self.health_store.blacklist_count())
        signal = classify_response_signal(
            host=host,
            identity_hash=self._identity_hash(request, ip),
            status_code=status,
            body=body,
            challenge_patterns=self.challenge_patterns,
            anti_bot_200_patterns=self.anti_bot_200_patterns,
            weights=self.feedback_weights,
            hash_salt=self.hash_salt,
            attempt_id=request.meta.get("attempt_id"),
        )
        self._record_feedback_signal(request, signal)
        return response

    def process_exception(self, request, exception, spider):
        host = request.meta.get("egress_host") or request_host(request.url)
        ip = request.meta.get("egress_local_ip", "")
        reason = classify_exception(exception)
        if reason in GLOBAL_EXCEPTION_NAMES:
            self.health_store.record_global_failure(ip, reason)
        self.health_store.record_failure(host, ip, reason)
        metrics.record_response(host, reason, ip, self._duration(request))
        metrics.set_blacklist_count(self.health_store.blacklist_count())
        signal = classify_exception_signal(
            host=host,
            identity_hash=self._identity_hash(request, ip),
            exception=exception,
            weights=self.feedback_weights,
            hash_salt=self.hash_salt,
            attempt_id=request.meta.get("attempt_id"),
        )
        self._record_feedback_signal(request, signal)
        return None

    def _record_feedback_signal(self, request, signal) -> None:
        if not self.feedback_controller:
            metrics.record_feedback_signal(signal.signal_type, "unhandled")
            return
        self.feedback_controller.record_signal(
            signal,
            asn=request.meta.get("egress_asn"),
            cidr=request.meta.get("egress_cidr"),
        )

    def _identity_hash(self, request, ip: str) -> str:
        return request.meta.get("egress_identity_hash") or stable_hash(ip or "unknown", salt=self.hash_salt)

    @staticmethod
    def _duration(request):
        started = request.meta.get("request_started_monotonic")
        if started is None:
            return None
        return max(time.monotonic() - started, 0.0)

    @staticmethod
    def _content_type(response) -> str:
        try:
            value = response.headers.get(b"Content-Type", b"")
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="ignore").lower()
            return str(value).lower()
        except Exception:
            return ""


def build_soft_ban_feedback_controller(settings):
    redis_url = settings.get("EXECUTION_STATE_REDIS_URL") or settings.get("REDIS_URL")
    if not redis_url:
        return None
    redis_client = build_redis_client(redis_url)
    store = FetchSafetyStateStore(
        redis_client,
        key_builder=ExecutionStateKeyBuilder(settings.get("EXECUTION_STATE_REDIS_PREFIX", "crawler:exec:safety")),
        max_ttl_seconds=settings.getint("EXECUTION_STATE_MAX_TTL_SECONDS", 86400),
        write_enabled=settings.getbool("EXECUTION_STATE_WRITE_ENABLED", True),
        fail_open=settings.getbool("EXECUTION_STATE_FAIL_OPEN", True),
    )
    return SoftBanFeedbackController(
        store,
        config=SoftBanFeedbackConfig(
            soft_ban_window_seconds=settings.getint("SOFT_BAN_WINDOW_SECONDS", 300),
            host_ip_soft_ban_threshold=settings.getint("HOST_IP_SOFT_BAN_THRESHOLD", 2),
            ip_cross_host_challenge_threshold=settings.getint("IP_CROSS_HOST_CHALLENGE_THRESHOLD", 3),
            host_cross_ip_challenge_threshold=settings.getint("HOST_CROSS_IP_CHALLENGE_THRESHOLD", 3),
            host_ip_backoff_ttl_seconds=settings.getint("EXECUTION_STATE_MAX_TTL_SECONDS", 86400),
            ip_cooldown_seconds=settings.getint("IP_COOLDOWN_SECONDS", 1800),
            host_slowdown_seconds=settings.getint("HOST_SLOWDOWN_SECONDS", 600),
            host_slowdown_factor=float(settings.get("HOST_SLOWDOWN_FACTOR", 3.0)),
            host_asn_soft_limit_enabled=settings.getbool("HOST_ASN_SOFT_LIMIT_ENABLED", False),
            host_asn_soft_limit_seconds=settings.getint("HOST_ASN_SOFT_LIMIT_SECONDS", 600),
            host_asn_soft_limit_factor=float(settings.get("HOST_ASN_SOFT_LIMIT_FACTOR", 3.0)),
        ),
        pacer_config=HostIpPacerConfig(
            min_delay_ms=settings.getint("HOST_IP_MIN_DELAY_MS", 2000),
            jitter_ms=settings.getint("HOST_IP_JITTER_MS", 500),
            backoff_base_ms=settings.getint("HOST_IP_BACKOFF_BASE_MS", 5000),
            backoff_max_ms=settings.getint("HOST_IP_BACKOFF_MAX_MS", 300000),
            backoff_multiplier=float(settings.get("HOST_IP_BACKOFF_MULTIPLIER", 2.0)),
        ),
    )
