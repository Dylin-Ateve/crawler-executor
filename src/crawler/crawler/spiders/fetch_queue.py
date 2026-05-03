from __future__ import annotations

import asyncio
import signal
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import scrapy
from scrapy import signals as scrapy_signals

from crawler.egress_identity import (
    EgressIdentity,
    load_egress_identity_map,
    resolve_egress_identities,
    stable_hash,
)
from crawler.egress_policy import EgressPolicyError, build_sticky_pool_assignment, select_from_sticky_pool
from crawler.fetch_safety_state import EgressCooldownState, ExecutionStateKeyBuilder, FetchSafetyStateStore
from crawler.health import mark_worker_initialized, record_consumer_heartbeat
from crawler.ip_pool import discover_local_ips
from crawler.metrics import metrics
from crawler.policy_provider import build_runtime_policy_provider
from crawler.politeness import (
    HostIpPacerConfig,
    HostIpPacerState,
    mark_request_started,
    pacer_decision,
)
from crawler.queues import FetchCommand, RedisStreamsFetchConsumer
from crawler.runtime_policy import EffectivePolicy, EffectivePolicyDocument, PolicyDecision, decide_policy


RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504, 522, 524}


@dataclass(frozen=True)
class LocalDelayedFetchCommand:
    command: FetchCommand
    message_id: str
    eligible_at_ms: int
    read_at_ms: int
    delay_reason: str
    selected_identity_hash: str
    warning_logged: bool = False
    max_local_delay_seconds: Optional[int] = None


