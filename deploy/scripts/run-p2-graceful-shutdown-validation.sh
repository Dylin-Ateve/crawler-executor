#!/usr/bin/env bash
# 验证 003 spec FR-022 与 ADR-0009 优雅停机不变量：
#   1) SIGTERM 触发优雅停机：worker 在 drain 时限内退出，不 ack 任何 in-flight 之外的消息。
#   2) 目标 stream XLEN 不变（不写新消息），PEL 中保留 in-flight 消息。
#   3) PEL 中消息的 times_delivered 不被本进程清零。
#   4) 日志中出现 fetch_queue_shutdown_signal_received 与 fetch_queue_shutdown_loop_exit。
#   5) SIGINT 走与 SIGTERM 同样的退出路径（FR-022 / ADR-0009 §1）。
#   6) SIGHUP 不进入优雅停机路径：进程被终止，但日志中无 shutdown_signal_received。
#
# 抓取目标使用故意慢的端点（httpbin /delay/N），确保 SIGTERM 抵达时仍有 in-flight 请求。
# 如果目标机无法访问 httpbin，可通过 P2_GRACEFUL_TARGET_URL 覆盖。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMAND_FILE="${COMMAND_FILE:-/tmp/p2-graceful-commands.$$.jsonl}"
LOG_DIR="${P2_GRACEFUL_LOG_DIR:-/tmp/p2-graceful-validation.$$}"
LOG_SIGTERM="${LOG_DIR}/sigterm.log"
LOG_SIGINT="${LOG_DIR}/sigint.log"
LOG_SIGHUP="${LOG_DIR}/sighup.log"

if [[ -z "${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}" ]]; then
  echo "缺少 FETCH_QUEUE_REDIS_URL 或 REDIS_URL。"
  exit 2
fi

mkdir -p "${LOG_DIR}"

TARGET_URL="${P2_GRACEFUL_TARGET_URL:-https://httpbin.org/delay/20}"

export FETCH_QUEUE_REDIS_URL="${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}"
export FETCH_QUEUE_STREAM="${FETCH_QUEUE_STREAM:-crawl:tasks:p2-graceful-$$}"
export FETCH_QUEUE_GROUP="${FETCH_QUEUE_GROUP:-crawler-executor-p2-graceful-$$}"
export FETCH_QUEUE_READ_COUNT="${FETCH_QUEUE_READ_COUNT:-1}"
export FETCH_QUEUE_BLOCK_MS="${FETCH_QUEUE_BLOCK_MS:-1000}"
export FETCH_QUEUE_MAX_DELIVERIES="${FETCH_QUEUE_MAX_DELIVERIES:-3}"
# drain 时限缩小到 8 秒，保持验收脚本耗时可控；K8s 生产形态仍按缺省 25 秒。
export FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS="${FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS:-8}"
export ENABLE_P1_PERSISTENCE="${ENABLE_P1_PERSISTENCE:-false}"
export FORCE_CLOSE_CONNECTIONS="${FORCE_CLOSE_CONNECTIONS:-false}"
export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"

echo "运行 P2 优雅停机验证："
echo "ROOT_DIR=${ROOT_DIR}"
echo "LOG_DIR=${LOG_DIR}"
echo "FETCH_QUEUE_STREAM=${FETCH_QUEUE_STREAM}"
echo "FETCH_QUEUE_GROUP=${FETCH_QUEUE_GROUP}"
echo "FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS=${FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS}"
echo "TARGET_URL=${TARGET_URL}"
echo

read_pel_summary() {
  python3 - <<'PY'
import os
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
max_times = max(times) if times else 0
xlen = client.xlen(stream)
print(f"count={count} max_times_delivered={max_times} xlen={xlen}")
PY
}

write_one_command() {
  local job_suffix="$1"
  cat >"${COMMAND_FILE}" <<EOF
{"url":"${TARGET_URL}","canonical_url":"${TARGET_URL}","job_id":"p2-graceful-${job_suffix}","command_id":"p2-graceful-${job_suffix}","trace_id":"p2-graceful-trace"}
EOF
}

