from crawler.response_signals import (
    BodyPattern,
    SIGNAL_ANTI_BOT_200,
    SIGNAL_CAPTCHA_CHALLENGE,
    SIGNAL_CONNECTION_FAILED,
    SIGNAL_HTTP_429,
    SIGNAL_HTTP_5XX,
    SIGNAL_SUCCESS,
    SIGNAL_TIMEOUT,
    classify_exception_signal,
    classify_response_signal,
    parse_body_patterns,
)


def test_classify_response_signal_maps_429_to_strong_soft_ban():
    signal = classify_response_signal(
        host="Example.COM",
        identity_hash="identity-hash",
        status_code=429,
        observed_at_ms=1000,
    )

    assert signal.signal_type == SIGNAL_HTTP_429
    assert signal.host == "example.com"
    assert signal.weight == 3
    assert signal.status_code == 429


def test_classify_response_signal_detects_challenge_pattern_before_5xx():
    signal = classify_response_signal(
        host="example.com",
        identity_hash="identity-hash",
        status_code=503,
        body=b"<html>please verify you are human</html>",
        challenge_patterns=(BodyPattern("human-check", "verify you are human"),),
        observed_at_ms=1000,
    )

    assert signal.signal_type == SIGNAL_CAPTCHA_CHALLENGE
    assert signal.matched_pattern == "human-check"
    assert signal.weight == 5


def test_classify_response_signal_detects_anti_bot_200():
    signal = classify_response_signal(
        host="example.com",
        identity_hash="identity-hash",
        status_code=200,
        body=b"<html>access denied by bot filter</html>",
        anti_bot_200_patterns=(BodyPattern("bot-filter", "bot filter"),),
        observed_at_ms=1000,
    )

    assert signal.signal_type == SIGNAL_ANTI_BOT_200
    assert signal.matched_pattern == "bot-filter"
    assert signal.weight == 4


def test_classify_response_signal_maps_plain_5xx_to_low_weight_signal():
    signal = classify_response_signal(
        host="example.com",
        identity_hash="identity-hash",
        status_code=503,
        observed_at_ms=1000,
    )

    assert signal.signal_type == SIGNAL_HTTP_5XX
    assert signal.weight == 1


def test_classify_response_signal_maps_regular_200_to_success():
    signal = classify_response_signal(
        host="example.com",
        identity_hash="identity-hash",
        status_code=200,
        observed_at_ms=1000,
    )

    assert signal.signal_type == SIGNAL_SUCCESS
    assert signal.weight == 0


def test_classify_exception_signal_distinguishes_timeout_from_connection_failure():
    timeout = classify_exception_signal(
        host="example.com",
        identity_hash="identity-hash",
        exception=TimeoutError("timed out"),
        observed_at_ms=1000,
    )
    connection = classify_exception_signal(
        host="example.com",
        identity_hash="identity-hash",
        exception=ConnectionError("connection refused"),
        observed_at_ms=1000,
    )

    assert timeout.signal_type == SIGNAL_TIMEOUT
    assert connection.signal_type == SIGNAL_CONNECTION_FAILED


def test_parse_body_patterns_supports_ids_and_inline_patterns():
    patterns = parse_body_patterns("captcha:please verify, access denied")

    assert patterns == (
        BodyPattern(pattern_id="captcha", pattern="please verify"),
        BodyPattern(pattern_id="access denied", pattern="access denied"),
    )
