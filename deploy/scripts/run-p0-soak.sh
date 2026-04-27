#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SEED_FILE="${1:-${SEED_FILE:-}}"
DURATION="${P0_SOAK_DURATION:-24h}"

if [[ -z "${SEED_FILE}" ]]; then
  echo "用法：$0 <seed-url-file>"
  echo "也可以通过 SEED_FILE 环境变量传入。"
  exit 2
fi

export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"
cd "${ROOT_DIR}/src/crawler"

echo "开始 P0 soak 测试，持续时间：${DURATION}"
timeout "${DURATION}" python -m scrapy crawl egress_validation -a "seed_file=${SEED_FILE}" -s LOG_LEVEL="${LOG_LEVEL:-INFO}"

