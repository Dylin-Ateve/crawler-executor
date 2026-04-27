#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VALKEY_CLI_BIN="${VALKEY_CLI:-valkey-cli}"
KEY_PREFIX="${REDIS_KEY_PREFIX:-crawler}"
FAILURE_THRESHOLD="${IP_FAILURE_THRESHOLD:-5}"
COOLDOWN_SECONDS="${IP_COOLDOWN_SECONDS:-1800}"
VALIDATION_URL="${P0_STEP6_URL:-https://httpbin.org/status/503}"
LOG_FILE="${P0_STEP6_LOG_FILE:-/tmp/p0-step6-valkey-blacklist.log}"

if [[ -z "${REDIS_URL:-}" ]]; then
  echo "错误：必须设置 REDIS_URL，格式为 redis://<username>:<url-encoded-password>@<host>:<port>/<db>"
  exit 2
fi

if ! command -v "${VALKEY_CLI_BIN}" >/dev/null 2>&1; then
  echo "错误：未找到 ${VALKEY_CLI_BIN}。Valkey 8.1 环境请先安装 valkey-cli，或通过 VALKEY_CLI 指定路径。"
  exit 2
fi

echo "Step 6 Redis/Valkey 黑名单验证"
echo "Valkey client: ${VALKEY_CLI_BIN}"
echo "REDIS_URL=${REDIS_URL}"
echo "REDIS_KEY_PREFIX=${KEY_PREFIX}"
echo "IP_FAILURE_THRESHOLD=${FAILURE_THRESHOLD}"
echo "IP_COOLDOWN_SECONDS=${COOLDOWN_SECONDS}"
echo "P0_STEP6_URL=${VALIDATION_URL}"
echo "P0_STEP6_LOG_FILE=${LOG_FILE}"

echo
echo "检查 Valkey 连接："
"${VALKEY_CLI_BIN}" -u "${REDIS_URL}" ping

SEED_FILE="$(mktemp /tmp/p0-step6-seeds.XXXXXX)"
printf '%s\n' "${VALIDATION_URL}" > "${SEED_FILE}"

export IP_SELECTION_STRATEGY="${IP_SELECTION_STRATEGY:-STICKY_BY_HOST}"
export FORCE_CLOSE_CONNECTIONS="${FORCE_CLOSE_CONNECTIONS:-false}"
export CONCURRENT_REQUESTS="${CONCURRENT_REQUESTS:-1}"
export CONCURRENT_REQUESTS_PER_DOMAIN="${CONCURRENT_REQUESTS_PER_DOMAIN:-1}"
export P0_VALIDATION_REPEAT="${P0_VALIDATION_REPEAT:-${FAILURE_THRESHOLD}}"
export RETRY_ENABLED="${RETRY_ENABLED:-false}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

echo
echo "运行 Scrapy 失败阈值触发验证："
echo "SEED_FILE=${SEED_FILE}"
echo "P0_VALIDATION_REPEAT=${P0_VALIDATION_REPEAT}"
echo "RETRY_ENABLED=${RETRY_ENABLED}"
echo "CONCURRENT_REQUESTS=${CONCURRENT_REQUESTS}"
echo "CONCURRENT_REQUESTS_PER_DOMAIN=${CONCURRENT_REQUESTS_PER_DOMAIN}"

"${ROOT_DIR}/deploy/scripts/run-egress-validation.sh" "${SEED_FILE}" 2>&1 | tee "${LOG_FILE}"

echo
echo "Valkey 失败计数 key："
"${VALKEY_CLI_BIN}" -u "${REDIS_URL}" --scan --pattern "${KEY_PREFIX}:fail:*" || true

echo
echo "Valkey 黑名单 key："
mapfile -t BLACKLIST_KEYS < <("${VALKEY_CLI_BIN}" -u "${REDIS_URL}" --scan --pattern "${KEY_PREFIX}:blacklist:*")
if [[ "${#BLACKLIST_KEYS[@]}" -eq 0 ]]; then
  echo "未发现黑名单 key。请检查目标是否返回 403/429/503，或确认 IP_FAILURE_THRESHOLD 与 P0_VALIDATION_REPEAT。"
  exit 1
fi

for key in "${BLACKLIST_KEYS[@]}"; do
  [[ -z "${key}" ]] && continue
  echo "key=${key}"
  echo -n "reason="
  "${VALKEY_CLI_BIN}" -u "${REDIS_URL}" get "${key}"
  echo -n "ttl="
  "${VALKEY_CLI_BIN}" -u "${REDIS_URL}" ttl "${key}"
done

echo
echo "Step 6 验证通过：已发现 Valkey 黑名单 key，并可读取 reason 与 TTL。"
