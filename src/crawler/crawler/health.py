from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
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

