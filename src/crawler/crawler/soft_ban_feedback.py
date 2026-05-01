from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from crawler.fetch_safety_state import FetchSafetyStateStore
from crawler.metrics import metrics
from crawler.politeness import HostIpPacerConfig, HostIpPacerState, mark_backoff
from crawler.response_signals import (
    FeedbackSignal,
    SIGNAL_ANTI_BOT_200,
    SIGNAL_CAPTCHA_CHALLENGE,
    SIGNAL_HTTP_429,
)


HOST_IP_BACKOFF_SIGNALS = {SIGNAL_HTTP_429, SIGNAL_CAPTCHA_CHALLENGE, SIGNAL_ANTI_BOT_200}
CROSS_DIMENSION_CHALLENGE_SIGNALS = {SIGNAL_CAPTCHA_CHALLENGE, SIGNAL_ANTI_BOT_200}


@dataclass(frozen=True)
class SoftBanFeedbackConfig:
    soft_ban_window_seconds: int = 300
    host_ip_soft_ban_threshold: int = 2
    ip_cross_host_challenge_threshold: int = 3
    host_cross_ip_challenge_threshold: int = 3
    host_ip_backoff_ttl_seconds: int = 86400
    ip_cooldown_seconds: int = 1800
    host_slowdown_seconds: int = 600
    host_slowdown_factor: float = 3.0
    host_asn_soft_limit_enabled: bool = False
    host_asn_soft_limit_seconds: int = 600
    host_asn_soft_limit_factor: float = 3.0


@dataclass(frozen=True)
class SoftBanFeedbackResult:
    host_ip_backoff: bool = False
    ip_cooldown: bool = False
    host_slowdown: bool = False
    host_asn_soft_limit: bool = False


