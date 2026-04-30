#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ -z "${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}" ]]; then
  echo "缺少 FETCH_QUEUE_REDIS_URL 或 REDIS_URL。"
  exit 2
fi

export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"
export FETCH_QUEUE_REDIS_URL="${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}"
export FETCH_QUEUE_STREAM="${FETCH_QUEUE_STREAM:-crawl:tasks:m3-pause-$$}"
export FETCH_QUEUE_GROUP="${FETCH_QUEUE_GROUP:-crawler-executor-m3-pause-$$}"
export FETCH_QUEUE_CONSUMER="${FETCH_QUEUE_CONSUMER:-worker-paused-$$}"
export FETCH_QUEUE_READ_COUNT="${FETCH_QUEUE_READ_COUNT:-1}"
export FETCH_QUEUE_BLOCK_MS="${FETCH_QUEUE_BLOCK_MS:-1000}"
export FETCH_QUEUE_MAX_MESSAGES="${FETCH_QUEUE_MAX_MESSAGES:-1}"
export CRAWLER_PAUSED="true"
export CRAWLER_PAUSE_POLL_SECONDS="${CRAWLER_PAUSE_POLL_SECONDS:-1}"
export ENABLE_P1_PERSISTENCE="false"

COMMAND_FILE="/tmp/m3-pause-command.$$.jsonl"
LOG_FILE="/tmp/m3-pause-validation.$$.log"
PAUSE_FILE="/tmp/m3-pause-flag.$$"

export CRAWLER_PAUSE_FILE="${CRAWLER_PAUSE_FILE:-${PAUSE_FILE}}"
printf 'true\n' >"${CRAWLER_PAUSE_FILE}"

cat >"${COMMAND_FILE}" <<'EOF'
{"url":"https://www.wikipedia.org/","canonical_url":"https://www.wikipedia.org","command_id":"m3-pause-invalid","trace_id":"m3-pause-trace"}
EOF

"${ROOT_DIR}/deploy/scripts/p2-enqueue-fetch-commands.sh" "${COMMAND_FILE}"

cd "${ROOT_DIR}/src/crawler"
timeout 5s python -m scrapy crawl fetch_queue -s LOG_LEVEL="${LOG_LEVEL:-INFO}" >"${LOG_FILE}" 2>&1 || true

python - <<'PY'
import os
import redis

client = redis.from_url(os.environ["FETCH_QUEUE_REDIS_URL"], decode_responses=True)
stream = os.environ["FETCH_QUEUE_STREAM"]
group = os.environ["FETCH_QUEUE_GROUP"]

length = client.xlen(stream)
try:
    pending = client.xpending(stream, group)
    pending_count = pending.get("pending", 0) if isinstance(pending, dict) else pending[0]
except Exception:
    pending_count = 0

if length != 1 or pending_count != 0:
    raise SystemExit(f"m3_pause_validation_failed xlen={length} pending={pending_count}")

print(f"m3_pause_validation_ok stream={stream} xlen={length} pending={pending_count}")
PY

if ! grep -q "fetch_queue_paused" "${LOG_FILE}"; then
  echo "m3_pause_validation_failed: 未观察到 paused 事件日志"
  cat "${LOG_FILE}"
  exit 1
fi

export CRAWLER_PAUSED="false"
printf 'false\n' >"${CRAWLER_PAUSE_FILE}"
RECOVERY_LOG_FILE="/tmp/m3-pause-recovery.$$.log"
timeout 5s python -m scrapy crawl fetch_queue -s LOG_LEVEL="${LOG_LEVEL:-INFO}" >"${RECOVERY_LOG_FILE}" 2>&1 || true

if ! grep -q "fetch_queue_invalid_message" "${RECOVERY_LOG_FILE}"; then
  echo "m3_pause_validation_failed: 恢复后未观察到 invalid message 被消费"
  cat "${RECOVERY_LOG_FILE}"
  exit 1
fi

python - <<'PY'
import os
import redis

client = redis.from_url(os.environ["FETCH_QUEUE_REDIS_URL"], decode_responses=True)
stream = os.environ["FETCH_QUEUE_STREAM"]
group = os.environ["FETCH_QUEUE_GROUP"]

pending = client.xpending(stream, group)
pending_count = pending.get("pending", 0) if isinstance(pending, dict) else pending[0]
if pending_count != 0:
    raise SystemExit(f"m3_pause_recovery_failed pending={pending_count}")
print(f"m3_pause_recovery_ok stream={stream} pending={pending_count}")
PY
