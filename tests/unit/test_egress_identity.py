import json

import pytest

from crawler.egress_identity import (
    EgressIdentityError,
    load_egress_identity_map,
    resolve_egress_identities,
    resolve_egress_identity,
    stable_hash,
)


def test_resolve_egress_identity_prefers_public_ip_when_mapping_exists():
    identity = resolve_egress_identity(
        "10.0.0.2",
        "198.51.100.10",
        identity_source="auto",
        hash_salt="test",
        interface="enp0s5",
    )

    assert identity.identity == "198.51.100.10"
    assert identity.identity_type == "public_ip"
    assert identity.bind_ip == "10.0.0.2"
    assert identity.public_ip == "198.51.100.10"
    assert identity.interface == "enp0s5"
    assert identity.identity_hash == stable_hash("198.51.100.10", salt="test")


def test_resolve_egress_identity_falls_back_to_bind_ip_and_marks_type():
    identity = resolve_egress_identity("10.0.0.2", identity_source="auto", allow_bind_ip=True)

    assert identity.identity == "10.0.0.2"
    assert identity.identity_type == "bind_ip"
    assert identity.public_ip is None


def test_resolve_egress_identity_requires_public_ip_when_fallback_disabled():
    with pytest.raises(EgressIdentityError):
        resolve_egress_identity("10.0.0.2", identity_source="auto", allow_bind_ip=False)


def test_load_egress_identity_map_from_json_object(tmp_path):
    path = tmp_path / "egress-map.json"
    path.write_text(json.dumps({"10.0.0.2": "198.51.100.10"}), encoding="utf-8")

    assert load_egress_identity_map(str(path)) == {"10.0.0.2": "198.51.100.10"}


def test_load_egress_identity_map_from_csv_header(tmp_path):
    path = tmp_path / "egress-map.csv"
    path.write_text("bind_ip,public_ip\n10.0.0.2,198.51.100.10\n", encoding="utf-8")

    assert load_egress_identity_map(str(path)) == {"10.0.0.2": "198.51.100.10"}


def test_resolve_egress_identities_uses_bind_ip_fallback_for_missing_mapping():
    identities = resolve_egress_identities(
        ["10.0.0.2", "10.0.0.3"],
        identity_map={"10.0.0.2": "198.51.100.10"},
        identity_source="auto",
        allow_bind_ip=True,
    )

    assert [identity.identity_type for identity in identities] == ["public_ip", "bind_ip"]
    assert [identity.identity for identity in identities] == ["198.51.100.10", "10.0.0.3"]
