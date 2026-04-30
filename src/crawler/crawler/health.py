from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote


BLOCK_STATUS_CODES = {403, 429, 503}
GLOBAL_EXCEPTION_NAMES = {
    "TimeoutError",
    "TCPTimedOutError",
    "DNSLookupError",
    "ConnectionRefusedError",
    "ConnectionDone",
    "ConnectionLost",
}
CAPTCHA_MARKERS = ("captcha", "recaptcha", "hcaptcha", "verify you are human")


@dataclass
class RuntimeHealthState:
    started_at: float = field(default_factory=time.time)
    live: bool = True
    worker_initialized: bool = False
    last_consumer_heartbeat_at: Optional[float] = None


runtime_health_state = RuntimeHealthState()


def host_key(host: str) -> str:
    return quote(host.lower().strip(), safe="")


def failure_reason_for_status(status_code: int) -> Optional[str]:
    if status_code in BLOCK_STATUS_CODES:
        return f"HTTP_{status_code}"
    return None


def contains_captcha(body: bytes, content_type: str = "") -> bool:
    if content_type and "text" not in content_type and "html" not in content_type:
        return False
    sample = body[:131072].decode("utf-8", errors="ignore").lower()
    return any(marker in sample for marker in CAPTCHA_MARKERS)


def classify_exception(exception: BaseException) -> str:
    return type(exception).__name__


def build_liveness_payload(state: RuntimeHealthState = runtime_health_state) -> Tuple[int, Dict[str, object]]:
    payload = {
        "status": "ok" if state.live else "failed",
        "started_at": int(state.started_at),
        "uptime_seconds": max(time.time() - state.started_at, 0.0),
    }
    return (200 if state.live else 503), payload


def mark_worker_initialized(state: RuntimeHealthState = runtime_health_state, now: Optional[float] = None) -> None:
    timestamp = now if now is not None else time.time()
    state.worker_initialized = True
    state.last_consumer_heartbeat_at = timestamp


def record_consumer_heartbeat(state: RuntimeHealthState = runtime_health_state, now: Optional[float] = None) -> None:
    state.last_consumer_heartbeat_at = now if now is not None else time.time()


def build_readiness_payload(
    state: RuntimeHealthState = runtime_health_state,
    *,
    max_heartbeat_age_seconds: int = 30,
    now: Optional[float] = None,
) -> Tuple[int, Dict[str, object]]:
    timestamp = now if now is not None else time.time()
    last_heartbeat = state.last_consumer_heartbeat_at
    heartbeat_age = None if last_heartbeat is None else max(timestamp - last_heartbeat, 0.0)
    ready = bool(
        state.worker_initialized
        and last_heartbeat is not None
        and heartbeat_age is not None
        and heartbeat_age <= max_heartbeat_age_seconds
    )
    payload = {
        "status": "ready" if ready else "not_ready",
        "worker_initialized": state.worker_initialized,
        "last_consumer_heartbeat_at": int(last_heartbeat) if last_heartbeat is not None else None,
        "consumer_heartbeat_age_seconds": heartbeat_age,
        "max_heartbeat_age_seconds": max_heartbeat_age_seconds,
    }
    return (200 if ready else 503), payload


class HealthCheckHandler(BaseHTTPRequestHandler):
    state = runtime_health_state
    max_heartbeat_age_seconds = 30

    def do_GET(self) -> None:
        if self.path == "/health/liveness":
            status_code, payload = build_liveness_payload(self.state)
            self._write_json(status_code, payload)
            return
        if self.path == "/health/readiness":
            status_code, payload = build_readiness_payload(
                self.state,
                max_heartbeat_age_seconds=self.max_heartbeat_age_seconds,
            )
            self._write_json(status_code, payload)
            return
        self._write_json(404, {"status": "not_found", "path": self.path})

    def log_message(self, _format: str, *_args) -> None:
        return

    def _write_json(self, status_code: int, payload: Dict[str, object]) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class HealthCheckServer:
    def __init__(
        self,
        port: int = 9411,
        state: RuntimeHealthState = runtime_health_state,
        max_heartbeat_age_seconds: int = 30,
    ) -> None:
        self.port = port
        self.state = state
        self.max_heartbeat_age_seconds = max_heartbeat_age_seconds
        self.started = False
        self._server = None
        self._thread = None

    def start(self) -> None:
        if self.started:
            return

        handler = type(
            "CrawlerHealthCheckHandler",
            (HealthCheckHandler,),
            {
                "state": self.state,
                "max_heartbeat_age_seconds": self.max_heartbeat_age_seconds,
            },
        )
        server = ThreadingHTTPServer(("", self.port), handler)
        thread = threading.Thread(target=server.serve_forever, name="crawler-health-http", daemon=True)
        thread.start()
        self._server = server
        self._thread = thread
        self.started = True


