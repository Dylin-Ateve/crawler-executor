from __future__ import annotations

import hashlib
import ipaddress
import itertools
import socket
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set


class IpPoolError(RuntimeError):
    """Raised when no eligible local IP can be selected."""


def _normalize_ip(ip: str) -> str:
    return str(ipaddress.ip_address(ip.strip()))


def _is_usable_ipv4(ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return parsed.version == 4 and not parsed.is_loopback and not parsed.is_unspecified


def _is_all_interfaces(interface: str) -> bool:
    return not interface.strip() or interface.strip().lower() in {"*", "all"}


def _iter_ipv4_with_psutil(interface: str) -> List[str]:
    try:
        import psutil
    except ImportError:
        return []

    if _is_all_interfaces(interface):
        ips: List[str] = []
        for addrs in psutil.net_if_addrs().values():
            ips.extend(addr.address for addr in addrs if getattr(addr, "family", None) == socket.AF_INET)
        return ips

    addrs = psutil.net_if_addrs().get(interface, [])
    return [addr.address for addr in addrs if getattr(addr, "family", None) == socket.AF_INET]


def _iter_ipv4_with_netifaces(interface: str) -> List[str]:
    try:
        import netifaces
    except ImportError:
        return []

    if _is_all_interfaces(interface):
        ips: List[str] = []
        for name in netifaces.interfaces():
            addrs = netifaces.ifaddresses(name).get(netifaces.AF_INET, [])
            ips.extend(addr.get("addr") for addr in addrs if addr.get("addr"))
        return ips

    addrs = netifaces.ifaddresses(interface).get(netifaces.AF_INET, [])
    return [addr.get("addr") for addr in addrs if addr.get("addr")]


def discover_local_ips(
    interface: str,
    exclude_ips: Optional[Iterable[str]] = None,
    ip_provider: Optional[Callable[[str], Iterable[str]]] = None,
) -> List[str]:
    """Discover usable IPv4 addresses on local network interface(s).

    ``interface`` can be a concrete interface name, or ``all`` / ``*`` / empty
    to scan every local interface visible to the process.
    """

    provider = ip_provider
    if provider is None:
        def provider(name: str) -> Iterable[str]:
            return _iter_ipv4_with_psutil(name) or _iter_ipv4_with_netifaces(name)

    excluded: Set[str] = set()
    for ip in exclude_ips or []:
        try:
            excluded.add(_normalize_ip(ip))
        except ValueError:
            continue

    discovered: List[str] = []
    seen: Set[str] = set()
    for raw_ip in provider(interface):
        if not raw_ip or not _is_usable_ipv4(raw_ip):
            continue
        ip = _normalize_ip(raw_ip)
        if ip in excluded or ip in seen:
            continue
        seen.add(ip)
        discovered.append(ip)
    return discovered


def stable_host_bucket(host: str, modulo: int) -> int:
    if modulo <= 0:
        raise ValueError("modulo must be positive")
    digest = hashlib.sha256(host.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


@dataclass
class LocalIpPool:
    ip_pool: Sequence[str]
    strategy: str = "STICKY_BY_HOST"
    host_ip_map: Dict[str, str] = field(default_factory=dict)
    _rr_counter: itertools.count = field(default_factory=itertools.count)

    def __post_init__(self) -> None:
        normalized = [_normalize_ip(ip) for ip in self.ip_pool if _is_usable_ipv4(ip)]
        if not normalized:
            raise IpPoolError("no usable local IPv4 addresses discovered")
        self.ip_pool = tuple(dict.fromkeys(normalized))
        self.strategy = self.strategy.upper()

    def select_for_host(
        self,
        host: str,
        is_blacklisted: Optional[Callable[[str, str], bool]] = None,
    ) -> str:
        blacklist = is_blacklisted or (lambda _host, _ip: False)
        host = host.lower().strip()
        if not host:
            raise IpPoolError("host is required for IP selection")

        if self.strategy == "ROUND_ROBIN":
            return self._select_round_robin(host, blacklist)
        if self.strategy in {"STICKY_BY_HOST", "STICKY_POOL"}:
            return self._select_sticky(host, blacklist)
        raise IpPoolError(f"unsupported IP selection strategy: {self.strategy}")

    def _select_sticky(self, host: str, is_blacklisted: Callable[[str, str], bool]) -> str:
        existing = self.host_ip_map.get(host)
        if existing and not is_blacklisted(host, existing):
            return existing

        start = stable_host_bucket(host, len(self.ip_pool))
        candidates = list(self.ip_pool[start:]) + list(self.ip_pool[:start])
        for ip in candidates:
            if not is_blacklisted(host, ip):
                self.host_ip_map[host] = ip
                return ip
        raise IpPoolError(f"all local IPs are blacklisted for host: {host}")

    def _select_round_robin(self, host: str, is_blacklisted: Callable[[str, str], bool]) -> str:
        total = len(self.ip_pool)
        start = next(self._rr_counter) % total
        for offset in range(total):
            ip = self.ip_pool[(start + offset) % total]
            if not is_blacklisted(host, ip):
                self.host_ip_map[host] = ip
                return ip
        raise IpPoolError(f"all local IPs are blacklisted for host: {host}")
