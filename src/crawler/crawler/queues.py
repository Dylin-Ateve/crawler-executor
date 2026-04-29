from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional

from crawler.attempts import build_command_attempt_id
from crawler.contracts.canonical_url import CanonicalUrlError, canonical_url_hash, canonicalize_url


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
        deadline_at=_optional(decoded, "deadline_at"),
        max_retries=_optional_int(decoded, "max_retries"),
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
        claim_min_idle_ms: int = 60000,
    ) -> None:
        self.redis_client = redis_client
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.read_count = read_count
        self.block_ms = block_ms
        self.max_deliveries = max_deliveries
        self.claim_min_idle_ms = claim_min_idle_ms

    @classmethod
    def from_settings(cls, settings):
        import redis

        redis_url = settings.get("FETCH_QUEUE_REDIS_URL") or settings.get("REDIS_URL")
        if not redis_url:
            raise FetchCommandError("FETCH_QUEUE_REDIS_URL or REDIS_URL is required")
        return cls(
            redis.from_url(redis_url, decode_responses=False),
            stream=settings.get("FETCH_QUEUE_STREAM", "crawl:tasks"),
            group=settings.get("FETCH_QUEUE_GROUP", "crawler-executor"),
            consumer=settings.get("FETCH_QUEUE_CONSUMER") or socket.gethostname(),
            read_count=settings.getint("FETCH_QUEUE_READ_COUNT", 10),
            block_ms=settings.getint("FETCH_QUEUE_BLOCK_MS", 5000),
            max_deliveries=settings.getint("FETCH_QUEUE_MAX_DELIVERIES", 3),
            claim_min_idle_ms=settings.getint("FETCH_QUEUE_CLAIM_MIN_IDLE_MS", 60000),
        )

    def ensure_group(self) -> None:
        try:
            self.redis_client.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def read(self) -> List[StreamFetchCommand]:
        claimed = self.reclaim_pending()
        if claimed:
            return claimed
        response = self.redis_client.xreadgroup(
            self.group,
            self.consumer,
            {self.stream: ">"},
            count=self.read_count,
            block=self.block_ms,
        )
        return self._parse_response(response)

    def ack(self, message_id: str) -> None:
        self.redis_client.xack(self.stream, self.group, message_id)

    def reclaim_pending(self) -> List[StreamFetchCommand]:
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
            return []
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


def _required(fields: Mapping[str, str], key: str) -> str:
    value = fields.get(key, "").strip()
    if not value:
        raise FetchCommandError(f"{key} is required")
    return value


def _optional(fields: Mapping[str, str], key: str) -> Optional[str]:
    value = fields.get(key, "").strip()
    return value or None


def _optional_int(fields: Mapping[str, str], key: str) -> Optional[int]:
    value = _optional(fields, key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise FetchCommandError(f"{key} must be an integer") from exc
