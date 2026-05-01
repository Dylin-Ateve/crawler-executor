import pytest

from crawler.egress_identity import resolve_egress_identities
from crawler.egress_policy import (
    EgressPolicyError,
    build_sticky_pool_assignment,
    select_from_sticky_pool,
)


def _identities(count=6):
    return resolve_egress_identities([f"10.0.0.{index}" for index in range(10, 10 + count)])


def test_sticky_pool_uses_configured_candidate_count_and_is_stable():
    identities = _identities(6)

    first = build_sticky_pool_assignment("Example.COM", identities, pool_size=4, hash_salt="test", now_ms=1000)
    second = build_sticky_pool_assignment("example.com", identities, pool_size=4, hash_salt="test", now_ms=2000)

    assert first.host == "example.com"
    assert first.pool_size_requested == 4
    assert first.pool_size_actual == 4
    assert first.candidate_identity_hashes == second.candidate_identity_hashes


def test_sticky_pool_caps_candidate_count_to_available_identity_count():
    assignment = build_sticky_pool_assignment("example.com", _identities(2), pool_size=4)

    assert assignment.pool_size_actual == 2


def test_sticky_pool_local_perturbation_when_identity_pool_changes():
    identities = _identities(8)
    hosts = [f"host-{index}.example" for index in range(30)]
    removed = identities[0]

    before = {
        host: build_sticky_pool_assignment(host, identities, pool_size=3, hash_salt="test").candidate_identity_hashes
        for host in hosts
    }
    after_pool = tuple(identity for identity in identities if identity != removed)
    after = {
        host: build_sticky_pool_assignment(host, after_pool, pool_size=3, hash_salt="test").candidate_identity_hashes
        for host in hosts
    }

    unaffected_hosts = [host for host, pool in before.items() if removed.identity_hash not in pool]
    assert unaffected_hosts
    assert all(before[host] == after[host] for host in unaffected_hosts)


def test_select_from_sticky_pool_skips_cooldown_and_prefers_not_backed_off():
    assignment = build_sticky_pool_assignment("example.com", _identities(4), pool_size=4)
    first, second, third = assignment.candidate_identities[:3]

    selected = select_from_sticky_pool(
        assignment,
        is_in_cooldown=lambda identity: identity == first,
        is_backed_off=lambda _host, identity: identity == second,
    )

    assert selected == third


def test_select_from_sticky_pool_can_fallback_to_backed_off_candidate():
    assignment = build_sticky_pool_assignment("example.com", _identities(2), pool_size=2)

    selected = select_from_sticky_pool(assignment, is_backed_off=lambda _host, _identity: True)

    assert selected == assignment.candidate_identities[0]


def test_select_from_sticky_pool_raises_when_all_candidates_in_cooldown():
    assignment = build_sticky_pool_assignment("example.com", _identities(2), pool_size=2)

    with pytest.raises(EgressPolicyError):
        select_from_sticky_pool(assignment, is_in_cooldown=lambda _identity: True)