class HealthCheckExtension:
    def __init__(
        self,
        port: int = 9411,
        max_heartbeat_age_seconds: int = 30,
        server: Optional[HealthCheckServer] = None,
    ) -> None:
        self.port = port
        self.max_heartbeat_age_seconds = max_heartbeat_age_seconds
        self.server = server or HealthCheckServer(
            port=port,
            max_heartbeat_age_seconds=max_heartbeat_age_seconds,
        )

    @classmethod
    def from_crawler(cls, crawler):
        port = crawler.settings.getint("HEALTH_PORT", 9411)
        max_heartbeat_age_seconds = crawler.settings.getint("READINESS_MAX_HEARTBEAT_AGE_SECONDS", 30)
        extension = cls(port=port, max_heartbeat_age_seconds=max_heartbeat_age_seconds)
        try:
            from scrapy import signals
            crawler.signals.connect(extension.spider_opened, signal=signals.spider_opened)
        except Exception:
            pass
        return extension

    def spider_opened(self, spider) -> None:
        try:
            self.server.start()
            spider.logger.info("Health check endpoint started on port %s", self.port)
        except Exception as exc:
            spider.logger.warning("failed to start health check endpoint: %s", exc)


@dataclass
class RedisHealthStore:
    redis_client: object
    failure_threshold: int = 5
    window_seconds: int = 300
    cooldown_seconds: int = 1800
    key_prefix: str = "crawler"
    local_blacklist: Dict[Tuple[str, str], Tuple[float, str]] = field(default_factory=dict)
    local_failures: Dict[Tuple[str, str], List[float]] = field(default_factory=dict)

    def failure_key(self, host: str, ip: str) -> str:
        return f"{self.key_prefix}:fail:{host_key(host)}:{ip}"

    def blacklist_key(self, host: str, ip: str) -> str:
        return f"{self.key_prefix}:blacklist:{host_key(host)}:{ip}"

    def global_ip_key(self, ip: str) -> str:
        return f"{self.key_prefix}:ip:global:{ip}"

    def is_blacklisted(self, host: str, ip: str) -> bool:
        self._expire_local(time.time())
        local_key = (host.lower().strip(), ip)
        if local_key in self.local_blacklist:
            return True
        try:
            return bool(self.redis_client.exists(self.blacklist_key(host, ip)))
        except Exception:
            return False

    def record_success(self, host: str, ip: str) -> None:
        local_key = (host.lower().strip(), ip)
        self.local_failures.pop(local_key, None)
        try:
            self.redis_client.delete(self.failure_key(host, ip))
        except Exception:
            return

    def record_failure(
        self,
        host: str,
        ip: str,
        reason: str,
        now: Optional[float] = None,
        immediate: bool = False,
    ) -> bool:
        now = now or time.time()
        if immediate:
            self.blacklist(host, ip, reason, now=now)
            return True

        try:
            key = self.failure_key(host, ip)
            self.redis_client.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})
            self.redis_client.zremrangebyscore(key, 0, now - self.window_seconds)
            self.redis_client.expire(key, self.window_seconds + self.cooldown_seconds)
            failures = int(self.redis_client.zcard(key))
            if failures >= self.failure_threshold:
                self.blacklist(host, ip, reason, now=now)
                return True
            return False
        except Exception:
            return self._record_local_failure(host, ip, reason, now)

    def record_global_failure(self, ip: str, reason: str, now: Optional[float] = None) -> None:
        now = now or time.time()
        try:
            key = self.global_ip_key(ip)
            self.redis_client.hincrby(key, "failure_count", 1)
            self.redis_client.hset(key, mapping={"last_failure_ts": int(now), "status": "DEGRADED", "reason": reason})
            self.redis_client.expire(key, self.window_seconds + self.cooldown_seconds)
        except Exception:
            return

    def blacklist(self, host: str, ip: str, reason: str, now: Optional[float] = None) -> None:
        now = now or time.time()
        local_key = (host.lower().strip(), ip)
        self.local_blacklist[local_key] = (now + self.cooldown_seconds, reason)
        try:
            self.redis_client.setex(self.blacklist_key(host, ip), self.cooldown_seconds, reason)
        except Exception:
            return

    def blacklist_count(self, hosts: Optional[Iterable[str]] = None) -> int:
        self._expire_local(time.time())
        if hosts is not None:
            host_prefixes = [host_key(host) for host in hosts]
            return sum(1 for host, _ip in self.local_blacklist if host_key(host) in host_prefixes)
        try:
            pattern = f"{self.key_prefix}:blacklist:*"
            return sum(1 for _ in self.redis_client.scan_iter(match=pattern))
        except Exception:
            return len(self.local_blacklist)

    def _record_local_failure(self, host: str, ip: str, reason: str, now: float) -> bool:
        local_key = (host.lower().strip(), ip)
        failures = [ts for ts in self.local_failures.get(local_key, []) if ts >= now - self.window_seconds]
        failures.append(now)
        self.local_failures[local_key] = failures
        if len(failures) >= self.failure_threshold:
            self.local_blacklist[local_key] = (now + self.cooldown_seconds, reason)
            return True
        return False

    def _expire_local(self, now: float) -> None:
        expired = [key for key, (expires_at, _reason) in self.local_blacklist.items() if expires_at <= now]
        for key in expired:
            self.local_blacklist.pop(key, None)
