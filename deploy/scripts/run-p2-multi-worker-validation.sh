#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMAND_FILE="${COMMAND_FILE:-/tmp/p2-multi-worker-commands.$$.jsonl}"
LOG_FILE_1="${P2_MULTI_WORKER_LOG_1:-/tmp/p2-multi-worker-1.$$.log}"
LOG_FILE_2="${P2_MULTI_WORKER_LOG_2:-/tmp/p2-multi-worker-2.$$.log}"

if [[ -z "${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}" ]]; then
  echo "缺少 FETCH_QUEUE_REDIS_URL 或 REDIS_URL。"
  exit 2
fi

export FETCH_QUEUE_REDIS_URL="${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}"
export FETCH_QUEUE_STREAM="${FETCH_QUEUE_STREAM:-crawl:tasks:p2-multi-$$}"
export FETCH_QUEUE_GROUP="${FETCH_QUEUE_GROUP:-crawler-executor-p2-multi-$$}"
export FETCH_QUEUE_READ_COUNT="${FETCH_QUEUE_READ_COUNT:-1}"
export FETCH_QUEUE_BLOCK_MS="${FETCH_QUEUE_BLOCK_MS:-1000}"
export FETCH_QUEUE_MAX_DELIVERIES="${FETCH_QUEUE_MAX_DELIVERIES:-1}"
export ENABLE_P1_PERSISTENCE="true"
export FORCE_CLOSE_CONNECTIONS="${FORCE_CLOSE_CONNECTIONS:-false}"
export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"

: >"${COMMAND_FILE}"
for index in $(seq 1 10); do
  printf '{"url":"https://www.wikipedia.org/static/favicon/wikipedia.ico","canonical_url":"https://www.wikipedia.org/static/favicon/wikipedia.ico","job_id":"p2-multi-%02d","command_id":"p2-multi-%02d","trace_id":"p2-multi-trace"}\n' "${index}" "${index}" >>"${COMMAND_FILE}"
done

echo "运行 P2 多 worker 消费验证："
echo "COMMAND_FILE=${COMMAND_FILE}"
echo "LOG_FILE_1=${LOG_FILE_1}"
echo "LOG_FILE_2=${LOG_FILE_2}"
echo "FETCH_QUEUE_STREAM=${FETCH_QUEUE_STREAM}"
echo "FETCH_QUEUE_GROUP=${FETCH_QUEUE_GROUP}"
echo

"${ROOT_DIR}/deploy/scripts/p2-enqueue-fetch-commands.sh" "${COMMAND_FILE}"
echo

(
  set -o pipefail
  export FETCH_QUEUE_CONSUMER="worker-a-$$"
  cd "${ROOT_DIR}/src/crawler"
  python -m scrapy crawl fetch_queue -a max_messages=5 -s LOG_LEVEL="${LOG_LEVEL:-INFO}" 2>&1 | tee "${LOG_FILE_1}"
) &
pid1=$!

(
  set -o pipefail
  export FETCH_QUEUE_CONSUMER="worker-b-$$"
  cd "${ROOT_DIR}/src/crawler"
  python -m scrapy crawl fetch_queue -a max_messages=5 -s LOG_LEVEL="${LOG_LEVEL:-INFO}" 2>&1 | tee "${LOG_FILE_2}"
) &
pid2=$!

set +e
wait "${pid1}"
status1=$?
wait "${pid2}"
status2=$?
set -e

if [[ "${status1}" -ne 0 || "${status2}" -ne 0 ]]; then
  echo "P2 多 worker 验证失败：worker 退出码 worker1=${status1}, worker2=${status2}。"
  exit 1
fi

published_count="$(grep -h "p1_crawl_attempt_published" "${LOG_FILE_1}" "${LOG_FILE_2}" | wc -l | tr -d ' ')"
unique_attempts="$(grep -h -o 'attempt_id=[^ ]*' "${LOG_FILE_1}" "${LOG_FILE_2}" | sort -u | wc -l | tr -d ' ')"

if [[ "${published_count}" -ne 10 ]]; then
  echo "P2 多 worker 验证失败：期望 10 条发布日志，实际 ${published_count}。"
  exit 1
fi

if [[ "${unique_attempts}" -ne 10 ]]; then
  echo "P2 多 worker 验证失败：期望 10 个唯一 attempt_id，实际 ${unique_attempts}。"
  exit 1
fi

echo "P2 多 worker 消费验证通过。"
