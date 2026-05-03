from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Mapping, Optional

from crawler.attempts import build_command_attempt_id
from crawler.contracts.canonical_url import CanonicalUrlError, canonical_url_hash, canonicalize_url
from crawler.metrics import metrics


class FetchCommandError(ValueError):
    """Raised when a queue message cannot be converted into a fetch command."""


@dataclass(frozen=True)
class FetchCommand:
    url: str
    job_id: str
    canonical_url: str
    attempt_id: str
    url_hash: str
    command_id: Optional[str] = None
    trace_id: Optional[str] = None
    host_id: Optional[str] = None
    site_id: Optional[str] = None
    tier: Optional[str] = None
    politeness_key: Optional[str] = None
    policy_scope_id: Optional[str] = None
    deadline_at: Optional[str] = None
    max_retries: Optional[int] = None
    stream_id: Optional[str] = None
    deliveries: int = 1

    def to_request_meta(self) -> Dict[str, object]:
        return {
            "p1_candidate": True,
            "command_id": self.command_id,
            "job_id": self.job_id,
            "trace_id": self.trace_id,
            "host_id": self.host_id,
            "site_id": self.site_id,
            "tier": self.tier,
            "politeness_key": self.politeness_key,
            "policy_scope_id": self.policy_scope_id,
            "deadline_at": self.deadline_at,
            "max_retries": self.max_retries,
            "attempt_id": self.attempt_id,
            "canonical_url": self.canonical_url,
            "url_hash": self.url_hash,
            "stream_id": self.stream_id,
            "stream_deliveries": self.deliveries,
        }


@dataclass(frozen=True)
class StreamFetchCommand:
    stream: str
    message_id: str
    command: Optional[FetchCommand] = None
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.command is not None and self.error is None


def parse_fetch_command(fields: Mapping[object, object], *, stream_id: Optional[str] = None, deliveries: int = 1) -> FetchCommand:
    decoded = _decode_mapping(fields)
    if "payload" in decoded:
        try:
            payload = json.loads(decoded["payload"])
        except json.JSONDecodeError as exc:
            raise FetchCommandError(f"invalid payload json: {exc}") from exc
        if not isinstance(payload, dict):
            raise FetchCommandError("payload must be a JSON object")
        decoded = {str(key): "" if value is None else str(value) for key, value in payload.items()}

    url = _required(decoded, "url")
    job_id = _required(decoded, "job_id")
    canonical_url = _required(decoded, "canonical_url")
    try:
        canonical_url = canonicalize_url(canonical_url)
    except CanonicalUrlError as exc:
        raise FetchCommandError(f"invalid canonical_url: {exc}") from exc
    try:
        canonicalize_url(url)
    except CanonicalUrlError as exc:
        raise FetchCommandError(f"invalid url: {exc}") from exc

    return FetchCommand(
        url=url,
        job_id=job_id,
        canonical_url=canonical_url,
        attempt_id=build_command_attempt_id(job_id, canonical_url),
        url_hash=canonical_url_hash(canonical_url),
        command_id=_optional(decoded, "command_id"),
        trace_id=_optional(decoded, "trace_id"),
        host_id=_optional(decoded, "host_id"),
        site_id=_optional(decoded, "site_id"),
        tier=_optional(decoded, "tier"),
        politeness_key=_optional(decoded, "politeness_key"),
        policy_scope_id=_optional(decoded, "policy_scope_id"),
        deadline_at=_optional_datetime_text(decoded, "deadline_at"),
        max_retries=_optional_int(decoded, "max_retries", minimum=0, maximum=100),
        stream_id=stream_id,
        deliveries=deliveries,
    )


