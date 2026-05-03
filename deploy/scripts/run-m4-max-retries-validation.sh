#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python"
fi

"${PYTHON_BIN}" - <<'PY'
from crawler.policy_provider import StaticRuntimePolicyProvider
from crawler.queues import parse_fetch_command
from crawler.runtime_policy import policy_document_from_mapping
from crawler.spiders.fetch_queue import FetchQueueSpider


class Consumer:
    is_shutting_down = False
    max_deliveries = 3


doc = policy_document_from_mapping({
    "schema_version": "1.0",
    "version": "policy-default",
    "generated_at": "2026-05-03T10:00:00Z",
    "default_policy": {"enabled": True, "paused": False, "max_retries": 5},
})
spider = FetchQueueSpider(name="fetch_queue")
spider.consumer = Consumer()
spider.policy_provider = StaticRuntimePolicyProvider(doc)
command = parse_fetch_command({
    "url": "https://example.com/",
    "canonical_url": "https://example.com",
    "job_id": "m4-retry",
    "max_retries": "0",
})
request = spider._build_or_delay_request(command, "1-0")

assert request.meta["effective_max_retries"] == 0
assert spider._should_retry_request(request) is False
print("m4_max_retries_validation_ok")
PY
