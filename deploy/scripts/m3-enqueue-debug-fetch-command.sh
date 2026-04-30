#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NODE_NAME="${1:-${NODE_NAME:-}}"
URL="${2:-${DEBUG_URL:-https://www.wikipedia.org/}}"
CANONICAL_URL="${CANONICAL_URL:-${URL%/}}"
SESSION_ID="${DEBUG_SESSION_ID:-$(date +%Y%m%d%H%M%S)}"

if [[ -z "${NODE_NAME}" ]]; then
  echo "用法：$0 <node-name> [url]"
  echo "也可以通过 NODE_NAME / DEBUG_URL 环境变量传入。"
  exit 2
fi

COMMAND_FILE="${COMMAND_FILE:-/tmp/m3-debug-fetch-command.$$.jsonl}"
export FETCH_QUEUE_STREAM="${FETCH_QUEUE_STREAM:-crawl:tasks:debug:${NODE_NAME}}"

cat >"${COMMAND_FILE}" <<EOF
{"url":"${URL}","canonical_url":"${CANONICAL_URL}","job_id":"debug:${NODE_NAME}:${SESSION_ID}","command_id":"debug:${NODE_NAME}:1","trace_id":"debug:${NODE_NAME}:${SESSION_ID}","tier":"debug"}
EOF

"${ROOT_DIR}/deploy/scripts/p2-enqueue-fetch-commands.sh" "${COMMAND_FILE}"
