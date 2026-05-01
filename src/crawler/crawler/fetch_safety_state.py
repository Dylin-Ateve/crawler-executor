from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Sequence, Set

from crawler.metrics import metrics
from crawler.politeness import HostIpPacerState


FORBIDDEN_KEY_MARKERS = (
    "outlink",
    "scheduler",
    "dupefilter",
    "seen_url",
    "priority",
    "rank",
    "recrawl",
    "profile",
)


class FetchSafetyStateError(RuntimeError):
    """Raised when Redis execution-safety state cannot be handled."""


@dataclass(frozen=True)
class RedisWriteResult:
    ok: bool
    status: str
    key: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class EgressCooldownState:
    identity_hash: str
    cooldown_until_ms: int
    reason: str
    trigger_count: int
    last_updated_at_ms: int


@dataclass(frozen=True)
class HostSlowdownState:
    host_hash: str
    slowdown_until_ms: int
    slowdown_factor: float
    reason: str
    last_updated_at_ms: int


@dataclass(frozen=True)
class HostAsnSoftLimitState:
    host_hash: str
    asn: str
    limit_until_ms: int
    limit_factor: float
    reason: str
    last_updated_at_ms: int


@dataclass(frozen=True)
class SignalWindowCounter:
    key: str
    count: int
    weight_sum: int
    ttl_seconds: int


@dataclass(frozen=True)
class RedisBoundaryAuditResult:
    new_keys: frozenset[str]
    out_of_prefix_keys: frozenset[str]
    forbidden_keys: frozenset[str]
    missing_ttl_keys: frozenset[str]

    @property
    def passed(self) -> bool:
        return not self.out_of_prefix_keys and not self.forbidden_keys and not self.missing_ttl_keys


class ExecutionStateKeyBuilder:
    def __init__(self, prefix: str = "crawler:exec:safety") -> None:
        normalized = prefix.strip().rstrip(":")
        if not normalized:
            raise FetchSafetyStateError("EXECUTION_STATE_REDIS_PREFIX is required")
        self.prefix = normalized

    def host_ip(self, host_hash: str, identity_hash: str) -> str:
        return self._key("host_ip", host_hash, identity_hash)

    def ip(self, identity_hash: str) -> str:
        return self._key("ip", identity_hash)

    def host(self, host_hash: str) -> str:
        return self._key("host", host_hash)

    def host_asn(self, host_hash: str, asn: str) -> str:
        return self._key("host_asn", host_hash, asn)

    def host_cidr(self, host_hash: str, cidr_hash: str) -> str:
        return self._key("host_cidr", host_hash, cidr_hash)

    def signal(self, dimension: str, dimension_hash: str, signal_type: str) -> str:
        return self._key("signal", dimension, dimension_hash, signal_type)

    def consumer(self, consumer_name_hash: str) -> str:
        return self._key("consumer", consumer_name_hash)

    def is_allowed_key(self, key: str) -> bool:
        return key.startswith(f"{self.prefix}:") and not contains_forbidden_marker(key)

    def _key(self, *parts: str) -> str:
        safe_parts = [_safe_part(part) for part in parts]
        key = ":".join((self.prefix, *safe_parts))
        if contains_forbidden_marker(key):
            raise FetchSafetyStateError(f"forbidden execution-state key marker in key: {key}")
        return key


