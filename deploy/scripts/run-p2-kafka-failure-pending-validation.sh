#!/usr/bin/env bash
# 验证 003 spec FR-015 / FR-016 与 ADR-0008 在 Kafka 故障下的不变量：
#   1) Kafka 不可达：worker 不 XACK，消息留在 PEL；
#   2) 第二个 worker 通过 XAUTOCLAIM 接管同一消息（times_delivered 递增），仍不 ack；
#   3) Kafka 恢复：worker 完成 crawl_attempt 发布并 XACK，PEL 清空。
# 不验证"Kafka 失败达到 max_deliveries 后发终态 attempt"——按 ADR-0008，该语义只适用于 fetch 层失败。
#
# 默认使用 favicon URL 触发 non-HTML skipped pipeline 路径，避免对 OCI Object Storage 的依赖。
# 真实 Kafka 凭据（KAFKA_BOOTSTRAP_SERVERS / KAFKA_USERNAME / KAFKA_PASSWORD 等）期望
# 复用 P1 T055 验证那次的目标机环境。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMAND_FILE="${COMMAND_FILE:-/tmp/p2-kafka-failure-commands.$$.jsonl}"
LOG_DIR="${P2_KAFKA_FAILURE_LOG_DIR:-/tmp/p2-kafka-failure-validation.$$}"
LOG_PHASE1="${LOG_DIR}/phase1-kafka-down.log"
LOG_PHASE2="${LOG_DIR}/phase2-reclaim.log"
LOG_PHASE3="${LOG_DIR}/phase3-recovery.log"
PEL_LOG="${LOG_DIR}/pel-state.log"

if [[ -z "${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}" ]]; then
  echo "缺少 FETCH_QUEUE_REDIS_URL 或 REDIS_URL。"
  exit 2
fi

if [[ -z "${KAFKA_BOOTSTRAP_SERVERS:-}" ]]; then
  echo "缺少 KAFKA_BOOTSTRAP_SERVERS。Phase 3 需要复用 P1 T055 真实 Kafka 环境完成发布并 ack。"
  exit 2
fi

REAL_KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS}"
mkdir -p "${LOG_DIR}"

export FETCH_QUEUE_REDIS_URL="${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}"
export FETCH_QUEUE_STREAM="${FETCH_QUEUE_STREAM:-crawl:tasks:p2-kafka-failure-$$}"
export FETCH_QUEUE_GROUP="${FETCH_QUEUE_GROUP:-crawler-executor-p2-kafka-failure-$$}"
export FETCH_QUEUE_READ_COUNT="${FETCH_QUEUE_READ_COUNT:-1}"
export FETCH_QUEUE_BLOCK_MS="${FETCH_QUEUE_BLOCK_MS:-1000}"
# Kafka 失败不进入 max_deliveries 终态，本验证保持默认上限即可
export FETCH_QUEUE_MAX_DELIVERIES="${FETCH_QUEUE_MAX_DELIVERIES:-3}"
# 让 reclaim 阈值小到秒级，缩短验证耗时
export FETCH_QUEUE_CLAIM_MIN_IDLE_MS="${FETCH_QUEUE_CLAIM_MIN_IDLE_MS:-500}"
export ENABLE_P1_PERSISTENCE="true"
export FORCE_CLOSE_CONNECTIONS="${FORCE_CLOSE_CONNECTIONS:-false}"
export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"

# 缩短 Kafka 失败的等待时间，避免默认 120s delivery_timeout 让验证脚本卡住
export KAFKA_REQUEST_TIMEOUT_MS="${KAFKA_REQUEST_TIMEOUT_MS_OVERRIDE:-2000}"
export KAFKA_DELIVERY_TIMEOUT_MS="${KAFKA_DELIVERY_TIMEOUT_MS_OVERRIDE:-4000}"
export KAFKA_FLUSH_TIMEOUT_MS="${KAFKA_FLUSH_TIMEOUT_MS_OVERRIDE:-5000}"

cat >"${COMMAND_FILE}" <<'EOF'
{"url":"https://www.wikipedia.org/static/favicon/wikipedia.ico","canonical_url":"https://www.wikipedia.org/static/favicon/wikipedia.ico","job_id":"p2-kafka-failure","command_id":"p2-kafka-failure-1","trace_id":"p2-kafka-failure-trace"}
EOF