start_worker_and_signal() {
  local consumer_name="$1"
  local log_file="$2"
  local signal="$3"
  local wait_before_signal_seconds="$4"

  (
    set -o pipefail
    export FETCH_QUEUE_CONSUMER="${consumer_name}"
    cd "${ROOT_DIR}/src/crawler"
    exec python3 -m scrapy crawl fetch_queue \
      -s LOG_LEVEL="${LOG_LEVEL:-INFO}" >"${log_file}" 2>&1
  ) &
  local pid=$!

  sleep "${wait_before_signal_seconds}"
  if ! kill -0 "${pid}" 2>/dev/null; then
    echo "worker 未存活，pid=${pid}"
    cat "${log_file}"
    return 1
  fi
  echo "向 worker 发送 ${signal} (pid=${pid})"
  kill "-${signal}" "${pid}"

  local started_at
  started_at="$(date +%s)"
  set +e
  wait "${pid}"
  local status=$?
  set -e
  local finished_at
  finished_at="$(date +%s)"
  local elapsed=$((finished_at - started_at))
  echo "worker 退出 status=${status} 耗时=${elapsed}s 信号=${signal}"
  echo "EXIT_STATUS=${status}" >>"${log_file}"
  echo "EXIT_ELAPSED=${elapsed}" >>"${log_file}"
  return 0
}

cleanup_stream() {
  python3 - <<'PY' || true
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
}

trap 'cleanup_stream' EXIT

# ---- Phase 1: SIGTERM ----------------------------------------------------
echo "=== Phase 1：SIGTERM 触发优雅停机 ==="
write_one_command "sigterm"
"${ROOT_DIR}/deploy/scripts/p2-enqueue-fetch-commands.sh" "${COMMAND_FILE}"
xlen_before_sigterm="$(python3 -c "import os, redis; c=redis.from_url(os.environ['FETCH_QUEUE_REDIS_URL'], decode_responses=True); print(c.xlen(os.environ['FETCH_QUEUE_STREAM']))")"
echo "xlen_before_sigterm=${xlen_before_sigterm}"

start_worker_and_signal "worker-sigterm-$$" "${LOG_SIGTERM}" "TERM" 3

phase1_pel="$(read_pel_summary)"
echo "Phase 1 PEL: ${phase1_pel}"

phase1_xlen="$(echo "${phase1_pel}" | sed -n 's/.*xlen=\([0-9]*\).*/\1/p')"
phase1_count="$(echo "${phase1_pel}" | sed -n 's/.*count=\([0-9]*\).*/\1/p')"
phase1_max_times="$(echo "${phase1_pel}" | sed -n 's/.*max_times_delivered=\([0-9]*\).*/\1/p')"
phase1_elapsed="$(grep '^EXIT_ELAPSED=' "${LOG_SIGTERM}" | tail -n1 | cut -d= -f2)"

if [[ "${phase1_xlen}" != "${xlen_before_sigterm}" ]]; then
  echo "Phase 1 失败：worker 改变了 stream 长度（before=${xlen_before_sigterm}, after=${phase1_xlen}）。"
  exit 1
fi

if [[ "${phase1_count}" != "1" ]]; then
  echo "Phase 1 失败：期望 PEL count=1（in-flight 留 PEL），实际 ${phase1_count}。"
  cat "${LOG_SIGTERM}"
  exit 1
fi

if [[ -z "${phase1_max_times}" || "${phase1_max_times}" -lt 1 ]]; then
  echo "Phase 1 失败：期望 times_delivered≥1，实际 ${phase1_max_times}。"
  exit 1
fi

if [[ -z "${phase1_elapsed}" || "${phase1_elapsed}" -gt $((FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS + 5)) ]]; then
  echo "Phase 1 失败：worker 退出耗时 ${phase1_elapsed}s 超过 drain 时限 ${FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS}s + 5s 容差。"
  exit 1