class FetchSafetyStateStore:
    def __init__(
        self,
        redis_client: object,
        *,
        key_builder: Optional[ExecutionStateKeyBuilder] = None,
        max_ttl_seconds: int = 86400,
        write_enabled: bool = True,
        fail_open: bool = True,
    ) -> None:
        self.redis_client = redis_client
        self.key_builder = key_builder or ExecutionStateKeyBuilder()
        self.max_ttl_seconds = max_ttl_seconds
        self.write_enabled = write_enabled
        self.fail_open = fail_open

    def set_host_ip_backoff(
        self,
        host_hash: str,
        identity_hash: str,
        state: HostIpPacerState,
        *,
        ttl_seconds: int,
    ) -> RedisWriteResult:
        key = self.key_builder.host_ip(host_hash, identity_hash)
        mapping = {
            "next_allowed_at_ms": state.next_allowed_at_ms,
            "min_delay_ms": state.min_delay_ms,
            "backoff_level": state.backoff_level,
            "last_signal": state.last_signal or "",
            "last_updated_at_ms": state.last_updated_at_ms,
        }
        return self._hset_with_ttl(key, mapping, ttl_seconds, state_type="host_ip")

    def get_host_ip_backoff(self, host_hash: str, identity_hash: str) -> Optional[HostIpPacerState]:
        key = self.key_builder.host_ip(host_hash, identity_hash)
        data = self._hgetall(key, state_type="host_ip")
        if not data:
            return None
        return HostIpPacerState(
            next_allowed_at_ms=_int(data.get("next_allowed_at_ms"), 0),
            min_delay_ms=_int(data.get("min_delay_ms"), 0),
            backoff_level=_int(data.get("backoff_level"), 0),
            last_signal=data.get("last_signal") or None,
            last_updated_at_ms=_int(data.get("last_updated_at_ms"), 0),
        )

    def set_ip_cooldown(
        self,
        identity_hash: str,
        *,
        cooldown_until_ms: int,
        reason: str,
        trigger_count: int,
        now_ms: Optional[int] = None,
        ttl_seconds: int,
    ) -> RedisWriteResult:
        key = self.key_builder.ip(identity_hash)
        timestamp = now_ms if now_ms is not None else int(time.time() * 1000)
        return self._hset_with_ttl(
            key,
            {
                "cooldown_until_ms": cooldown_until_ms,
                "reason": reason,
                "trigger_count": trigger_count,
                "last_updated_at_ms": timestamp,
            },
            ttl_seconds,
            state_type="ip",
        )

    def get_ip_cooldown(self, identity_hash: str) -> Optional[EgressCooldownState]:
        key = self.key_builder.ip(identity_hash)
        data = self._hgetall(key, state_type="ip")
        if not data:
            return None
        return EgressCooldownState(
            identity_hash=identity_hash,
            cooldown_until_ms=_int(data.get("cooldown_until_ms"), 0),
            reason=data.get("reason") or "",
            trigger_count=_int(data.get("trigger_count"), 0),
            last_updated_at_ms=_int(data.get("last_updated_at_ms"), 0),
        )

    def set_host_slowdown(
        self,
        host_hash: str,
        *,
        slowdown_until_ms: int,
        slowdown_factor: float,
        reason: str,
        now_ms: Optional[int] = None,
        ttl_seconds: int,
    ) -> RedisWriteResult:
        key = self.key_builder.host(host_hash)
        timestamp = now_ms if now_ms is not None else int(time.time() * 1000)
        return self._hset_with_ttl(
            key,
            {
                "slowdown_until_ms": slowdown_until_ms,
                "slowdown_factor": slowdown_factor,
                "reason": reason,
                "last_updated_at_ms": timestamp,
            },
            ttl_seconds,
            state_type="host",
        )

    def get_host_slowdown(self, host_hash: str) -> Optional[HostSlowdownState]:
        key = self.key_builder.host(host_hash)
        data = self._hgetall(key, state_type="host")
        if not data:
            return None
        return HostSlowdownState(
            host_hash=host_hash,
            slowdown_until_ms=_int(data.get("slowdown_until_ms"), 0),
            slowdown_factor=_float(data.get("slowdown_factor"), 1.0),
            reason=data.get("reason") or "",
            last_updated_at_ms=_int(data.get("last_updated_at_ms"), 0),
        )

    def set_host_asn_soft_limit(
        self,
        host_hash: str,
        asn: str,
        *,
        limit_until_ms: int,
        limit_factor: float,
        reason: str,
        now_ms: Optional[int] = None,
        ttl_seconds: int,
    ) -> RedisWriteResult:
        key = self.key_builder.host_asn(host_hash, asn)
        timestamp = now_ms if now_ms is not None else int(time.time() * 1000)
        return self._hset_with_ttl(
            key,
            {
                "limit_until_ms": limit_until_ms,
                "limit_factor": limit_factor,
                "reason": reason,
                "last_updated_at_ms": timestamp,
            },
            ttl_seconds,
            state_type="host_asn",
        )

    def get_host_asn_soft_limit(self, host_hash: str, asn: str) -> Optional[HostAsnSoftLimitState]:
        key = self.key_builder.host_asn(host_hash, asn)
        data = self._hgetall(key, state_type="host_asn")
        if not data:
            return None
        return HostAsnSoftLimitState(
            host_hash=host_hash,
            asn=asn,
            limit_until_ms=_int(data.get("limit_until_ms"), 0),
            limit_factor=_float(data.get("limit_factor"), 1.0),
            reason=data.get("reason") or "",
            last_updated_at_ms=_int(data.get("last_updated_at_ms"), 0),
        )

    def increment_signal_window(
        self,
        *,
        dimension: str,
        dimension_hash: str,
        signal_type: str,
        weight: int,
        window_seconds: int,
    ) -> SignalWindowCounter:
        key = self.key_builder.signal(dimension, dimension_hash, signal_type)
        ttl = self._ttl(window_seconds)
        if not self.write_enabled:
            metrics.record_execution_state_write("signal", "disabled")
            return SignalWindowCounter(key=key, count=0, weight_sum=0, ttl_seconds=ttl)
        try:
            count = int(self.redis_client.hincrby(key, "count", 1))
            weight_sum = int(self.redis_client.hincrby(key, "weight_sum", weight))
            self.redis_client.expire(key, ttl)
            metrics.record_execution_state_write("signal", "written")
            metrics.observe_execution_state_ttl("signal", ttl)
            return SignalWindowCounter(key=key, count=count, weight_sum=weight_sum, ttl_seconds=ttl)
        except Exception as exc:
            metrics.record_execution_state_write("signal", "failed")
            if self.fail_open:
                return SignalWindowCounter(key=key, count=0, weight_sum=0, ttl_seconds=ttl)
            raise FetchSafetyStateError(str(exc)) from exc

    def increment_distinct_signal_window(
        self,
        *,
        dimension: str,
        dimension_hash: str,
        signal_type: str,
        member_hash: str,
        weight: int,
        window_seconds: int,
    ) -> SignalWindowCounter:
        key = self.key_builder.signal(dimension, dimension_hash, signal_type)
        ttl = self._ttl(window_seconds)
        if not self.write_enabled:
            metrics.record_execution_state_write("signal", "disabled")
            return SignalWindowCounter(key=key, count=0, weight_sum=0, ttl_seconds=ttl)
        try:
            data = self._hgetall(key, state_type="signal")
            member_field = f"member:{_safe_part(member_hash)}"
            if member_field not in data:
                self.redis_client.hset(key, mapping={member_field: 1})
                count = int(self.redis_client.hincrby(key, "count", 1))
            else:
                count = _int(data.get("count"), 0)
            weight_sum = int(self.redis_client.hincrby(key, "weight_sum", weight))
            self.redis_client.expire(key, ttl)
            metrics.record_execution_state_write("signal", "written")
            metrics.observe_execution_state_ttl("signal", ttl)
            return SignalWindowCounter(key=key, count=count, weight_sum=weight_sum, ttl_seconds=ttl)
        except Exception as exc:
            metrics.record_execution_state_write("signal", "failed")
            if self.fail_open:
                return SignalWindowCounter(key=key, count=0, weight_sum=0, ttl_seconds=ttl)
            raise FetchSafetyStateError(str(exc)) from exc

    def _hset_with_ttl(
        self,
        key: str,
        mapping: Mapping[str, object],
        ttl_seconds: int,
        *,
        state_type: str,
    ) -> RedisWriteResult:
        ttl = self._ttl(ttl_seconds)
        if not self.write_enabled:
            metrics.record_execution_state_write(state_type, "disabled")
            return RedisWriteResult(ok=False, status="disabled", key=key)
        try:
            self.redis_client.hset(key, mapping=mapping)
            self.redis_client.expire(key, ttl)
            metrics.record_execution_state_write(state_type, "written")
            metrics.observe_execution_state_ttl(state_type, ttl)
            return RedisWriteResult(ok=True, status="written", key=key)
        except Exception as exc:
            metrics.record_execution_state_write(state_type, "failed")
            if self.fail_open:
                return RedisWriteResult(ok=False, status="failed_open", key=key, error=str(exc))
            raise FetchSafetyStateError(str(exc)) from exc

    def _hgetall(self, key: str, *, state_type: str) -> Dict[str, str]:
        try:
            raw = self.redis_client.hgetall(key)
        except Exception as exc:
            metrics.record_execution_state_read(state_type, "failed")
            if self.fail_open:
                return {}
            raise FetchSafetyStateError(str(exc)) from exc
        metrics.record_execution_state_read(state_type, "hit" if raw else "miss")
        return {str(k): str(v) for k, v in (raw or {}).items()}

    def _ttl(self, ttl_seconds: int) -> int:
        return max(1, min(int(ttl_seconds), int(self.max_ttl_seconds)))


