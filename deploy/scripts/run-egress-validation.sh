#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SEED_FILE="${1:-${SEED_FILE:-}}"

if [[ -z "${SEED_FILE}" ]]; then
  echo "用法：$0 <seed-url-file>"
  echo "也可以通过 SEED_FILE 环境变量传入。"
  exit 2
fi

export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"
cd "${ROOT_DIR}/src/crawler"

python -m scrapy crawl egress_validation -a "seed_file=${SEED_FILE}" -s LOG_LEVEL="${LOG_LEVEL:-INFO}"

