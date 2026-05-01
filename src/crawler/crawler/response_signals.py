from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from crawler.egress_identity import stable_hash


SIGNAL_SUCCESS = "success"
SIGNAL_HTTP_429 = "http_429"
SIGNAL_CAPTCHA_CHALLENGE = "captcha_challenge"
SIGNAL_ANTI_BOT_200 = "anti_bot_200"
SIGNAL_TIMEOUT = "timeout"
SIGNAL_CONNECTION_FAILED = "connection_failed"
SIGNAL_HTTP_5XX = "http_5xx"


@dataclass(frozen=True)
class BodyPattern:
    pattern_id: str
    pattern: str


@dataclass(frozen=True)
class FeedbackWeights:
    http_429: int = 3
    captcha_challenge: int = 5
    anti_bot_200: int = 4
    http_5xx: int = 1
    timeout: int = 1
    connection_failed: int = 1


@dataclass(frozen=True)
class FeedbackSignal:
    signal_type: str
    host: str
    host_hash: str
    identity_hash: str
    status_code: Optional[int]
    matched_pattern: Optional[str]
    weight: int
    observed_at_ms: int
    attempt_id: Optional[str] = None


def classify_response_signal(
    *,
    host: str,
    identity_hash: str,
    status_code: int,
    body: bytes = b"",
    challenge_patterns: Sequence[BodyPattern] = (),
    anti_bot_200_patterns: Sequence[BodyPattern] = (),
    weights: FeedbackWeights = FeedbackWeights(),
    hash_salt: str = "",
    observed_at_ms: Optional[int] = None,
    attempt_id: Optional[str] = None,
) -> FeedbackSignal:
    observed_at = observed_at_ms if observed_at_ms is not None else int(time.time() * 1000)
    normalized_host = host.strip().lower()

    if status_code == 429:
        return _signal(SIGNAL_HTTP_429, normalized_host, identity_hash, status_code, None, weights.http_429, observed_at, hash_salt, attempt_id)

    matched_challenge = _match_pattern(body, challenge_patterns)
    if matched_challenge:
        return _signal(SIGNAL_CAPTCHA_CHALLENGE, normalized_host, identity_hash, status_code, matched_challenge, weights.captcha_challenge, observed_at, hash_salt, attempt_id)

    if status_code == 200:
        matched_anti_bot = _match_pattern(body, anti_bot_200_patterns)
        if matched_anti_bot:
            return _signal(SIGNAL_ANTI_BOT_200, normalized_host, identity_hash, status_code, matched_anti_bot, weights.anti_bot_200, observed_at, hash_salt, attempt_id)

    if 500 <= status_code <= 599:
        return _signal(SIGNAL_HTTP_5XX, normalized_host, identity_hash, status_code, None, weights.http_5xx, observed_at, hash_salt, attempt_id)

    return _signal(SIGNAL_SUCCESS, normalized_host, identity_hash, status_code, None, 0, observed_at, hash_salt, attempt_id)


def classify_exception_signal(
    *,
    host: str,
    identity_hash: str,
    exception: BaseException,
    weights: FeedbackWeights = FeedbackWeights(),
    hash_salt: str = "",
    observed_at_ms: Optional[int] = None,
    attempt_id: Optional[str] = None,
) -> FeedbackSignal:
    observed_at = observed_at_ms if observed_at_ms is not None else int(time.time() * 1000)
    normalized_host = host.strip().lower()
    signal_type = SIGNAL_TIMEOUT if _is_timeout(exception) else SIGNAL_CONNECTION_FAILED
    weight = weights.timeout if signal_type == SIGNAL_TIMEOUT else weights.connection_failed
    return _signal(signal_type, normalized_host, identity_hash, None, None, weight, observed_at, hash_salt, attempt_id)


def parse_body_patterns(raw: str) -> tuple[BodyPattern, ...]:
    patterns = []
    for item in (part.strip() for part in raw.split(",") if part.strip()):
        if ":" in item:
            pattern_id, pattern = item.split(":", 1)
        else:
            pattern_id, pattern = item, item
        patterns.append(BodyPattern(pattern_id=pattern_id.strip(), pattern=pattern.strip()))
    return tuple(patterns)


def _signal(
    signal_type: str,
    host: str,
    identity_hash: str,
    status_code: Optional[int],
    matched_pattern: Optional[str],
    weight: int,
    observed_at_ms: int,
    hash_salt: str,
    attempt_id: Optional[str],
) -> FeedbackSignal:
    return FeedbackSignal(
        signal_type=signal_type,
        host=host,
        host_hash=stable_hash(host, salt=hash_salt),
        identity_hash=identity_hash,
        status_code=status_code,
        matched_pattern=matched_pattern,
        weight=weight,
        observed_at_ms=observed_at_ms,
        attempt_id=attempt_id,
    )


def _match_pattern(body: bytes, patterns: Iterable[BodyPattern]) -> Optional[str]:
    if not body:
        return None
    text = body.decode("utf-8", errors="ignore")
    for pattern in patterns:
        if re.search(pattern.pattern, text, flags=re.IGNORECASE):
            return pattern.pattern_id
    return None


def _is_timeout(exception: BaseException) -> bool:
    name = exception.__class__.__name__.lower()
    text = str(exception).lower()
    return "timeout" in name or "timed out" in text or "timeout" in text
