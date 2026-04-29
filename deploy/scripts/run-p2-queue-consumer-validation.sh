#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMAND_FILE="${1:-${COMMAND_FILE:-/tmp/p2-queue-consumer-commands.$$.jsonl}}"
LOG_FILE="${P2_QUEUE_CONSUMER_LOG:-/tmp/p2-queue-consumer-validation.$$.log}"

if [[ -z "${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}" ]]; then
  echo "缺少 FETCH_QUEUE_REDIS_URL 或 REDIS_URL。"
  exit 2
fi

export FETCH_QUEUE_REDIS_URL="${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}"
export FETCH_QUEUE_STREAM="${FETCH_QUEUE_STREAM:-crawl:tasks:p2-single-$$}"
export FETCH_QUEUE_GROUP="${FETCH_QUEUE_GROUP:-crawler-executor-p2-single-$$}"
export FETCH_QUEUE_CONSUMER="${FETCH_QUEUE_CONSUMER:-worker-single-$$}"
export FETCH_QUEUE_READ_COUNT="${FETCH_QUEUE_READ_COUNT:-1}"
export FETCH_QUEUE_BLOCK_MS="${FETCH_QUEUE_BLOCK_MS:-1000}"
export FETCH_QUEUE_MAX_DELIVERIES="${FETCH_QUEUE_MAX_DELIVERIES:-1}"
export FETCH_QUEUE_CLAIM_MIN_IDLE_MS="${FETCH_QUEUE_CLAIM_MIN_IDLE_MS:-1000}"
export ENABLE_P1_PERSISTENCE="true"
export FORCE_CLOSE_CONNECTIONS="${FORCE_CLOSE_CONNECTIONS:-false}"
export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"

cat >"${COMMAND_FILE}" <<'EOF'
{"url":"https://www.wikipedia.org/","canonical_url":"https://www.wikipedia.org","job_id":"p2-single-html","command_id":"p2-single-1","trace_id":"p2-single-trace"}
{"url":"https://www.wikipedia.org/static/favicon/wikipedia.ico","canonical_url":"https://www.wikipedia.org/static/favicon/wikipedia.ico","job_id":"p2-single-non-html","command_id":"p2-single-2","trace_id":"p2-single-trace"}
{"url":"http://127.0.0.1:1/","canonical_url":"http://127.0.0.1:1","job_id":"p2-single-fetch-failed","command_id":"p2-single-3","trace_id":"p2-single-trace"}
EOF

echo "运行 P2 单 worker 队列消费验证："
echo "ROOT_DIR=${ROOT_DIR}"
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
  -a max_messages=3 \
  -s LOG_LEVEL="${LOG_LEVEL:-INFO}" 2>&1 | tee "${LOG_FILE}"
status=${PIPESTATUS[0]}
set -e

if [[ "${status}" -ne 0 ]]; then
  exit "${status}"
fi

published_count="$(grep -c "p1_crawl_attempt_published" "${LOG_FILE}" || true)"
if [[ "${published_count}" -lt 3 ]]; then
  echo "P2 单 worker 验证失败：期望至少 3 条 crawl_attempt 发布日志，实际 ${published_count}。"
  exit 1
fi

grep -q "storage_result=stored" "${LOG_FILE}" || {
  echo "P2 单 worker 验证失败：未观察到 storage_result=stored。"
  exit 1
}

grep -q "reason=non_html_content" "${LOG_FILE}" || {
  echo "P2 单 worker 验证失败：未观察到非 HTML skipped。"
  exit 1
}

grep -q "reason=fetch_failed" "${LOG_FILE}" || {
  echo "P2 单 worker 验证失败：未观察到 fetch_failed attempt。"
  exit 1
}

storage_key="$(grep -o 'storage_key=[^ ]*' "${LOG_FILE}" | tail -n 1 | cut -d= -f2- || true)"
if [[ -n "${storage_key}" ]]; then
  python -m crawler.tools.p1_verify_storage_object "${storage_key}"
fi

echo "P2 单 worker 队列消费验证通过。"
