#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SEED_FILE="${1:-${SEED_FILE:-}}"

if [[ -z "${SEED_FILE}" ]]; then
  echo "用法：$0 <seed-url-file>"
  echo "也可以通过 SEED_FILE 环境变量传入。"
  exit 2
fi

export ENABLE_P1_PERSISTENCE="true"
export FORCE_CLOSE_CONNECTIONS="${FORCE_CLOSE_CONNECTIONS:-false}"
export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"

cd "${ROOT_DIR}/src/crawler"

python -m scrapy crawl content_persistence \
  -a "seed_file=${SEED_FILE}" \
  -a "repeat=${P1_VALIDATION_REPEAT:-1}" \
  -a "max_pages=${P1_VALIDATION_MAX_PAGES:-0}" \
  -s LOG_LEVEL="${LOG_LEVEL:-INFO}"