class LocalDelayedBuffer:
    def __init__(self, capacity: int) -> None:
        self.capacity = max(int(capacity), 0)
        self._items: list[LocalDelayedFetchCommand] = []

    def __len__(self) -> int:
        return len(self._items)

    @property
    def is_full(self) -> bool:
        return self.capacity > 0 and len(self._items) >= self.capacity

    def add(self, item: LocalDelayedFetchCommand) -> bool:
        if self.is_full:
            return False
        self._items.append(item)
        self._items.sort(key=lambda delayed: delayed.eligible_at_ms)
        return True

    def pop_due(self, now_ms: int) -> list[LocalDelayedFetchCommand]:
        due = [item for item in self._items if item.eligible_at_ms <= now_ms]
        if not due:
            return []
        due_ids = {(item.message_id, item.selected_identity_hash) for item in due}
        self._items = [
            item
            for item in self._items
            if (item.message_id, item.selected_identity_hash) not in due_ids
        ]
        return due

    def oldest_age_seconds(self, now_ms: int) -> float:
        if not self._items:
            return 0.0
        oldest = min(item.read_at_ms for item in self._items)
        return max((now_ms - oldest) / 1000.0, 0.0)

    def mark_warning_logged(self, message_id: str, identity_hash: str) -> None:
        self._items = [
            LocalDelayedFetchCommand(
                command=item.command,
                message_id=item.message_id,
                eligible_at_ms=item.eligible_at_ms,
                read_at_ms=item.read_at_ms,
                delay_reason=item.delay_reason,
                selected_identity_hash=item.selected_identity_hash,
                warning_logged=True,
                max_local_delay_seconds=item.max_local_delay_seconds,
            )
            if item.message_id == message_id and item.selected_identity_hash == identity_hash
            else item
            for item in self._items
        ]


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
        self.paused = False
        self.pause_file = ""
        self.pause_poll_seconds = 5
        self._pause_logged = False
        self._pause_file_error_logged = False
        # ADR-0009 优雅停机相关运行态。
        self.shutdown_drain_seconds = 25
        self._shutdown_started_at = None
        self._shutdown_summary_logged = False
        self.egress_selection_strategy = "STICKY_BY_HOST"
        self.egress_identities: tuple[EgressIdentity, ...] = ()
        self.sticky_pool_size = 4
        self.egress_hash_salt = ""
        self.pacer_config = HostIpPacerConfig()
        self.host_slowdown_factor = 1.0
        self.delayed_buffer = LocalDelayedBuffer(capacity=0)
        self.max_local_delay_seconds = 300
        self.local_delayed_buffer_poll_seconds = 0.5
        self.stop_reading_when_delayed_buffer_full = True
        self._pacer_states: dict[tuple[str, str], HostIpPacerState] = {}
        self.fetch_safety_store: Optional[FetchSafetyStateStore] = None
        self.policy_provider = None

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.consumer = RedisStreamsFetchConsumer.from_settings(crawler.settings)
        spider.default_max_messages = crawler.settings.getint("FETCH_QUEUE_MAX_MESSAGES", 0)
        spider.pause_poll_seconds = crawler.settings.getint("CRAWLER_PAUSE_POLL_SECONDS", 5)
        spider.paused = crawler.settings.getbool("CRAWLER_PAUSED", False)
        spider.pause_file = crawler.settings.get("CRAWLER_PAUSE_FILE", "") or ""
        spider.shutdown_drain_seconds = crawler.settings.getint(
            "FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS", 25
        )
        spider._configure_m3a(crawler.settings)
        spider.policy_provider = build_runtime_policy_provider(crawler.settings)
        spider._install_signal_handlers()
        # M4：尽早通过 signal handler 设置 shutdown flag；Scrapy 自身信号仍作为
        # 兜底入口和退出总结。
        crawler.signals.connect(
            spider._on_spider_closed, signal=scrapy_signals.spider_closed
        )
        crawler.signals.connect(
            spider._on_engine_stopped, signal=scrapy_signals.engine_stopped
        )
        return spider

    def _install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                previous = signal.getsignal(sig)

                def handler(signum, frame, previous_handler=previous):
                    self._request_shutdown(f"signal:{signum}")
                    if callable(previous_handler):
                        previous_handler(signum, frame)

                signal.signal(sig, handler)
            except Exception:
                self.logger.debug("fetch_queue_signal_handler_install_failed signal=%s", sig, exc_info=True)

    def _on_spider_closed(self, spider, reason):
        if spider is not self:
            return
        self._request_shutdown(str(reason))

    def _request_shutdown(self, reason: str) -> None:
        if self.consumer.is_shutting_down:
            return
        self._shutdown_started_at = time.monotonic()
        self.consumer.request_shutdown()
        metrics.record_fetch_queue_event("shutdown")
        metrics.record_shutdown_event("requested")
        self.logger.info(
            "fetch_queue_shutdown_signal_received reason=%s seen_messages=%s acked_count=%s drain_seconds=%s",
            reason,
            self.seen_messages,
            self.consumer.acked_count,
            self.shutdown_drain_seconds,
        )

    def _on_engine_stopped(self):
        if self._shutdown_summary_logged:
            return
        if not self.consumer.is_shutting_down:
            return
        if self._shutdown_started_at is None:
            elapsed = 0.0
        else:
            elapsed = time.monotonic() - self._shutdown_started_at
        drain_timeout = elapsed > self.shutdown_drain_seconds
        in_flight_estimate = max(self.seen_messages - self.consumer.acked_count, 0)
        metrics.set_shutdown_in_flight(in_flight_estimate)
        metrics.record_shutdown_event("drain_timeout" if drain_timeout else "drain_completed")
        self.logger.info(
            "fetch_queue_shutdown_loop_exit elapsed_seconds=%.3f drain_timeout=%s seen_messages=%s acked_count=%s in_flight_estimate=%s",
            elapsed,
            "true" if drain_timeout else "false",
            self.seen_messages,
            self.consumer.acked_count,
            in_flight_estimate,
        )
        self._shutdown_summary_logged = True

    async def start(self):
        await asyncio.to_thread(self.consumer.ensure_group)
        self._record_consumer_heartbeat()
        mark_worker_initialized()
        max_messages = self.max_messages or self.default_max_messages
        while True:
            self._record_consumer_heartbeat()
            if self.consumer.is_shutting_down:
                return
            if self._is_paused():
                if not self._pause_logged:
                    self.logger.info(
                        "fetch_queue_paused stream=%s group=%s",
                        self.consumer.stream,
                        self.consumer.group,
                    )
                    self._pause_logged = True
                metrics.record_fetch_queue_event("paused")
                await asyncio.sleep(self.pause_poll_seconds)
                continue
            self._pause_logged = False
            if max_messages and self.seen_messages >= max_messages:
                return
            async for delayed_request in self._drain_due_delayed_requests():
                yield delayed_request
                if max_messages and self.seen_messages >= max_messages:
                    return
            self._log_expired_delayed_commands()
            if (
                self.stop_reading_when_delayed_buffer_full
                and self.delayed_buffer.is_full
            ):
                metrics.record_fetch_queue_event("xreadgroup_suppressed_delayed_buffer_full")
                metrics.record_xreadgroup_suppressed("delayed_buffer_full")
                self._record_delayed_buffer_metrics()
                await asyncio.sleep(self.local_delayed_buffer_poll_seconds)
                continue
            entries = await asyncio.to_thread(self.consumer.read)
            if not entries:
                if self.consumer.is_shutting_down:
                    return
                metrics.record_fetch_queue_event("empty")
                if max_messages and not len(self.delayed_buffer):
                    return
                if len(self.delayed_buffer):
                    await asyncio.sleep(self.local_delayed_buffer_poll_seconds)
                continue
            for entry in entries:
                self._record_consumer_heartbeat()
                if self.consumer.is_shutting_down:
                    return
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
                request = self._build_or_delay_request(entry.command, entry.message_id)
                if request is not None:
                    yield request

    def _build_request(
        self,
        command: FetchCommand,
        message_id: str,
        *,
        egress_identity: Optional[EgressIdentity] = None,
        host: Optional[str] = None,
        policy_decision: Optional[PolicyDecision] = None,
    ) -> scrapy.Request:
        policy_decision = policy_decision or self._policy_decision(command)
        attempted_at = datetime.now(timezone.utc)
        meta = command.to_request_meta()
        meta.update(
            {
                "attempted_at_dt": attempted_at,
                "stream_message_id": message_id,
                "fetch_queue_consumer": self.consumer,
                "handle_httpstatus_all": True,
                "effective_max_retries": self._effective_max_retries(command, policy_decision),
                "policy_version": policy_decision.policy_version,
                "matched_policy_scope_type": policy_decision.matched_scope_type,
                "matched_policy_scope_id": policy_decision.matched_scope_id,
                "policy_lkg_active": policy_decision.lkg_active,
            }
        )
        if policy_decision.policy.download_timeout_seconds is not None:
            meta["download_timeout"] = policy_decision.policy.download_timeout_seconds
        if egress_identity is not None and host:
            meta.update(
                {
                    "egress_bind_ip": egress_identity.bind_ip,
                    "egress_local_ip": egress_identity.bind_ip,
                    "egress_identity": egress_identity.identity,
                    "egress_identity_hash": egress_identity.identity_hash,
                    "egress_identity_type": egress_identity.identity_type,
                    "egress_host": host,
                    "download_slot": f"{host}@{egress_identity.identity}",
                }
            )
        return scrapy.Request(
            url=command.url,
            callback=self.parse,
            errback=self.errback,
            dont_filter=True,
            meta=meta,
        )

    def _configure_m3a(self, settings) -> None:
        self.egress_selection_strategy = (
            settings.get("EGRESS_SELECTION_STRATEGY")
            or settings.get("IP_SELECTION_STRATEGY", "STICKY_BY_HOST")
        ).upper()
        self.sticky_pool_size = settings.getint("STICKY_POOL_SIZE", 4)
        self.egress_hash_salt = settings.get("EGRESS_IDENTITY_HASH_SALT", "") or ""
        self.pacer_config = HostIpPacerConfig(
            min_delay_ms=settings.getint("HOST_IP_MIN_DELAY_MS", 2000),
            jitter_ms=settings.getint("HOST_IP_JITTER_MS", 500),
            backoff_base_ms=settings.getint("HOST_IP_BACKOFF_BASE_MS", 5000),
            backoff_max_ms=settings.getint("HOST_IP_BACKOFF_MAX_MS", 300000),
            backoff_multiplier=float(settings.get("HOST_IP_BACKOFF_MULTIPLIER", 2.0)),
        )
        self.host_slowdown_factor = float(settings.get("HOST_SLOWDOWN_FACTOR", 1.0))
        self.delayed_buffer = LocalDelayedBuffer(settings.getint("LOCAL_DELAYED_BUFFER_CAPACITY", 100))
        self.max_local_delay_seconds = settings.getint("MAX_LOCAL_DELAY_SECONDS", 300)
        self.local_delayed_buffer_poll_seconds = settings.getint("LOCAL_DELAYED_BUFFER_POLL_MS", 500) / 1000.0
        self.stop_reading_when_delayed_buffer_full = settings.getbool(
            "STOP_READING_WHEN_DELAYED_BUFFER_FULL", True
        )

        if self.egress_selection_strategy != "STICKY_POOL":
            return

        interface = settings.get("CRAWL_INTERFACE", "ens3")
        excluded = settings.getlist("EXCLUDED_LOCAL_IPS", [])
        bind_ips = settings.getlist("LOCAL_IP_POOL") or discover_local_ips(interface, excluded)
        identity_map = load_egress_identity_map(settings.get("EGRESS_IDENTITY_MAP_FILE", "") or "")
        self.egress_identities = resolve_egress_identities(
            bind_ips,
            identity_map=identity_map,
            identity_source=settings.get("EGRESS_IDENTITY_SOURCE", "auto"),
            allow_bind_ip=settings.getbool("ALLOW_BIND_IP_AS_EGRESS_IDENTITY", True),
            hash_salt=self.egress_hash_salt,
            interface=interface,
        )
        self.fetch_safety_store = self._build_fetch_safety_store(settings)

    async def _drain_due_delayed_requests(self):
        while True:
            if self.consumer.is_shutting_down:
                return
            due_items = self.delayed_buffer.pop_due(self._now_ms())
            if not due_items:
                return
            for delayed in due_items:
                request = self._build_or_delay_request(
                    delayed.command,
                    delayed.message_id,
                    read_at_ms=delayed.read_at_ms,
                    warning_logged=delayed.warning_logged,
                )
                if request is not None:
                    yield request

    def _build_or_delay_request(
        self,
        command: FetchCommand,
        message_id: str,
        *,
        read_at_ms: Optional[int] = None,
        warning_logged: bool = False,
    ):
        policy_decision = self._policy_decision(command)
        if policy_decision.policy.is_paused:
            metrics.record_fetch_paused(
                policy_decision.matched_scope_type,
                policy_decision.policy.pause_reason or "paused",
            )
            return self._terminal_skip_item(
                command,
                message_id,
                error_type="paused",
                error_message=policy_decision.policy.pause_reason or "Fetch command paused before request start",
                policy_decision=policy_decision,
            )
        if self._deadline_expired(command):
            metrics.record_fetch_deadline_expired(policy_decision.matched_scope_type)
            return self._terminal_skip_item(
                command,
                message_id,
                error_type="deadline_expired",
                error_message="Fetch command deadline expired before request start",
                policy_decision=policy_decision,
            )

        egress_selection_strategy = policy_decision.policy.egress_selection_strategy or self.egress_selection_strategy
        if egress_selection_strategy != "STICKY_POOL":
            return self._build_request(command, message_id, policy_decision=policy_decision)

        now_ms = self._now_ms()
        read_at = read_at_ms if read_at_ms is not None else now_ms
        host = self._command_host(command)
        sticky_pool_size = policy_decision.policy.sticky_pool_size or self.sticky_pool_size
        assignment = build_sticky_pool_assignment(
            host,
            self.egress_identities,
            pool_size=sticky_pool_size,
            hash_salt=self.egress_hash_salt,
            now_ms=now_ms,
        )
        metrics.record_sticky_pool_assignment("sticky_pool")
        host_hash = stable_hash(host, salt=self.egress_hash_salt)
        host_slowdown_factor = self._host_slowdown_factor(host_hash, now_ms)
        cooldowns = self._candidate_cooldowns(assignment.candidate_identities, now_ms)
        try:
            identity = select_from_sticky_pool(
                assignment,
                is_in_cooldown=lambda selected_identity: selected_identity.identity_hash in cooldowns,
                is_backed_off=lambda selected_host, selected_identity: not pacer_decision(
                    self._host_ip_pacer_state(
                        stable_hash(selected_host, salt=self.egress_hash_salt),
                        selected_identity.identity_hash,
                    ),
                    now_ms,
                ).eligible,
            )
        except EgressPolicyError:
            eligible_at_ms = min(
                (cooldown.cooldown_until_ms for cooldown in cooldowns.values()),
                default=now_ms + self.pacer_config.min_delay_ms,
            )
            self._delay_command(
                command,
                message_id,
                eligible_at_ms=max(eligible_at_ms, now_ms + 1),
                read_at_ms=read_at,
                delay_reason="ip_cooldown",
                selected_identity_hash="all_candidates",
                warning_logged=warning_logged,
                host_hash=host_hash,
                max_local_delay_seconds=policy_decision.policy.max_local_delay_seconds,
            )
            return None
        pacer_key = (host_hash, identity.identity_hash)
        state = self._host_ip_pacer_state(host_hash, identity.identity_hash)
        decision = pacer_decision(state, now_ms)
        if not decision.eligible:
            metrics.observe_pacer_delay(
                "host_ip_pacer",
                decision.delay_ms / 1000.0,
                host_hash=host_hash,
                egress_identity_hash=identity.identity_hash,
            )
            self._delay_command(
                command,
                message_id,
                eligible_at_ms=decision.next_allowed_at_ms,
                read_at_ms=read_at,
                delay_reason="host_ip_pacer",
                selected_identity_hash=identity.identity_hash,
                warning_logged=warning_logged,
                host_hash=host_hash,
                max_local_delay_seconds=policy_decision.policy.max_local_delay_seconds,
            )
            return None

        self._pacer_states[pacer_key] = mark_request_started(
            state,
            self._policy_pacer_config(policy_decision),
            now_ms,
            host_slowdown_factor=host_slowdown_factor,
        )
        metrics.record_egress_identity_selected("sticky_pool", identity.identity_type)
        metrics.observe_sticky_pool_candidate_count("sticky_pool", assignment.pool_size_actual)
        self._record_delayed_buffer_metrics()
        return self._build_request(
            command,
            message_id,
            egress_identity=identity,
            host=host,
            policy_decision=policy_decision,
        )

    def _policy_decision(self, command: FetchCommand) -> PolicyDecision:
        if self.policy_provider:
            snapshot = self.policy_provider.current()
            document = snapshot.document
            lkg_active = snapshot.lkg_active
        else:
            document = EffectivePolicyDocument(
                schema_version="1.0",
                version="bootstrap-spider",
                generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                default_policy=EffectivePolicy(
                    egress_selection_strategy=self.egress_selection_strategy,
                    sticky_pool_size=self.sticky_pool_size,
                    host_ip_min_delay_ms=self.pacer_config.min_delay_ms,
                    host_ip_jitter_ms=self.pacer_config.jitter_ms,
                    max_retries=max(int(getattr(self.consumer, "max_deliveries", 3)) - 1, 0),
                    max_local_delay_seconds=self.max_local_delay_seconds,
                ),
            )
            lkg_active = False
        decision = decide_policy(document, command.to_request_meta(), lkg_active=lkg_active)
        metrics.record_policy_decision(decision.matched_scope_type)
        return decision

    def _policy_pacer_config(self, decision: PolicyDecision) -> HostIpPacerConfig:
        return replace(
            self.pacer_config,
            min_delay_ms=decision.policy.host_ip_min_delay_ms
            if decision.policy.host_ip_min_delay_ms is not None
            else self.pacer_config.min_delay_ms,
            jitter_ms=decision.policy.host_ip_jitter_ms
            if decision.policy.host_ip_jitter_ms is not None
            else self.pacer_config.jitter_ms,
        )

    def _effective_max_retries(self, command: FetchCommand, decision: PolicyDecision) -> int:
        if command.max_retries is not None:
            return command.max_retries
        if decision.policy.max_retries is not None:
            return decision.policy.max_retries
        return max(int(getattr(self.consumer, "max_deliveries", 3)) - 1, 0)

    @staticmethod
    def _deadline_expired(command: FetchCommand) -> bool:
        if not command.deadline_at:
            return False
        normalized = command.deadline_at[:-1] + "+00:00" if command.deadline_at.endswith("Z") else command.deadline_at
        deadline = datetime.fromisoformat(normalized)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= deadline.astimezone(timezone.utc)

    def _terminal_skip_item(
        self,
        command: FetchCommand,
        message_id: str,
        *,
        error_type: str,
        error_message: str,
        policy_decision: PolicyDecision,
    ):
        now = datetime.now(timezone.utc)
        return {
            "p1_candidate": True,
            "fetch_failed": True,
            "url": command.url,
            "canonical_url": command.canonical_url,
            "url_hash": command.url_hash,
            "status_code": None,
            "content_type": None,
            "response_headers": {},
            "body": b"",
            "outlinks": [],
            "error_type": error_type,
            "error_message": error_message,
            "egress_local_ip": None,
            "observed_egress_ip": None,
            "attempt_id": command.attempt_id,
            "attempted_at_dt": now,
            "fetched_at_dt": now,
            "command_id": command.command_id,
            "job_id": command.job_id,
            "trace_id": command.trace_id,
            "host_id": command.host_id,
            "site_id": command.site_id,
            "tier": command.tier,
            "politeness_key": command.politeness_key,
            "policy_scope_id": command.policy_scope_id,
            "policy_version": policy_decision.policy_version,
            "matched_policy_scope_type": policy_decision.matched_scope_type,
            "matched_policy_scope_id": policy_decision.matched_scope_id,
            "policy_lkg_active": policy_decision.lkg_active,
            "stream_message_id": message_id,
            "fetch_queue_consumer": self.consumer,
        }

    def _log_expired_delayed_commands(self) -> None:
        if not len(self.delayed_buffer):
            return
        now_ms = self._now_ms()
        for delayed in list(self.delayed_buffer._items):
            age_seconds = (now_ms - delayed.read_at_ms) / 1000.0
            max_delay_seconds = delayed.max_local_delay_seconds
            if max_delay_seconds is None:
                max_delay_seconds = self.max_local_delay_seconds
            if age_seconds < max_delay_seconds or delayed.warning_logged:
                continue
            metrics.record_fetch_queue_event("max_local_delay_exceeded")
            metrics.record_delayed_message_expired(delayed.delay_reason)
            self.logger.warning(
                "fetch_queue_max_local_delay_exceeded message_id=%s delay_reason=%s age_seconds=%.3f",
                delayed.message_id,
                delayed.delay_reason,
                age_seconds,
            )
            self.delayed_buffer.mark_warning_logged(delayed.message_id, delayed.selected_identity_hash)
        self._record_delayed_buffer_metrics()

    def _record_delayed_buffer_metrics(self) -> None:
        now_ms = self._now_ms()
        metrics.set_delayed_buffer_state(
            len(self.delayed_buffer),
            self.delayed_buffer.oldest_age_seconds(now_ms),
            self._consumer_metric_label(),
        )

    def _host_ip_pacer_state(self, host_hash: str, identity_hash: str) -> HostIpPacerState:
        local = self._pacer_states.get((host_hash, identity_hash), HostIpPacerState())
        if not self.fetch_safety_store:
            return local
        remote = self.fetch_safety_store.get_host_ip_backoff(host_hash, identity_hash)
        if remote is None:
            return local
        if remote.next_allowed_at_ms > local.next_allowed_at_ms:
            return remote
        return local

    def _candidate_cooldowns(
        self,
        identities: tuple[EgressIdentity, ...],
        now_ms: int,
    ) -> dict[str, EgressCooldownState]:
        return {
            identity.identity_hash: cooldown
            for identity in identities
            for cooldown in (self._identity_cooldown(identity.identity_hash, now_ms),)
            if cooldown is not None
        }

    def _identity_cooldown(self, identity_hash: str, now_ms: int) -> Optional[EgressCooldownState]:
        if not self.fetch_safety_store:
            return None
        cooldown = self.fetch_safety_store.get_ip_cooldown(identity_hash)
        if cooldown is None or cooldown.cooldown_until_ms <= now_ms:
            return None
        metrics.record_egress_identity_unavailable("ip_cooldown")
        metrics.set_ip_cooldown_active(cooldown.reason or "unknown", True)
        return cooldown

    def _host_slowdown_factor(self, host_hash: str, now_ms: int) -> float:
        if not self.fetch_safety_store:
            return self.host_slowdown_factor
        slowdown = self.fetch_safety_store.get_host_slowdown(host_hash)
        if slowdown is None or slowdown.slowdown_until_ms <= now_ms:
            return self.host_slowdown_factor
        metrics.set_host_slowdown_active(slowdown.reason or "unknown", True)
        return max(float(slowdown.slowdown_factor), self.host_slowdown_factor)

    def _consumer_metric_label(self) -> str:
        return getattr(self.consumer, "consumer", None) or getattr(self.consumer, "consumer_name", None) or "unknown"

    def _delay_command(
        self,
        command: FetchCommand,
        message_id: str,
        *,
        eligible_at_ms: int,
        read_at_ms: int,
        delay_reason: str,
        selected_identity_hash: str,
        warning_logged: bool,
        host_hash: str,
        max_local_delay_seconds: Optional[int] = None,
    ) -> None:
        delayed = LocalDelayedFetchCommand(
            command=command,
            message_id=message_id,
            eligible_at_ms=eligible_at_ms,
            read_at_ms=read_at_ms,
            delay_reason=delay_reason,
            selected_identity_hash=selected_identity_hash,
            warning_logged=warning_logged,
            max_local_delay_seconds=max_local_delay_seconds,
        )
        if self.delayed_buffer.add(delayed):
            metrics.record_fetch_queue_event("delayed")
            return
        metrics.record_fetch_queue_event("delayed_buffer_full")
        metrics.record_delayed_buffer_full(self._consumer_metric_label())
        self.logger.warning(
            "fetch_queue_delayed_buffer_full message_id=%s host_hash=%s egress_identity_hash=%s delay_reason=%s",
            message_id,
            host_hash,
            selected_identity_hash,
            delay_reason,
        )

    @staticmethod
    def _build_fetch_safety_store(settings) -> Optional[FetchSafetyStateStore]:
        redis_url = settings.get("EXECUTION_STATE_REDIS_URL") or settings.get("REDIS_URL")
        if not redis_url:
            return None
        try:
            import redis
        except ImportError:
            return None
        redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
        return FetchSafetyStateStore(
            redis_client,
            key_builder=ExecutionStateKeyBuilder(settings.get("EXECUTION_STATE_REDIS_PREFIX", "crawler:exec:safety")),
            max_ttl_seconds=settings.getint("EXECUTION_STATE_MAX_TTL_SECONDS", 86400),
            write_enabled=settings.getbool("EXECUTION_STATE_WRITE_ENABLED", True),
            fail_open=settings.getbool("EXECUTION_STATE_FAIL_OPEN", True),
        )

    @staticmethod
    def _command_host(command: FetchCommand) -> str:
        return (urlsplit(command.canonical_url).hostname or urlsplit(command.url).hostname or "").lower()

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _record_consumer_heartbeat() -> None:
        timestamp = time.time()
        record_consumer_heartbeat(now=timestamp)
        metrics.set_fetch_queue_consumer_heartbeat(timestamp)

    def _is_paused(self) -> bool:
        if not self.pause_file:
            return self.paused
        try:
            value = Path(self.pause_file).read_text(encoding="utf-8").strip().lower()
        except OSError as exc:
            if not self._pause_file_error_logged:
                self.logger.warning(
                    "fetch_queue_pause_file_read_failed path=%s error=%s",
                    self.pause_file,
                    exc,
                )
                self._pause_file_error_logged = True
            return self.paused
        self._pause_file_error_logged = False
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off", ""}:
            return False
        return self.paused

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
            metrics.record_fetch_retry_terminal("retry_exhausted")
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
            "tier": response.meta.get("tier"),
            "politeness_key": response.meta.get("politeness_key"),
            "policy_scope_id": response.meta.get("policy_scope_id"),
            "policy_version": response.meta.get("policy_version"),
            "matched_policy_scope_type": response.meta.get("matched_policy_scope_type"),
            "matched_policy_scope_id": response.meta.get("matched_policy_scope_id"),
            "policy_lkg_active": response.meta.get("policy_lkg_active"),
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
            error_type="retry_exhausted" if self._delivery_count(request.meta) > self._max_retries(request.meta) else error_type,
            error_message=error_message,
        )
        if item["error_type"] == "retry_exhausted":
            metrics.record_fetch_retry_terminal("retry_exhausted")
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
            "tier": request.meta.get("tier"),
            "politeness_key": request.meta.get("politeness_key"),
            "policy_scope_id": request.meta.get("policy_scope_id"),
            "policy_version": request.meta.get("policy_version"),
            "matched_policy_scope_type": request.meta.get("matched_policy_scope_type"),
            "matched_policy_scope_id": request.meta.get("matched_policy_scope_id"),
            "policy_lkg_active": request.meta.get("policy_lkg_active"),
            "stream_message_id": request.meta.get("stream_message_id"),
            "fetch_queue_consumer": request.meta.get("fetch_queue_consumer"),
        }
        return item

    def _should_retry_response(self, response) -> bool:
        return response.status in RETRYABLE_HTTP_STATUS_CODES and self._should_retry_request(response.request)

    def _should_retry_request(self, request) -> bool:
        return self._delivery_count(request.meta) <= self._max_retries(request.meta)

    @staticmethod
    def _delivery_count(meta) -> int:
        try:
            return int(meta.get("stream_deliveries") or 1)
        except (TypeError, ValueError):
            return 1

    def _max_retries(self, meta) -> int:
        try:
            return max(int(meta.get("effective_max_retries")), 0)
        except (TypeError, ValueError):
            return max(int(getattr(self.consumer, "max_deliveries", 3)) - 1, 0)

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