fi

if ! grep -q "fetch_queue_shutdown_signal_received" "${LOG_SIGTERM}"; then
  echo "Phase 1 失败：未观察到 fetch_queue_shutdown_signal_received 日志。"
  cat "${LOG_SIGTERM}"
  exit 1
fi

if ! grep -q "fetch_queue_shutdown_loop_exit" "${LOG_SIGTERM}"; then
  echo "Phase 1 失败：未观察到 fetch_queue_shutdown_loop_exit 退出总结日志。"
  cat "${LOG_SIGTERM}"
  exit 1
fi

echo "Phase 1 通过：SIGTERM 优雅停机不变量满足。"
echo

# ---- Phase 2: SIGINT (同语义) ---------------------------------------------
echo "=== Phase 2：SIGINT 走 SIGTERM 同样的退出路径 ==="
cleanup_stream
write_one_command "sigint"
"${ROOT_DIR}/deploy/scripts/p2-enqueue-fetch-commands.sh" "${COMMAND_FILE}"

start_worker_and_signal "worker-sigint-$$" "${LOG_SIGINT}" "INT" 3

phase2_pel="$(read_pel_summary)"
echo "Phase 2 PEL: ${phase2_pel}"
phase2_count="$(echo "${phase2_pel}" | sed -n 's/.*count=\([0-9]*\).*/\1/p')"
phase2_elapsed="$(grep '^EXIT_ELAPSED=' "${LOG_SIGINT}" | tail -n1 | cut -d= -f2)"

if [[ "${phase2_count}" != "1" ]]; then
  echo "Phase 2 失败：SIGINT 期望 PEL count=1（in-flight 留 PEL），实际 ${phase2_count}。"
  cat "${LOG_SIGINT}"
  exit 1
fi

if [[ -z "${phase2_elapsed}" || "${phase2_elapsed}" -gt $((FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS + 5)) ]]; then
  echo "Phase 2 失败：SIGINT 退出耗时 ${phase2_elapsed}s 超过 drain 时限 ${FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS}s + 5s 容差。"
  exit 1
fi

if ! grep -q "fetch_queue_shutdown_signal_received" "${LOG_SIGINT}"; then
  echo "Phase 2 失败：SIGINT 未触发 fetch_queue_shutdown_signal_received。"
  cat "${LOG_SIGINT}"
  exit 1
fi

echo "Phase 2 通过：SIGINT 与 SIGTERM 同语义。"
echo

# ---- Phase 3: SIGHUP (不进入优雅停机) -------------------------------------
echo "=== Phase 3：SIGHUP 不触发优雅停机路径 ==="
cleanup_stream
write_one_command "sighup"
"${ROOT_DIR}/deploy/scripts/p2-enqueue-fetch-commands.sh" "${COMMAND_FILE}"

start_worker_and_signal "worker-sighup-$$" "${LOG_SIGHUP}" "HUP" 3

# SIGHUP 默认行为是终止进程，无 graceful drain；进程应在很短时间内退出。
phase3_elapsed="$(grep '^EXIT_ELAPSED=' "${LOG_SIGHUP}" | tail -n1 | cut -d= -f2)"

if grep -q "fetch_queue_shutdown_signal_received" "${LOG_SIGHUP}"; then
  echo "Phase 3 失败：SIGHUP 不应触发 fetch_queue_shutdown_signal_received（沿用进程默认行为）。"
  cat "${LOG_SIGHUP}"
  exit 1
fi

if [[ -z "${phase3_elapsed}" || "${phase3_elapsed}" -gt $((FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS + 5)) ]]; then
  echo "Phase 3 失败：SIGHUP 后进程 ${phase3_elapsed}s 仍未退出。"
  exit 1
fi

echo "Phase 3 通过：SIGHUP 沿用进程默认行为，不进入优雅停机路径。"
echo

echo "P2 优雅停机验证全部通过。日志目录：${LOG_DIR}"
