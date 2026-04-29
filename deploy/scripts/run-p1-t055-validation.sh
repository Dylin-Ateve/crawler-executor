#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SEED_FILE="${1:-${SEED_FILE:-/tmp/p1-t055-seeds.txt}}"

if [[ ! -f "${SEED_FILE}" ]]; then
  cat >"${SEED_FILE}" <<'EOF'
https://www.wikipedia.org/
EOF
fi

export P1_VALIDATION_REPEAT="${P1_VALIDATION_REPEAT:-1}"
export P1_VALIDATION_MAX_PAGES="${P1_VALIDATION_MAX_PAGES:-1}"

echo "运行 P1 T055 目标节点验证："
echo "ROOT_DIR=${ROOT_DIR}"
echo "SEED_FILE=${SEED_FILE}"
echo "KAFKA_TOPIC_CRAWL_ATTEMPT=${KAFKA_TOPIC_CRAWL_ATTEMPT:-crawler.crawl-attempt.v1}"
echo

"${ROOT_DIR}/deploy/scripts/p1-kafka-smoke.sh"
echo

"${ROOT_DIR}/deploy/scripts/p1-object-storage-smoke.sh"
echo

"${ROOT_DIR}/deploy/scripts/run-p1-persistence-validation.sh" "${SEED_FILE}"
echo

"${ROOT_DIR}/deploy/scripts/run-p1-storage-failure-validation.sh" "${SEED_FILE}"
echo

"${ROOT_DIR}/deploy/scripts/run-p1-kafka-failure-validation.sh" "${SEED_FILE}"
echo

echo "P1 T055 验证脚本执行完成。请根据输出确认 crawl_attempt topic、storage_result 和 storage_key 读取校验结果。"
