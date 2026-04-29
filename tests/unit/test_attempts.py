from crawler.attempts import build_command_attempt_id
from crawler.contracts.canonical_url import canonical_url_hash


def test_command_attempt_id_is_stable_for_same_job_and_canonical_url():
    first = build_command_attempt_id("job-1", "https://example.com/path")
    second = build_command_attempt_id("job-1", "https://example.com/path")

    assert first == second


def test_command_attempt_id_changes_when_job_changes():
    first = build_command_attempt_id("job-1", "https://example.com/path")
    second = build_command_attempt_id("job-2", "https://example.com/path")

    assert first != second


def test_command_attempt_id_uses_canonical_url_hash_prefix():
    attempt_id = build_command_attempt_id("job-1", "https://example.com/path")

    assert attempt_id.startswith(canonical_url_hash("https://example.com/path") + ":attempt:")