class SoftBanFeedbackController:
    def __init__(
        self,
        store: FetchSafetyStateStore,
        *,
        config: SoftBanFeedbackConfig = SoftBanFeedbackConfig(),
        pacer_config: HostIpPacerConfig = HostIpPacerConfig(),
    ) -> None:
        self.store = store
        self.config = config
        self.pacer_config = pacer_config

    def record_signal(
        self,
        signal: FeedbackSignal,
        *,
        asn: Optional[str] = None,
        cidr: Optional[str] = None,
        now_ms: Optional[int] = None,
    ) -> SoftBanFeedbackResult:
        timestamp = now_ms if now_ms is not None else int(time.time() * 1000)
        metrics.record_feedback_signal(signal.signal_type, "host_ip")
        host_ip_backoff = self._record_host_ip_signal(signal, timestamp)
        ip_cooldown = False
        host_slowdown = False
        host_asn_soft_limit = False

        if signal.signal_type in CROSS_DIMENSION_CHALLENGE_SIGNALS:
            ip_cooldown = self._record_ip_challenge(signal, timestamp)
            host_slowdown = self._record_host_challenge(signal, timestamp)
            if self.config.host_asn_soft_limit_enabled and asn:
                host_asn_soft_limit = self._record_host_asn_challenge(signal, asn, timestamp)

        return SoftBanFeedbackResult(
            host_ip_backoff=host_ip_backoff,
            ip_cooldown=ip_cooldown,
            host_slowdown=host_slowdown,
            host_asn_soft_limit=host_asn_soft_limit,
        )

    def _record_host_ip_signal(self, signal: FeedbackSignal, now_ms: int) -> bool:
        if signal.signal_type not in HOST_IP_BACKOFF_SIGNALS:
            return False
        dimension_hash = _combined_dimension_hash(signal.host_hash, signal.identity_hash)
        counter = self.store.increment_signal_window(
            dimension="host_ip",
            dimension_hash=dimension_hash,
            signal_type=signal.signal_type,
            weight=signal.weight,
            window_seconds=self.config.soft_ban_window_seconds,
        )
        if counter.count < self.config.host_ip_soft_ban_threshold:
            return False

        current = self.store.get_host_ip_backoff(signal.host_hash, signal.identity_hash) or HostIpPacerState()
        updated = mark_backoff(
            current,
            self.pacer_config,
            now_ms,
            signal_type=signal.signal_type,
            host_slowdown_factor=1.0,
        )
        self.store.set_host_ip_backoff(
            signal.host_hash,
            signal.identity_hash,
            updated,
            ttl_seconds=self.config.host_ip_backoff_ttl_seconds,
        )
        metrics.set_host_ip_backoff_active(signal.signal_type, True)
        metrics.observe_host_ip_backoff(
            signal.signal_type,
            max((updated.next_allowed_at_ms - now_ms) / 1000.0, 0.0),
        )
        return True

    def _record_ip_challenge(self, signal: FeedbackSignal, now_ms: int) -> bool:
        counter = self.store.increment_distinct_signal_window(
            dimension="ip",
            dimension_hash=signal.identity_hash,
            signal_type=signal.signal_type,
            member_hash=signal.host_hash,
            weight=signal.weight,
            window_seconds=self.config.soft_ban_window_seconds,
        )
        if counter.count < self.config.ip_cross_host_challenge_threshold:
            return False
        self.store.set_ip_cooldown(
            signal.identity_hash,
            cooldown_until_ms=now_ms + self.config.ip_cooldown_seconds * 1000,
            reason="cross_host_challenge",
            trigger_count=counter.count,
            now_ms=now_ms,
            ttl_seconds=self.config.ip_cooldown_seconds + self.config.soft_ban_window_seconds,
        )
        metrics.set_ip_cooldown_active("cross_host_challenge", True)
        metrics.record_ip_cooldown("cross_host_challenge")
        return True

    def _record_host_challenge(self, signal: FeedbackSignal, now_ms: int) -> bool:
        counter = self.store.increment_distinct_signal_window(
            dimension="host",
            dimension_hash=signal.host_hash,
            signal_type=signal.signal_type,
            member_hash=signal.identity_hash,
            weight=signal.weight,
            window_seconds=self.config.soft_ban_window_seconds,
        )
        if counter.count < self.config.host_cross_ip_challenge_threshold:
            return False
        self.store.set_host_slowdown(
            signal.host_hash,
            slowdown_until_ms=now_ms + self.config.host_slowdown_seconds * 1000,
            slowdown_factor=self.config.host_slowdown_factor,
            reason="multi_ip_challenge",
            now_ms=now_ms,
            ttl_seconds=self.config.host_slowdown_seconds + self.config.soft_ban_window_seconds,
        )
        metrics.set_host_slowdown_active("multi_ip_challenge", True)
        metrics.record_host_slowdown("multi_ip_challenge")
        return True

    def _record_host_asn_challenge(self, signal: FeedbackSignal, asn: str, now_ms: int) -> bool:
        dimension_hash = _combined_dimension_hash(signal.host_hash, asn)
        counter = self.store.increment_distinct_signal_window(
            dimension="host_asn",
            dimension_hash=dimension_hash,
            signal_type=signal.signal_type,
            member_hash=signal.identity_hash,
            weight=signal.weight,
            window_seconds=self.config.soft_ban_window_seconds,
        )
        if counter.count < self.config.host_cross_ip_challenge_threshold:
            return False
        self.store.set_host_asn_soft_limit(
            signal.host_hash,
            asn,
            limit_until_ms=now_ms + self.config.host_asn_soft_limit_seconds * 1000,
            limit_factor=self.config.host_asn_soft_limit_factor,
            reason="host_asn_challenge",
            now_ms=now_ms,
            ttl_seconds=self.config.host_asn_soft_limit_seconds + self.config.soft_ban_window_seconds,
        )
        metrics.record_host_asn_soft_limit("host_asn_challenge", asn=asn)
        return True


def _combined_dimension_hash(left: str, right: str) -> str:
    from crawler.egress_identity import stable_hash

    return stable_hash(f"{left}:{right}")
