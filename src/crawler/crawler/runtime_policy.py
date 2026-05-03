from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Dict, Iterable, Mapping, Optional, Tuple


class RuntimePolicyError(ValueError):
    """Raised when an effective policy document is invalid."""


SCOPE_MATCH_ORDER = ("policy_scope_id", "politeness_key", "host_id", "site_id", "tier")
SUPPORTED_SCHEMA_VERSION = "1.0"
SUPPORTED_EGRESS_STRATEGIES = {"STICKY_POOL", "STICKY_BY_HOST", "ROUND_ROBIN"}


@dataclass(frozen=True)
class EffectivePolicy:
    enabled: bool = True
    paused: bool = False
    pause_reason: Optional[str] = None
    egress_selection_strategy: Optional[str] = None
    sticky_pool_size: Optional[int] = None
    host_ip_min_delay_ms: Optional[int] = None
    host_ip_jitter_ms: Optional[int] = None
    download_timeout_seconds: Optional[int] = None
    max_retries: Optional[int] = None
    max_local_delay_seconds: Optional[int] = None

    @property
    def is_paused(self) -> bool:
        return self.paused or not self.enabled

    def merged_with(self, override: "EffectivePolicy") -> "EffectivePolicy":
        values = {}
        for field_name in self.__dataclass_fields__:
            value = getattr(override, field_name)
            if value is not None:
                values[field_name] = value
        return replace(self, **values)


@dataclass(frozen=True)
class ScopePolicy:
    scope_type: str
    scope_id: str
    policy: EffectivePolicy


@dataclass(frozen=True)
class EffectivePolicyDocument:
    schema_version: str
    version: str
    generated_at: str
    default_policy: EffectivePolicy
    scope_policies: Tuple[ScopePolicy, ...] = ()

    @property
    def scope_index(self) -> Dict[Tuple[str, str], EffectivePolicy]:
        return {(scope.scope_type, scope.scope_id): scope.policy for scope in self.scope_policies}


@dataclass(frozen=True)
class PolicyDecision:
    policy_version: str
    matched_scope_type: str
    matched_scope_id: Optional[str]
    policy: EffectivePolicy
    lkg_active: bool = False


