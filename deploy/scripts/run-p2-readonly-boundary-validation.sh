#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMAND_FILE="${COMMAND_FILE:-/tmp/p2-readonly-commands.$$.jsonl}"
LOG_FILE="${P2_READONLY_LOG:-/tmp/p2-readonly-boundary-validation.$$.log}"
KEYS_BEFORE="${P2_READONLY_KEYS_BEFORE:-/tmp/p2-readonly-keys-before.$$.txt}"
KEYS_AFTER="${P2_READONLY_KEYS_AFTER:-/tmp/p2-readonly-keys-after.$$.txt}"

if [[ -z "${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}" ]]; then
  echo "缺少 FETCH_QUEUE_REDIS_URL 或 REDIS_URL。"
  exit 2
fi

export FETCH_QUEUE_REDIS_URL="${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}"
export FETCH_QUEUE_STREAM="${FETCH_QUEUE_STREAM:-crawl:tasks:p2-readonly-$$}"
export FETCH_QUEUE_GROUP="${FETCH_QUEUE_GROUP:-crawler-executor-p2-readonly-$$}"
export FETCH_QUEUE_CONSUMER="${FETCH_QUEUE_CONSUMER:-worker-readonly-$$}"
export FETCH_QUEUE_READ_COUNT="${FETCH_QUEUE_READ_COUNT:-1}"
export FETCH_QUEUE_BLOCK_MS="${FETCH_QUEUE_BLOCK_MS:-1000}"
export FETCH_QUEUE_MAX_DELIVERIES="${FETCH_QUEUE_MAX_DELIVERIES:-1}"
export FETCH_QUEUE_AUDIT_PATTERN="${FETCH_QUEUE_AUDIT_PATTERN:-${FETCH_QUEUE_STREAM}*}"
export ENABLE_P1_PERSISTENCE="true"
export FORCE_CLOSE_CONNECTIONS="${FORCE_CLOSE_CONNECTIONS:-false}"
export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"

cat >"${COMMAND_FILE}" <<'EOF'
{"url":"https://www.wikipedia.org/","canonical_url":"https://www.wikipedia.org","job_id":"p2-readonly-html","command_id":"p2-readonly-1","trace_id":"p2-readonly-trace"}
EOF

echo "运行 P2 Redis 只读边界验证："
echo "COMMAND_FILE=${COMMAND_FILE}"
echo "LOG_FILE=${LOG_FILE}"
echo "FETCH_QUEUE_STREAM=${FETCH_QUEUE_STREAM}"
echo "FETCH_QUEUE_GROUP=${FETCH_QUEUE_GROUP}"
echo "FETCH_QUEUE_AUDIT_PATTERN=${FETCH_QUEUE_AUDIT_PATTERN}"
echo

"${ROOT_DIR}/deploy/scripts/p2-enqueue-fetch-commands.sh" "${COMMAND_FILE}"

python - "${KEYS_BEFORE}" <<'PY'
import os
import sys

import redis

client = redis.from_url(os.environ["FETCH_QUEUE_REDIS_URL"], decode_responses=True)
pattern = os.environ["FETCH_QUEUE_AUDIT_PATTERN"]
keys = sorted(client.scan_iter(match=pattern))
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    for key in keys:
        handle.write(key + "\n")
PY

cd "${ROOT_DIR}/src/crawler"

set +e
python -m scrapy crawl fetch_queue \
  -a max_messages=1 \
  -s LOG_LEVEL="${LOG_LEVEL:-INFO}" 2>&1 | tee "${LOG_FILE}"
status=${PIPESTATUS[0]}
set -e

if [[ "${status}" -ne 0 ]]; then
  exit "${status}"
fi

python - "${KEYS_AFTER}" <<'PY'
import os
import sys

import redis

client = redis.from_url(os.environ["FETCH_QUEUE_REDIS_URL"], decode_responses=True)
pattern = os.environ["FETCH_QUEUE_AUDIT_PATTERN"]
keys = sorted(client.scan_iter(match=pattern))
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    for key in keys:
        handle.write(key + "\n")
PY

new_keys="$(comm -13 "${KEYS_BEFORE}" "${KEYS_AFTER}" || true)"
if [[ -n "${new_keys}" ]]; then
  echo "P2 只读边界验证失败：worker 运行后出现新的 Redis key："
  echo "${new_keys}"
  exit 1
fi

grep -q "p1_crawl_attempt_published" "${LOG_FILE}" || {
  echo "P2 只读边界验证失败：未观察到 crawl_attempt 发布。"
  exit 1
}

echo "P2 Redis 只读边界验证通过：未发现 executor 新建 URL 队列或去重 key。"
