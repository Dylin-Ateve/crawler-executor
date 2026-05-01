from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence

from crawler.egress_identity import EgressIdentity, stable_hash


class EgressPolicyError(ValueError):
    """Raised when sticky-pool selection has no usable candidate."""


@dataclass(frozen=True)
class StickyPoolAssignment:
    host: str
    host_hash: str
    pool_size_requested: int
    pool_size_actual: int
    candidate_identities: tuple[EgressIdentity, ...]
    candidate_identity_hashes: tuple[str, ...]
    selection_strategy: str
    generated_at_ms: int


def build_sticky_pool_assignment(
    host: str,
    identities: Iterable[EgressIdentity],
    *,
    pool_size: int,
    hash_salt: str = "",
    now_ms: Optional[int] = None,
) -> StickyPoolAssignment:
    normalized_host = _normalize_host(host)
    if pool_size <= 0:
        raise EgressPolicyError("pool_size must be positive")

    active = tuple(identity for identity in identities if identity.status == "active")
    if not active:
        raise EgressPolicyError("at least one active egress identity is required")

    ranked = sorted(
        active,
        key=lambda identity: _rendezvous_score(normalized_host, identity.identity, hash_salt),
        reverse=True,
    )
    candidates = tuple(ranked[: min(pool_size, len(ranked))])
    generated_at = now_ms if now_ms is not None else int(time.time() * 1000)
    return StickyPoolAssignment(
        host=normalized_host,
        host_hash=stable_hash(normalized_host, salt=hash_salt),
        pool_size_requested=pool_size,
        pool_size_actual=len(candidates),
        candidate_identities=candidates,
        candidate_identity_hashes=tuple(identity.identity_hash for identity in candidates),
        selection_strategy="sticky_pool",
        generated_at_ms=generated_at,
    )


def select_from_sticky_pool(
    assignment: StickyPoolAssignment,
    *,
    is_in_cooldown: Optional[Callable[[EgressIdentity], bool]] = None,
    is_backed_off: Optional[Callable[[str, EgressIdentity], bool]] = None,
) -> EgressIdentity:
    cooldown = is_in_cooldown or (lambda _identity: False)
    backed_off = is_backed_off or (lambda _host, _identity: False)

    fallback: Optional[EgressIdentity] = None
    for identity in assignment.candidate_identities:
        if cooldown(identity):
            continue
        if backed_off(assignment.host, identity):
            fallback = fallback or identity
            continue
        return identity
    if fallback:
        return fallback
    raise EgressPolicyError(f"no eligible egress identity for host: {assignment.host}")


def _normalize_host(host: str) -> str:
    normalized = host.strip().lower()
    if not normalized:
        raise EgressPolicyError("host is required")
    return normalized


def _rendezvous_score(host: str, identity: str, salt: str) -> int:
    payload = f"{salt}:{host}:{identity}" if salt else f"{host}:{identity}"
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest(), 16)
