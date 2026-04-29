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
LOG_FILE="${P1_VALIDATION_LOG:-/tmp/p1-persistence-validation.$$.log}"

cd "${ROOT_DIR}/src/crawler"

echo "运行 P1 持久化端到端验证："
echo "SEED_FILE=${SEED_FILE}"
echo "LOG_FILE=${LOG_FILE}"

set +e
python -m scrapy crawl content_persistence \
  -a "seed_file=${SEED_FILE}" \
  -a "repeat=${P1_VALIDATION_REPEAT:-1}" \
  -a "max_pages=${P1_VALIDATION_MAX_PAGES:-0}" \
  -s LOG_LEVEL="${LOG_LEVEL:-INFO}" 2>&1 | tee "${LOG_FILE}"
status=${PIPESTATUS[0]}
set -e

if [[ "${status}" -ne 0 ]]; then
  exit "${status}"
fi

storage_key="$(grep -o 'storage_key=[^ ]*' "${LOG_FILE}" | tail -n 1 | cut -d= -f2- || true)"
if grep -q "storage_result=stored" "${LOG_FILE}" && [[ -n "${storage_key}" ]]; then
  python -m crawler.tools.p1_verify_storage_object "${storage_key}"
fi