class RedisStreamsFetchConsumer:
    def __init__(
        self,
        redis_client,
        *,
        stream: str,
        group: str,
        consumer: str,
        read_count: int = 10,
        block_ms: int = 5000,
        max_deliveries: int = 3,
        claim_min_idle_ms: int = 600000,
    ) -> None:
        self.redis_client = redis_client
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.read_count = read_count
        self.block_ms = block_ms
        self.max_deliveries = max_deliveries
        self.claim_min_idle_ms = claim_min_idle_ms
        # ADR-0009：共享停机标志。优雅停机进入后 read() 不再发起 XREADGROUP，
        # reclaim_pending() 不再发起 XAUTOCLAIM；本进程 PEL 中的消息保留，
        # 由其它存活 worker 通过后续 XAUTOCLAIM 接管。
        self._shutdown = False
        # 用于退出前总结日志，配合 spider 计算 in-flight 估算值。
        self.acked_count = 0

    @classmethod
    def from_settings(cls, settings):
        import redis

        redis_url = settings.get("FETCH_QUEUE_REDIS_URL") or settings.get("REDIS_URL")
        if not redis_url:
            raise FetchCommandError("FETCH_QUEUE_REDIS_URL or REDIS_URL is required")
        return cls(
            redis.from_url(redis_url, decode_responses=False),
            stream=resolve_fetch_queue_stream(settings),
            group=resolve_fetch_queue_group(settings),
            consumer=resolve_fetch_queue_consumer(settings),
            read_count=settings.getint("FETCH_QUEUE_READ_COUNT", 10),
            block_ms=settings.getint("FETCH_QUEUE_BLOCK_MS", 5000),
            max_deliveries=settings.getint("FETCH_QUEUE_MAX_DELIVERIES", 3),
            claim_min_idle_ms=settings.getint("FETCH_QUEUE_CLAIM_MIN_IDLE_MS", 600000),
        )

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown

    def request_shutdown(self) -> None:
        """触发优雅停机。详见 ADR-0009：

        - 停止 XREADGROUP 与 XAUTOCLAIM。
        - 已经在 PEL 中的消息保持留存，由其它存活 worker 通过 XAUTOCLAIM 接管。
        - 不主动 ack 任何 in-flight 之外的消息。
        """
        self._shutdown = True

    def ensure_group(self) -> None:
        try:
            self.redis_client.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                metrics.record_dependency_health("redis", False)
                raise
        metrics.record_dependency_health("redis", True)

    def read(self) -> List[StreamFetchCommand]:
        if self._shutdown:
            return []
        claimed = self.reclaim_pending()
        if claimed:
            return claimed
        # 阻塞读之前再次检查停机标志：reclaim_pending() 期间可能进入停机态。
        if self._shutdown:
            return []
        try:
            response = self.redis_client.xreadgroup(
                self.group,
                self.consumer,
                {self.stream: ">"},
                count=self.read_count,
                block=self.block_ms,
            )
            metrics.record_dependency_health("redis", True)
        except Exception:
            metrics.record_dependency_health("redis", False)
            raise
        return self._parse_response(response)

    def ack(self, message_id: str) -> None:
        try:
            self.redis_client.xack(self.stream, self.group, message_id)
            metrics.record_dependency_health("redis", True)
        except Exception:
            metrics.record_dependency_health("redis", False)
            raise
        self.acked_count += 1

    def reclaim_pending(self) -> List[StreamFetchCommand]:
        if self._shutdown:
            return []
        try:
            response = self.redis_client.xautoclaim(
                self.stream,
                self.group,
                self.consumer,
                self.claim_min_idle_ms,
                "0-0",
                count=self.read_count,
            )
        except Exception:
            metrics.record_dependency_health("redis", False)
            return []
        metrics.record_dependency_health("redis", True)
        return self._parse_claim_response(response)

    def _parse_response(self, response: Iterable[object]) -> List[StreamFetchCommand]:
        commands: List[StreamFetchCommand] = []
        for stream_name, messages in response or []:
            stream = _decode_value(stream_name)
            for message_id, fields in messages:
                message_id_text = _decode_value(message_id)
                try:
                    command = parse_fetch_command(fields, stream_id=message_id_text)
                except FetchCommandError as exc:
                    commands.append(StreamFetchCommand(stream=stream, message_id=message_id_text, error=str(exc)))
                    continue
                commands.append(StreamFetchCommand(stream=stream, message_id=message_id_text, command=command))
        return commands

    def _parse_claim_response(self, response: object) -> List[StreamFetchCommand]:
        if not response:
            return []
        messages = response[1] if isinstance(response, (tuple, list)) and len(response) >= 2 else []
        commands: List[StreamFetchCommand] = []
        for message_id, fields in messages:
            message_id_text = _decode_value(message_id)
            try:
                command = parse_fetch_command(
                    fields,
                    stream_id=message_id_text,
                    deliveries=self.delivery_count(message_id_text),
                )
            except FetchCommandError as exc:
                commands.append(StreamFetchCommand(stream=self.stream, message_id=message_id_text, error=str(exc)))
                continue
            commands.append(StreamFetchCommand(stream=self.stream, message_id=message_id_text, command=command))
        return commands

    def delivery_count(self, message_id: str) -> int:
        try:
            pending = self.redis_client.xpending_range(self.stream, self.group, message_id, message_id, 1)
        except Exception:
            return self.max_deliveries
        if not pending:
            return self.max_deliveries
        entry = pending[0]
        if isinstance(entry, dict):
            value = entry.get("times_delivered") or entry.get(b"times_delivered") or entry.get("delivery_count")
            try:
                return int(value)
            except (TypeError, ValueError):
                return self.max_deliveries
        return self.max_deliveries


