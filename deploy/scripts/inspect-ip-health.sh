#!/usr/bin/env bash
set -euo pipefail

REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
KEY_PREFIX="${REDIS_KEY_PREFIX:-crawler}"

echo "Redis: ${REDIS_URL}"
echo "黑名单 key："
redis-cli -u "${REDIS_URL}" --scan --pattern "${KEY_PREFIX}:blacklist:*"
echo
echo "全局 IP 状态 key："
redis-cli -u "${REDIS_URL}" --scan --pattern "${KEY_PREFIX}:ip:global:*"

