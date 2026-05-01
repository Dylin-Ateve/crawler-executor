from __future__ import annotations

import csv
import hashlib
import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional


IDENTITY_TYPE_PUBLIC_IP = "public_ip"
IDENTITY_TYPE_BIND_IP = "bind_ip"
IDENTITY_TYPE_UNKNOWN = "unknown"


class EgressIdentityError(ValueError):
    """Raised when an egress identity cannot be resolved safely."""


@dataclass(frozen=True)
class EgressIdentity:
    identity: str
    identity_hash: str
    identity_type: str
    bind_ip: str
    public_ip: Optional[str] = None
    interface: Optional[str] = None
    asn: Optional[str] = None
    cidr: Optional[str] = None
    status: str = "active"


def stable_hash(value: str, salt: str = "", length: int = 16) -> str:
    if length <= 0:
        raise ValueError("length must be positive")
    payload = f"{salt}:{value}" if salt else value
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def normalize_ip(ip: str) -> str:
    try:
        return str(ipaddress.ip_address(ip.strip()))
    except ValueError as exc:
        raise EgressIdentityError(f"invalid IP address: {ip}") from exc


def load_egress_identity_map(path: str) -> Dict[str, str]:
    """Load bind-private-IP to public-egress-IP mappings from JSON or CSV."""

    if not path:
        return {}

    source = Path(path)
    if not source.exists():
        raise EgressIdentityError(f"egress identity map file does not exist: {path}")

    if source.suffix.lower() == ".json":
        with source.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        return _normalize_mapping(_json_mapping(loaded))

    with source.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.read(2048)
        handle.seek(0)
        if not sample.strip():
            return {}
        sniffer = csv.Sniffer()
        has_header = sniffer.has_header(sample)
        if has_header:
            reader = csv.DictReader(handle)
            return _normalize_mapping(
                {
                    row.get("bind_ip") or row.get("private_ip") or "": row.get("public_ip") or ""
                    for row in reader
                }
            )
        reader = csv.reader(handle)
        return _normalize_mapping({row[0]: row[1] for row in reader if len(row) >= 2})


def resolve_egress_identity(
    bind_ip: str,
    public_ip: Optional[str] = None,
    *,
    identity_source: str = "auto",
    allow_bind_ip: bool = True,
    hash_salt: str = "",
    interface: Optional[str] = None,
    asn: Optional[str] = None,
    cidr: Optional[str] = None,
) -> EgressIdentity:
    normalized_bind_ip = normalize_ip(bind_ip)
    normalized_public_ip = normalize_ip(public_ip) if public_ip else None
    source = identity_source.strip().lower()

    if source == "public_ip":
        if not normalized_public_ip:
            raise EgressIdentityError(f"public egress IP mapping is required for bind_ip={normalized_bind_ip}")
        identity = normalized_public_ip
        identity_type = IDENTITY_TYPE_PUBLIC_IP
    elif source == "bind_ip":
        if not allow_bind_ip:
            raise EgressIdentityError("bind_ip egress identity fallback is disabled")
        identity = normalized_bind_ip
        identity_type = IDENTITY_TYPE_BIND_IP
    elif source == "auto":
        if normalized_public_ip:
            identity = normalized_public_ip
            identity_type = IDENTITY_TYPE_PUBLIC_IP
        elif allow_bind_ip:
            identity = normalized_bind_ip
            identity_type = IDENTITY_TYPE_BIND_IP
        else:
            raise EgressIdentityError(f"no public egress IP mapping for bind_ip={normalized_bind_ip}")
    else:
        raise EgressIdentityError(f"unsupported egress identity source: {identity_source}")

    return EgressIdentity(
        identity=identity,
        identity_hash=stable_hash(identity, salt=hash_salt),
        identity_type=identity_type,
        bind_ip=normalized_bind_ip,
        public_ip=normalized_public_ip,
        interface=interface,
        asn=asn,
        cidr=cidr,
    )


def resolve_egress_identities(
    bind_ips: Iterable[str],
    *,
    identity_map: Optional[Mapping[str, str]] = None,
    identity_source: str = "auto",
    allow_bind_ip: bool = True,
    hash_salt: str = "",
    interface: Optional[str] = None,
) -> tuple[EgressIdentity, ...]:
    mapping = _normalize_mapping(identity_map or {})
    identities = [
        resolve_egress_identity(
            bind_ip,
            mapping.get(normalize_ip(bind_ip)),
            identity_source=identity_source,
            allow_bind_ip=allow_bind_ip,
            hash_salt=hash_salt,
            interface=interface,
        )
        for bind_ip in bind_ips
    ]
    return tuple(dict.fromkeys(identities))


def _json_mapping(loaded) -> Mapping[str, str]:
    if isinstance(loaded, dict):
        return loaded
    if isinstance(loaded, list):
        return {
            item.get("bind_ip") or item.get("private_ip") or "": item.get("public_ip") or ""
            for item in loaded
            if isinstance(item, dict)
        }
    raise EgressIdentityError("egress identity JSON map must be an object or a list of objects")


def _normalize_mapping(mapping: Mapping[str, str]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for bind_ip, public_ip in mapping.items():
        if not bind_ip or not public_ip:
            continue
        normalized[normalize_ip(bind_ip)] = normalize_ip(public_ip)
    return normalized
