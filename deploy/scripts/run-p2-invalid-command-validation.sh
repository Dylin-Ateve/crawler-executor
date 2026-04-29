#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMAND_FILE="${COMMAND_FILE:-/tmp/p2-invalid-commands.$$.jsonl}"
LOG_FILE="${P2_INVALID_COMMAND_LOG:-/tmp/p2-invalid-command-validation.$$.log}"

if [[ -z "${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}" ]]; then
  echo "缺少 FETCH_QUEUE_REDIS_URL 或 REDIS_URL。"
  exit 2
fi

export FETCH_QUEUE_REDIS_URL="${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}"
export FETCH_QUEUE_STREAM="${FETCH_QUEUE_STREAM:-crawl:tasks:p2-invalid-$$}"
export FETCH_QUEUE_GROUP="${FETCH_QUEUE_GROUP:-crawler-executor-p2-invalid-$$}"
export FETCH_QUEUE_CONSUMER="${FETCH_QUEUE_CONSUMER:-worker-invalid-$$}"
export FETCH_QUEUE_READ_COUNT="${FETCH_QUEUE_READ_COUNT:-10}"
export FETCH_QUEUE_BLOCK_MS="${FETCH_QUEUE_BLOCK_MS:-1000}"
export FETCH_QUEUE_MAX_DELIVERIES="${FETCH_QUEUE_MAX_DELIVERIES:-1}"
export ENABLE_P1_PERSISTENCE="false"
export FORCE_CLOSE_CONNECTIONS="${FORCE_CLOSE_CONNECTIONS:-false}"
export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"

cat >"${COMMAND_FILE}" <<'EOF'
{"url":"https://example.com","canonical_url":"https://example.com"}
{"url":"not-a-url","canonical_url":"https://example.com","job_id":"p2-invalid-url"}
{"payload":"{bad-json"}
EOF

echo "运行 P2 无效 Fetch Command 验证："
echo "COMMAND_FILE=${COMMAND_FILE}"
echo "LOG_FILE=${LOG_FILE}"
echo "FETCH_QUEUE_STREAM=${FETCH_QUEUE_STREAM}"
echo "FETCH_QUEUE_GROUP=${FETCH_QUEUE_GROUP}"
echo

"${ROOT_DIR}/deploy/scripts/p2-enqueue-fetch-commands.sh" "${COMMAND_FILE}"
echo

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

invalid_count="$(grep -c "fetch_queue_invalid_message" "${LOG_FILE}" || true)"
if [[ "${invalid_count}" -lt 3 ]]; then
  echo "P2 无效消息验证失败：期望至少 3 条 invalid 日志，实际 ${invalid_count}。"
  exit 1
fi

if grep -q "p1_crawl_attempt_published" "${LOG_FILE}"; then
  echo "P2 无效消息验证失败：无效消息不应发布 crawl_attempt。"
  exit 1
fi

echo "P2 无效 Fetch Command 验证通过。"