echo "运行 P2 Kafka 失败 + reclaim 验证："
echo "ROOT_DIR=${ROOT_DIR}"
echo "LOG_DIR=${LOG_DIR}"
echo "FETCH_QUEUE_STREAM=${FETCH_QUEUE_STREAM}"
echo "FETCH_QUEUE_GROUP=${FETCH_QUEUE_GROUP}"
echo "FETCH_QUEUE_CLAIM_MIN_IDLE_MS=${FETCH_QUEUE_CLAIM_MIN_IDLE_MS}"
echo "KAFKA_REQUEST_TIMEOUT_MS=${KAFKA_REQUEST_TIMEOUT_MS}"
echo "KAFKA_DELIVERY_TIMEOUT_MS=${KAFKA_DELIVERY_TIMEOUT_MS}"
echo "KAFKA_FLUSH_TIMEOUT_MS=${KAFKA_FLUSH_TIMEOUT_MS}"
echo

"${ROOT_DIR}/deploy/scripts/p2-enqueue-fetch-commands.sh" "${COMMAND_FILE}"
echo

read_pel_summary() {
  python - <<'PY'
import os
import sys

import redis

client = redis.from_url(os.environ["FETCH_QUEUE_REDIS_URL"], decode_responses=True)
stream = os.environ["FETCH_QUEUE_STREAM"]
group = os.environ["FETCH_QUEUE_GROUP"]
summary = client.xpending(stream, group)
if isinstance(summary, dict):
    count = int(summary.get("pending") or summary.get("count") or 0)
else:
    count = summary[0] if summary else 0
entries = client.xpending_range(stream, group, "-", "+", 100) or []
times = [int(e["times_delivered"]) for e in entries]
consumers = sorted({e.get("consumer") for e in entries if e.get("consumer")})
max_times = max(times) if times else 0
print(f"count={count} max_times_delivered={max_times} consumers={','.join(consumers)}")
PY
}

assert_no_attempt_published() {
  local log_file="$1"
  local phase_name="$2"
  if grep -q "p1_crawl_attempt_published" "${log_file}"; then
    echo "${phase_name} 失败：Kafka 不可达期间不应观察到 p1_crawl_attempt_published。"
    exit 1
  fi
}

assert_kafka_publish_failed() {
  local log_file="$1"
  local phase_name="$2"
  if ! grep -q "p1_kafka_publish_failed" "${log_file}"; then
    echo "${phase_name} 失败：未观察到 p1_kafka_publish_failed 日志。"
    exit 1
  fi
}

echo "=== Phase 1：Kafka 不可达 + 单 worker，期望不 XACK ==="
(
  set -o pipefail
  export KAFKA_BOOTSTRAP_SERVERS="127.0.0.1:1"
  export FETCH_QUEUE_CONSUMER="worker-kafka-down-a-$$"
  cd "${ROOT_DIR}/src/crawler"
  python -m scrapy crawl fetch_queue \
    -a max_messages=1 \
    -s LOG_LEVEL="${LOG_LEVEL:-INFO}" 2>&1 | tee "${LOG_PHASE1}"
)

assert_kafka_publish_failed "${LOG_PHASE1}" "Phase 1"
assert_no_attempt_published "${LOG_PHASE1}" "Phase 1"

phase1_pel="$(read_pel_summary)"
echo "Phase 1 PEL: ${phase1_pel}" | tee -a "${PEL_LOG}"
phase1_count="$(echo "${phase1_pel}" | sed -n 's/.*count=\([0-9]*\).*/\1/p')"
if [[ "${phase1_count}" != "1" ]]; then
  echo "Phase 1 失败：期望 PEL count=1，实际 ${phase1_count}。"
  exit 1
fi
echo "Phase 1 通过：Kafka 失败未 ack，消息留 PEL。"
echo

# 等待 idle 超过 claim_min_idle_ms 阈值
sleep 1