def _decode_mapping(fields: Mapping[object, object]) -> Dict[str, str]:
    return {_decode_value(key): _decode_value(value) for key, value in fields.items()}


def _decode_value(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def resolve_fetch_queue_consumer(settings, hostname_factory=socket.gethostname) -> str:
    explicit = (settings.get("FETCH_QUEUE_CONSUMER") or "").strip()
    if explicit:
        return explicit

    node_name = (settings.get("NODE_NAME") or "").strip()
    pod_name = (settings.get("POD_NAME") or "").strip()
    debug_mode = _settings_bool(settings, "CRAWLER_DEBUG_MODE", False)
    template_name = "DEBUG_FETCH_QUEUE_CONSUMER_TEMPLATE" if debug_mode else "FETCH_QUEUE_CONSUMER_TEMPLATE"
    template = (settings.get(template_name) or "").strip()

    if template and node_name and pod_name:
        rendered = render_runtime_template(template, node_name=node_name, pod_name=pod_name)
        if rendered:
            return rendered

    if node_name and pod_name:
        return f"{node_name}-{pod_name}"

    return hostname_factory()


def resolve_fetch_queue_stream(settings) -> str:
    if not _settings_bool(settings, "CRAWLER_DEBUG_MODE", False):
        return settings.get("FETCH_QUEUE_STREAM", "crawl:tasks")
    template = settings.get("DEBUG_FETCH_QUEUE_STREAM_TEMPLATE", "crawl:tasks:debug:{node_name}")
    return render_runtime_template(
        template,
        node_name=(settings.get("NODE_NAME") or "").strip(),
        pod_name=(settings.get("POD_NAME") or "").strip(),
    )


def resolve_fetch_queue_group(settings) -> str:
    if not _settings_bool(settings, "CRAWLER_DEBUG_MODE", False):
        return settings.get("FETCH_QUEUE_GROUP", "crawler-executor")
    template = settings.get("DEBUG_FETCH_QUEUE_GROUP_TEMPLATE", "crawler-executor-debug:{node_name}")
    return render_runtime_template(
        template,
        node_name=(settings.get("NODE_NAME") or "").strip(),
        pod_name=(settings.get("POD_NAME") or "").strip(),
    )


def render_runtime_template(template: str, *, node_name: str, pod_name: str) -> str:
    return (
        str(template)
        .replace("${NODE_NAME}", node_name)
        .replace("${POD_NAME}", pod_name)
        .replace("$(NODE_NAME)", node_name)
        .replace("$(POD_NAME)", pod_name)
        .replace("{NODE_NAME}", node_name)
        .replace("{POD_NAME}", pod_name)
        .replace("{node_name}", node_name)
        .replace("{pod_name}", pod_name)
    ).strip()


def _settings_bool(settings, name: str, default: bool) -> bool:
    if hasattr(settings, "getbool"):
        return settings.getbool(name, default)
    value = settings.get(name, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _required(fields: Mapping[str, str], key: str) -> str:
    value = fields.get(key, "").strip()
    if not value:
        raise FetchCommandError(f"{key} is required")
    return value


def _optional(fields: Mapping[str, str], key: str) -> Optional[str]:
    value = fields.get(key, "").strip()
    return value or None


def _optional_int(fields: Mapping[str, str], key: str, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> Optional[int]:
    value = _optional(fields, key)
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise FetchCommandError(f"{key} must be an integer") from exc
    if minimum is not None and parsed < minimum:
        raise FetchCommandError(f"{key} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise FetchCommandError(f"{key} must be <= {maximum}")
    return parsed


def _optional_datetime_text(fields: Mapping[str, str], key: str) -> Optional[str]:
    value = _optional(fields, key)
    if value is None:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise FetchCommandError(f"{key} must be an ISO-8601 timestamp") from exc
    return value
