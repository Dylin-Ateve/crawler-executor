from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class HostIpPacerConfig:
    min_delay_ms: int = 2000
    jitter_ms: int = 500
    backoff_base_ms: int = 5000
    backoff_max_ms: int = 300000
    backoff_multiplier: float = 2.0


@dataclass(frozen=True)
class HostIpPacerState:
    next_allowed_at_ms: int = 0
    min_delay_ms: int = 0
    backoff_level: int = 0
    last_signal: Optional[str] = None
    last_started_at_ms: Optional[int] = None
    last_updated_at_ms: int = 0


@dataclass(frozen=True)
class PacerDecision:
    eligible: bool
    delay_ms: int
    next_allowed_at_ms: int


def pacer_decision(state: HostIpPacerState, now_ms: int) -> PacerDecision:
    delay_ms = max(state.next_allowed_at_ms - now_ms, 0)
    return PacerDecision(
        eligible=delay_ms == 0,
        delay_ms=delay_ms,
        next_allowed_at_ms=state.next_allowed_at_ms,
    )


def mark_request_started(
    state: HostIpPacerState,
    config: HostIpPacerConfig,
    now_ms: int,
    *,
    host_slowdown_factor: float = 1.0,
    jitter_ms: Optional[int] = None,
) -> HostIpPacerState:
    interval = _scaled(config.min_delay_ms, host_slowdown_factor) + _jitter(config, jitter_ms)
    return HostIpPacerState(
        next_allowed_at_ms=now_ms + interval,
        min_delay_ms=_scaled(config.min_delay_ms, host_slowdown_factor),
        backoff_level=state.backoff_level,
        last_signal=state.last_signal,
        last_started_at_ms=now_ms,
        last_updated_at_ms=now_ms,
    )


def mark_success(state: HostIpPacerState, now_ms: int) -> HostIpPacerState:
    return HostIpPacerState(
        next_allowed_at_ms=state.next_allowed_at_ms,
        min_delay_ms=state.min_delay_ms,
        backoff_level=0,
        last_signal="success",
        last_started_at_ms=state.last_started_at_ms,
        last_updated_at_ms=now_ms,
    )


def mark_backoff(
    state: HostIpPacerState,
    config: HostIpPacerConfig,
    now_ms: int,
    *,
    signal_type: str,
    host_slowdown_factor: float = 1.0,
) -> HostIpPacerState:
    next_level = state.backoff_level + 1
    raw_delay = config.backoff_base_ms * (config.backoff_multiplier ** (next_level - 1))
    delay_ms = min(_scaled(int(raw_delay), host_slowdown_factor), config.backoff_max_ms)
    return HostIpPacerState(
        next_allowed_at_ms=now_ms + delay_ms,
        min_delay_ms=state.min_delay_ms,
        backoff_level=next_level,
        last_signal=signal_type,
        last_started_at_ms=state.last_started_at_ms,
        last_updated_at_ms=now_ms,
    )


def _scaled(value_ms: int, factor: float) -> int:
    return max(int(value_ms * max(factor, 1.0)), 0)


def _jitter(config: HostIpPacerConfig, jitter_ms: Optional[int]) -> int:
    if jitter_ms is not None:
        return max(jitter_ms, 0)
    if config.jitter_ms <= 0:
        return 0
    return random.randint(0, config.jitter_ms)
