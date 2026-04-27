#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${REDIS_URL:-}" ]]; then
  echo "错误：必须设置 REDIS_URL，格式为 redis://<username>:<url-encoded-password>@<host>:<port>/<db>"
  exit 2
fi

KEY_PREFIX="${REDIS_KEY_PREFIX:-crawler}"

echo "Redis: REDIS_URL 已配置，出于安全原因不回显连接串"
echo "黑名单 key："
redis-cli -u "${REDIS_URL}" --scan --pattern "${KEY_PREFIX}:blacklist:*"
echo
echo "全局 IP 状态 key："
redis-cli -u "${REDIS_URL}" --scan --pattern "${KEY_PREFIX}:ip:global:*"
