from crawler.politeness import (
    HostIpPacerConfig,
    HostIpPacerState,
    mark_backoff,
    mark_request_started,
    mark_success,
    pacer_decision,
)


def test_pacer_decision_reports_eligible_when_next_allowed_has_passed():
    state = HostIpPacerState(next_allowed_at_ms=1000)

    assert pacer_decision(state, now_ms=1000).eligible is True
    assert pacer_decision(state, now_ms=900).delay_ms == 100


def test_mark_request_started_sets_next_allowed_with_delay_jitter_and_slowdown():
    config = HostIpPacerConfig(min_delay_ms=2000, jitter_ms=500)

    state = mark_request_started(
        HostIpPacerState(),
        config,
        now_ms=10000,
        host_slowdown_factor=3.0,
        jitter_ms=250,
    )

    assert state.last_started_at_ms == 10000
    assert state.min_delay_ms == 6000
    assert state.next_allowed_at_ms == 16250


def test_mark_backoff_increments_level_and_caps_delay():
    config = HostIpPacerConfig(backoff_base_ms=5000, backoff_max_ms=12000, backoff_multiplier=2.0)

    first = mark_backoff(HostIpPacerState(), config, now_ms=1000, signal_type="http_429")
    second = mark_backoff(first, config, now_ms=2000, signal_type="captcha_challenge")
    capped = mark_backoff(second, config, now_ms=3000, signal_type="captcha_challenge")

    assert first.backoff_level == 1
    assert first.next_allowed_at_ms == 6000
    assert second.backoff_level == 2
    assert second.next_allowed_at_ms == 12000
    assert capped.backoff_level == 3
    assert capped.next_allowed_at_ms == 15000


def test_mark_success_resets_backoff_level_without_moving_next_allowed():
    state = HostIpPacerState(next_allowed_at_ms=5000, backoff_level=2, last_started_at_ms=1000)

    updated = mark_success(state, now_ms=2000)

    assert updated.backoff_level == 0
    assert updated.last_signal == "success"
    assert updated.next_allowed_at_ms == 5000