def policy_document_from_mapping(data: Mapping[str, object]) -> EffectivePolicyDocument:
    if not isinstance(data, Mapping):
        raise RuntimePolicyError("policy document must be an object")
    schema_version = _required_string(data, "schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise RuntimePolicyError(f"unsupported schema_version: {schema_version}")
    version = _required_string(data, "version")
    generated_at = _required_string(data, "generated_at")
    _parse_datetime(generated_at, "generated_at")
    default_raw = data.get("default_policy")
    if not isinstance(default_raw, Mapping):
        raise RuntimePolicyError("default_policy must be an object")
    default_policy = _policy_from_mapping(default_raw, default=True)
    scopes_raw = data.get("scope_policies") or []
    if not isinstance(scopes_raw, list):
        raise RuntimePolicyError("scope_policies must be an array")

    seen = set()
    scopes = []
    for index, scope_raw in enumerate(scopes_raw):
        if not isinstance(scope_raw, Mapping):
            raise RuntimePolicyError(f"scope_policies[{index}] must be an object")
        scope_type = _required_string(scope_raw, "scope_type")
        if scope_type not in SCOPE_MATCH_ORDER:
            raise RuntimePolicyError(f"unsupported scope_type: {scope_type}")
        scope_id = _required_string(scope_raw, "scope_id")
        key = (scope_type, scope_id)
        if key in seen:
            raise RuntimePolicyError(f"duplicate scope policy: {scope_type}:{scope_id}")
        seen.add(key)
        policy_raw = scope_raw.get("policy")
        if not isinstance(policy_raw, Mapping):
            raise RuntimePolicyError(f"scope_policies[{index}].policy must be an object")
        scopes.append(ScopePolicy(scope_type=scope_type, scope_id=scope_id, policy=_policy_from_mapping(policy_raw)))

    return EffectivePolicyDocument(
        schema_version=schema_version,
        version=version,
        generated_at=generated_at,
        default_policy=default_policy,
        scope_policies=tuple(scopes),
    )


def make_bootstrap_policy_document(settings) -> EffectivePolicyDocument:
    return EffectivePolicyDocument(
        schema_version=SUPPORTED_SCHEMA_VERSION,
        version="bootstrap-settings",
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        default_policy=EffectivePolicy(
            enabled=True,
            paused=False,
            egress_selection_strategy=(settings.get("EGRESS_SELECTION_STRATEGY") or settings.get("IP_SELECTION_STRATEGY", "STICKY_BY_HOST")).upper(),
            sticky_pool_size=settings.getint("STICKY_POOL_SIZE", 4),
            host_ip_min_delay_ms=settings.getint("HOST_IP_MIN_DELAY_MS", 2000),
            host_ip_jitter_ms=settings.getint("HOST_IP_JITTER_MS", 500),
            download_timeout_seconds=settings.getint("DOWNLOAD_TIMEOUT", 30),
            max_retries=settings.getint("FETCH_QUEUE_MAX_DELIVERIES", 3) - 1,
            max_local_delay_seconds=settings.getint("MAX_LOCAL_DELAY_SECONDS", 300),
        ),
    )


def decide_policy(
    document: EffectivePolicyDocument,
    command_meta: Mapping[str, object],
    *,
    lkg_active: bool = False,
) -> PolicyDecision:
    index = document.scope_index
    for scope_type in SCOPE_MATCH_ORDER:
        value = command_meta.get(scope_type)
        if value is None:
            continue
        scope_id = str(value).strip()
        if not scope_id:
            continue
        override = index.get((scope_type, scope_id))
        if override is None:
            continue
        return PolicyDecision(
            policy_version=document.version,
            matched_scope_type=scope_type,
            matched_scope_id=scope_id,
            policy=document.default_policy.merged_with(override),
            lkg_active=lkg_active,
        )
    return PolicyDecision(
        policy_version=document.version,
        matched_scope_type="default",
        matched_scope_id=None,
        policy=document.default_policy,
        lkg_active=lkg_active,
    )


def _policy_from_mapping(data: Mapping[str, object], *, default: bool = False) -> EffectivePolicy:
    allowed = set(EffectivePolicy.__dataclass_fields__)
    unknown = sorted(str(key) for key in data.keys() if key not in allowed)
    if unknown:
        raise RuntimePolicyError(f"unknown policy fields: {', '.join(unknown)}")
    return EffectivePolicy(
        enabled=_optional_bool(data, "enabled", True if default else None),
        paused=_optional_bool(data, "paused", False if default else None),
        pause_reason=_optional_string(data, "pause_reason"),
        egress_selection_strategy=_optional_strategy(data, "egress_selection_strategy"),
        sticky_pool_size=_optional_int(data, "sticky_pool_size", minimum=1, maximum=1024),
        host_ip_min_delay_ms=_optional_int(data, "host_ip_min_delay_ms", minimum=0, maximum=3600000),
        host_ip_jitter_ms=_optional_int(data, "host_ip_jitter_ms", minimum=0, maximum=3600000),
        download_timeout_seconds=_optional_int(data, "download_timeout_seconds", minimum=1, maximum=3600),
        max_retries=_optional_int(data, "max_retries", minimum=0, maximum=100),
        max_local_delay_seconds=_optional_int(data, "max_local_delay_seconds", minimum=0, maximum=86400),
    )


def _required_string(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimePolicyError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(data: Mapping[str, object], key: str) -> Optional[str]:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RuntimePolicyError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_bool(data: Mapping[str, object], key: str, default: Optional[bool] = None) -> Optional[bool]:
    value = data.get(key, default)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise RuntimePolicyError(f"{key} must be a boolean")
    return value


def _optional_strategy(data: Mapping[str, object], key: str) -> Optional[str]:
    value = _optional_string(data, key)
    if value is None:
        return None
    strategy = value.upper()
    if strategy not in SUPPORTED_EGRESS_STRATEGIES:
        raise RuntimePolicyError(f"{key} is unsupported: {value}")
    return strategy


def _optional_int(
    data: Mapping[str, object],
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> Optional[int]:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimePolicyError(f"{key} must be an integer")
    if value < minimum or value > maximum:
        raise RuntimePolicyError(f"{key} must be between {minimum} and {maximum}")
    return value


def _parse_datetime(value: str, key: str) -> None:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RuntimePolicyError(f"{key} must be an ISO-8601 timestamp") from exc
