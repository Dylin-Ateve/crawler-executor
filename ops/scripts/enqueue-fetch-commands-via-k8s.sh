#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMAND_FILE="${1:-${COMMAND_FILE:-}}"
NAMESPACE="${M3_K8S_NAMESPACE:-crawler-executor}"
LABEL_SELECTOR="${M3_LABEL_SELECTOR:-app.kubernetes.io/name=crawler-executor,app.kubernetes.io/component=fetch-worker}"
POD="${ENQUEUE_POD:-}"
STREAM="${FETCH_QUEUE_STREAM:-crawl:tasks}"
DRY_RUN="${DRY_RUN:-false}"

if [[ -z "${COMMAND_FILE}" ]]; then
  echo "用法：$0 <fetch-command.jsonl>"
  exit 2
fi

if [[ ! -f "${COMMAND_FILE}" ]]; then
  echo "Fetch Command 文件不存在：${COMMAND_FILE}"
  exit 2
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "缺少 kubectl。"
  exit 2
fi

"${ROOT_DIR}/ops/scripts/validate-fetch-command-jsonl.py" "${COMMAND_FILE}"

if [[ -z "${POD}" ]]; then
  POD="$(
    kubectl -n "${NAMESPACE}" get pods -l "${LABEL_SELECTOR}" \
      -o jsonpath='{range .items[?(@.status.phase=="Running")]}{.metadata.name}{"\n"}{end}' |
      awk 'NF {print; exit}'
  )"
fi

if [[ -z "${POD}" ]]; then
  echo "未找到可用的 running crawler pod。"
  exit 1
fi

echo "enqueue_fetch_commands namespace=${NAMESPACE} pod=${POD} stream=${STREAM} file=${COMMAND_FILE} dry_run=${DRY_RUN}"

kubectl -n "${NAMESPACE}" exec -i "${POD}" -- \
  env FETCH_QUEUE_STREAM="${STREAM}" DRY_RUN="${DRY_RUN}" python -c '
import json
import os
import sys

import redis
from crawler.queues import parse_fetch_command

stream = os.environ["FETCH_QUEUE_STREAM"]
dry_run = os.environ.get("DRY_RUN", "false").lower() in {"1", "true", "yes", "on"}
redis_url = os.environ.get("FETCH_QUEUE_REDIS_URL") or os.environ.get("REDIS_URL")
if not redis_url:
    raise SystemExit("container missing FETCH_QUEUE_REDIS_URL or REDIS_URL")

client = None if dry_run else redis.from_url(redis_url, decode_responses=False)
count = 0

for line_number, raw in enumerate(sys.stdin, start=1):
    line = raw.strip()
    if not line:
        continue
    payload = json.loads(line)
    command = parse_fetch_command(payload)
    fields = {}
    for key, value in payload.items():
        if value is None:
            fields[str(key)] = ""
        elif isinstance(value, (dict, list)):
            fields[str(key)] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            fields[str(key)] = str(value)
    count += 1
    if dry_run:
        print(
            f"fetch_command_dry_run line={line_number} job_id={command.job_id} "
            f"canonical_url={command.canonical_url}"
        )
        continue
    message_id = client.xadd(stream, fields)
    if isinstance(message_id, bytes):
        message_id = message_id.decode("utf-8", errors="replace")
    print(f"fetch_command_enqueued stream={stream} message_id={message_id} job_id={command.job_id}")

print(f"fetch_command_enqueue_done stream={stream} count={count} dry_run={dry_run}")
' <"${COMMAND_FILE}"