echo "=== Phase 2：第二个 worker 通过 XAUTOCLAIM 接管，Kafka 仍不可达 ==="
(
  set -o pipefail
  export KAFKA_BOOTSTRAP_SERVERS="127.0.0.1:1"
  export FETCH_QUEUE_CONSUMER="worker-kafka-down-b-$$"
  cd "${ROOT_DIR}/src/crawler"
  python -m scrapy crawl fetch_queue \
    -a max_messages=1 \
    -s LOG_LEVEL="${LOG_LEVEL:-INFO}" 2>&1 | tee "${LOG_PHASE2}"
)

assert_kafka_publish_failed "${LOG_PHASE2}" "Phase 2"
assert_no_attempt_published "${LOG_PHASE2}" "Phase 2"

phase2_pel="$(read_pel_summary)"
echo "Phase 2 PEL: ${phase2_pel}" | tee -a "${PEL_LOG}"
phase2_count="$(echo "${phase2_pel}" | sed -n 's/.*count=\([0-9]*\).*/\1/p')"
phase2_max_times="$(echo "${phase2_pel}" | sed -n 's/.*max_times_delivered=\([0-9]*\).*/\1/p')"
phase2_consumers="$(echo "${phase2_pel}" | sed -n 's/.*consumers=\([^ ]*\).*/\1/p')"

if [[ "${phase2_count}" != "1" ]]; then
  echo "Phase 2 失败：期望 PEL count=1，实际 ${phase2_count}。"
  exit 1
fi
if [[ -z "${phase2_max_times}" || "${phase2_max_times}" -lt 2 ]]; then
  echo "Phase 2 失败：期望 times_delivered≥2（reclaim 后递增），实际 ${phase2_max_times}。"
  exit 1
fi
if ! echo "${phase2_consumers}" | grep -q "worker-kafka-down-b-$$"; then
  echo "Phase 2 失败：消息未被第二个 consumer 接管，实际 consumers=${phase2_consumers}。"
  exit 1
fi
echo "Phase 2 通过：消息被 XAUTOCLAIM 接管，仍未 ack。"
echo

sleep 1

echo "=== Phase 3：Kafka 恢复，worker 完成发布并 XACK，PEL 清空 ==="
(
  set -o pipefail
  export KAFKA_BOOTSTRAP_SERVERS="${REAL_KAFKA_BOOTSTRAP_SERVERS}"
  export FETCH_QUEUE_CONSUMER="worker-kafka-recovered-c-$$"
  # 恢复阶段使用真实 Kafka 默认超时即可，但脚本内已 export override；此处保持一致避免不必要的偏差
  cd "${ROOT_DIR}/src/crawler"
  python -m scrapy crawl fetch_queue \
    -a max_messages=1 \
    -s LOG_LEVEL="${LOG_LEVEL:-INFO}" 2>&1 | tee "${LOG_PHASE3}"
)

if ! grep -q "p1_crawl_attempt_published" "${LOG_PHASE3}"; then
  echo "Phase 3 失败：Kafka 恢复后未观察到 p1_crawl_attempt_published。"
  exit 1
fi

phase3_pel="$(read_pel_summary)"
echo "Phase 3 PEL: ${phase3_pel}" | tee -a "${PEL_LOG}"
phase3_count="$(echo "${phase3_pel}" | sed -n 's/.*count=\([0-9]*\).*/\1/p')"
if [[ "${phase3_count}" != "0" ]]; then
  echo "Phase 3 失败：期望 PEL 清空（count=0），实际 ${phase3_count}。"
  exit 1
fi
echo "Phase 3 通过：Kafka 恢复后消息已 ack，PEL 清空。"

# 收尾：清理测试 stream / consumer group，避免目标机残留
python - <<'PY'
import os
import redis

client = redis.from_url(os.environ["FETCH_QUEUE_REDIS_URL"], decode_responses=True)
stream = os.environ["FETCH_QUEUE_STREAM"]
group = os.environ["FETCH_QUEUE_GROUP"]
try:
    client.xgroup_destroy(stream, group)
except Exception:
    pass
try:
    client.delete(stream)
except Exception:
    pass
PY

echo
echo "P2 Kafka 失败 + reclaim 验证全部通过。日志目录：${LOG_DIR}"
