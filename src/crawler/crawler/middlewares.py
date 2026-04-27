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
from crawler.metrics import metrics

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
    def __init__(self, health_store: RedisHealthStore) -> None:
        self.health_store = health_store

    @classmethod
    def from_crawler(cls, crawler):
        redis_client = build_redis_client(crawler.settings.get("REDIS_URL"))
        health_store = RedisHealthStore(
            redis_client=redis_client,
            failure_threshold=crawler.settings.getint("IP_FAILURE_THRESHOLD", 5),
            window_seconds=crawler.settings.getint("IP_FAILURE_WINDOW_SECONDS", 300),
            cooldown_seconds=crawler.settings.getint("IP_COOLDOWN_SECONDS", 1800),
            key_prefix=crawler.settings.get("REDIS_KEY_PREFIX", "crawler"),
        )
        return cls(health_store=health_store)

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
        return None

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
