#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMAND_FILE="${1:-${COMMAND_FILE:-}}"

if [[ -z "${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}" ]]; then
  echo "缺少 FETCH_QUEUE_REDIS_URL 或 REDIS_URL。"
  exit 2
fi

if [[ -z "${COMMAND_FILE}" ]]; then
  COMMAND_FILE="/tmp/p2-fetch-commands.$$.jsonl"
  cat >"${COMMAND_FILE}" <<'EOF'
{"url":"https://www.wikipedia.org/","canonical_url":"https://www.wikipedia.org","job_id":"p2-sample-html","command_id":"p2-sample-1","trace_id":"p2-sample-trace"}
{"url":"https://www.wikipedia.org/static/favicon/wikipedia.ico","canonical_url":"https://www.wikipedia.org/static/favicon/wikipedia.ico","job_id":"p2-sample-non-html","command_id":"p2-sample-2","trace_id":"p2-sample-trace"}
{"url":"http://127.0.0.1:1/","canonical_url":"http://127.0.0.1:1","job_id":"p2-sample-fetch-failed","command_id":"p2-sample-3","trace_id":"p2-sample-trace"}
EOF
fi

if [[ ! -f "${COMMAND_FILE}" ]]; then
  echo "Fetch Command 文件不存在：${COMMAND_FILE}"
  exit 2
fi

export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"
export FETCH_QUEUE_REDIS_URL="${FETCH_QUEUE_REDIS_URL:-${REDIS_URL:-}}"
export FETCH_QUEUE_STREAM="${FETCH_QUEUE_STREAM:-crawl:tasks}"

python - "${COMMAND_FILE}" <<'PY'
import json
import os
import sys

import redis

command_file = sys.argv[1]
redis_url = os.environ["FETCH_QUEUE_REDIS_URL"]
stream = os.environ["FETCH_QUEUE_STREAM"]

client = redis.from_url(redis_url, decode_responses=False)
count = 0

with open(command_file, "r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{command_file}:{line_number}: JSON 解析失败：{exc}") from exc
        if not isinstance(payload, dict):
            raise SystemExit(f"{command_file}:{line_number}: 每行必须是 JSON object")

        fields = {}
        for key, value in payload.items():
            if value is None:
                fields[str(key)] = ""
            elif isinstance(value, (dict, list)):
                fields[str(key)] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            else:
                fields[str(key)] = str(value)

        message_id = client.xadd(stream, fields)
        count += 1
        if isinstance(message_id, bytes):
            message_id = message_id.decode("utf-8", errors="replace")
        print(f"p2_fetch_command_enqueued stream={stream} message_id={message_id}")

print(f"p2_fetch_command_enqueue_done stream={stream} count={count}")
PY