def audit_redis_key_diff(
    *,
    before_keys: Iterable[str],
    after_keys: Iterable[str],
    prefix: str,
    ttl_by_key: Optional[Mapping[str, int]] = None,
    allowed_extra_prefixes: Sequence[str] = (),
) -> RedisBoundaryAuditResult:
    builder = ExecutionStateKeyBuilder(prefix)
    before = set(before_keys)
    after = set(after_keys)
    new_keys = after - before
    allowed_extra = tuple(value.rstrip(":") for value in allowed_extra_prefixes)

    out_of_prefix = {
        key
        for key in new_keys
        if not builder.is_allowed_key(key) and not any(key.startswith(prefix) for prefix in allowed_extra)
    }
    forbidden = {key for key in new_keys if contains_forbidden_marker(key)}
    for key in forbidden:
        for marker in FORBIDDEN_KEY_MARKERS:
            if marker in key.lower():
                metrics.record_execution_state_forbidden_key_detected(marker)
                break
    missing_ttl: Set[str] = set()
    if ttl_by_key is not None:
        for key in new_keys:
            if builder.is_allowed_key(key) and int(ttl_by_key.get(key, -1)) <= 0:
                missing_ttl.add(key)

    return RedisBoundaryAuditResult(
        new_keys=frozenset(new_keys),
        out_of_prefix_keys=frozenset(out_of_prefix),
        forbidden_keys=frozenset(forbidden),
        missing_ttl_keys=frozenset(missing_ttl),
    )


def contains_forbidden_marker(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in FORBIDDEN_KEY_MARKERS)


def _safe_part(value: str) -> str:
    part = str(value).strip()
    if not part:
        raise FetchSafetyStateError("execution-state key part is required")
    if ":" in part or "/" in part or " " in part:
        raise FetchSafetyStateError(f"unsafe execution-state key part: {value}")
    return part


def _int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
