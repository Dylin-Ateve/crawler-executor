from __future__ import annotations

import json

from crawler.policy_provider import FileRuntimePolicyProvider
from crawler.runtime_policy import (
    RuntimePolicyError,
    decide_policy,
    make_bootstrap_policy_document,
    policy_document_from_mapping,
)


class DictSettings:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, name, default=None):
        return self.values.get(name, default)

    def getint(self, name, default=0):
        return int(self.values.get(name, default))


def _policy_doc(version="policy-1"):
    return {
        "schema_version": "1.0",
        "version": version,
        "generated_at": "2026-05-03T10:00:00Z",
        "default_policy": {
            "enabled": True,
            "paused": False,
            "egress_selection_strategy": "STICKY_POOL",
            "sticky_pool_size": 4,
            "host_ip_min_delay_ms": 2000,
            "host_ip_jitter_ms": 500,
            "download_timeout_seconds": 30,
            "max_retries": 2,
            "max_local_delay_seconds": 300,
        },
        "scope_policies": [
            {
                "scope_type": "politeness_key",
                "scope_id": "site:example",
                "policy": {"host_ip_min_delay_ms": 5000, "max_retries": 1},
            },
            {
                "scope_type": "policy_scope_id",
                "scope_id": "scope-paused",
                "policy": {"paused": True, "pause_reason": "manual_pause"},
            },
        ],
    }


def test_policy_document_parses_and_matches_scope_order():
    document = policy_document_from_mapping(_policy_doc())

    decision = decide_policy(
        document,
        {
            "policy_scope_id": "missing",
            "politeness_key": "site:example",
            "tier": "default",
        },
    )

    assert decision.policy_version == "policy-1"
    assert decision.matched_scope_type == "politeness_key"
    assert decision.matched_scope_id == "site:example"
    assert decision.policy.host_ip_min_delay_ms == 5000
    assert decision.policy.sticky_pool_size == 4
    assert decision.policy.max_retries == 1


def test_policy_scope_id_takes_precedence_over_politeness_key():
    document = policy_document_from_mapping(_policy_doc())

    decision = decide_policy(
        document,
        {
            "policy_scope_id": "scope-paused",
            "politeness_key": "site:example",
        },
    )

    assert decision.matched_scope_type == "policy_scope_id"
    assert decision.policy.is_paused is True
    assert decision.policy.pause_reason == "manual_pause"


def test_policy_document_rejects_duplicate_scope():
    data = _policy_doc()
    data["scope_policies"].append(data["scope_policies"][0])

    try:
        policy_document_from_mapping(data)
    except RuntimePolicyError as exc:
        assert "duplicate scope policy" in str(exc)
    else:
        raise AssertionError("expected duplicate scope rejection")


def test_policy_document_rejects_unknown_policy_field():
    data = _policy_doc()
    data["default_policy"]["priority"] = 10

    try:
        policy_document_from_mapping(data)
    except RuntimePolicyError as exc:
        assert "unknown policy fields" in str(exc)
    else:
        raise AssertionError("expected unknown field rejection")


def test_file_provider_uses_last_known_good_on_invalid_update(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(_policy_doc("policy-good")), encoding="utf-8")
    provider = FileRuntimePolicyProvider(
        str(path),
        bootstrap_document=make_bootstrap_policy_document(DictSettings()),
        reload_interval_seconds=1,
    )

    first = provider.current(force=True)
    path.write_text("{not-json", encoding="utf-8")
    second = provider.current(force=True)

    assert first.document.version == "policy-good"
    assert first.lkg_active is False
    assert second.document.version == "policy-good"
    assert second.lkg_active is True
    assert second.load_result == "validation_error"


def test_file_provider_falls_back_to_bootstrap_without_lkg(tmp_path):
    path = tmp_path / "missing.json"
    bootstrap = make_bootstrap_policy_document(DictSettings({"FETCH_QUEUE_MAX_DELIVERIES": 5}))
    provider = FileRuntimePolicyProvider(str(path), bootstrap_document=bootstrap, reload_interval_seconds=1)

    snapshot = provider.current(force=True)

    assert snapshot.document.version == "bootstrap-settings"
    assert snapshot.lkg_active is False
    assert snapshot.load_result == "read_error"
    assert snapshot.document.default_policy.max_retries == 4
