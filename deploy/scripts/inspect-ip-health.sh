#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${REDIS_URL:-}" ]]; then
  echo "错误：必须设置 REDIS_URL，格式为 redis://<username>:<url-encoded-password>@<host>:<port>/<db>"
  exit 2
fi

KEY_PREFIX="${REDIS_KEY_PREFIX:-crawler}"
VALKEY_CLI_BIN="${VALKEY_CLI:-valkey-cli}"
AUTH_WARNING="Warning: Using a password with '-a' or '-u' option on the command line interface may not be safe."

if ! command -v "${VALKEY_CLI_BIN}" >/dev/null 2>&1; then
  echo "错误：未找到 ${VALKEY_CLI_BIN}。Valkey 8.1 环境请先安装 valkey-cli，或通过 VALKEY_CLI 指定路径。"
  exit 2
fi

run_valkey() {
  "${VALKEY_CLI_BIN}" -u "${REDIS_URL}" "$@" 2> >(grep -v -F "${AUTH_WARNING}" >&2)
}

echo "Valkey client: ${VALKEY_CLI_BIN}"
echo "REDIS_URL=${REDIS_URL}"
echo "黑名单 key："
run_valkey --scan --pattern "${KEY_PREFIX}:blacklist:*"
echo
echo "全局 IP 状态 key："
run_valkey --scan --pattern "${KEY_PREFIX}:ip:global:*"
