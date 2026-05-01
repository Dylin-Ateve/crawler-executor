import pytest

from crawler.ip_pool import IpPoolError, LocalIpPool, discover_local_ips, stable_host_bucket


def test_discover_local_ips_filters_loopback_duplicates_and_excluded():
    ips = discover_local_ips(
        "enp0s5",
        exclude_ips={"10.0.0.2"},
        ip_provider=lambda _name: ["127.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.3", "bad"],
    )

    assert ips == ["10.0.0.3"]


def test_discover_local_ips_accepts_all_interfaces_marker():
    seen_interfaces = []

    ips = discover_local_ips(
        "all",
        ip_provider=lambda name: seen_interfaces.append(name) or ["127.0.0.1", "10.0.0.3", "10.0.0.4"],
    )

    assert seen_interfaces == ["all"]
    assert ips == ["10.0.0.3", "10.0.0.4"]


def test_sticky_by_host_reuses_mapping_until_blacklisted():
    pool = LocalIpPool(["10.0.0.2", "10.0.0.3", "10.0.0.4"], strategy="STICKY_BY_HOST")

    first = pool.select_for_host("example.com")
    assert pool.select_for_host("example.com") == first

    second = pool.select_for_host("example.com", is_blacklisted=lambda _host, ip: ip == first)
    assert second != first
    assert pool.select_for_host("example.com") == second


def test_round_robin_skips_blacklisted_ip():
    pool = LocalIpPool(["10.0.0.2", "10.0.0.3"], strategy="ROUND_ROBIN")

    assert pool.select_for_host("a.example") == "10.0.0.2"
    assert pool.select_for_host("b.example", is_blacklisted=lambda _host, ip: ip == "10.0.0.3") == "10.0.0.2"


def test_all_blacklisted_raises():
    pool = LocalIpPool(["10.0.0.2"], strategy="STICKY_BY_HOST")

    with pytest.raises(IpPoolError):
        pool.select_for_host("example.com", is_blacklisted=lambda _host, _ip: True)


def test_stable_host_bucket_is_deterministic():
    assert stable_host_bucket("example.com", 8) == stable_host_bucket("example.com", 8)


def test_local_ip_pool_supports_sixty_ipv4_addresses_without_fixed_cap():
    ips = [f"10.0.1.{index}" for index in range(10, 70)]

    pool = LocalIpPool(ips, strategy="STICKY_BY_HOST")

    assert len(pool.ip_pool) == 60
    assert pool.select_for_host("example.com") in pool.ip_pool


def test_local_ip_pool_accepts_sticky_pool_as_legacy_fallback():
    pool = LocalIpPool(["10.0.0.2", "10.0.0.3"], strategy="STICKY_POOL")

    first = pool.select_for_host("example.com")

    assert first in pool.ip_pool
    assert pool.select_for_host("example.com") == first
