#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SEED_FILE="${1:-${SEED_FILE:-}}"

if [[ -z "${SEED_FILE}" ]]; then
  echo "用法：$0 <seed-url-file>"
  echo "也可以通过 SEED_FILE 环境变量传入。"
  exit 2
fi

LOG_FILE="${P1_VALIDATION_LOG:-/tmp/p1-storage-failure-validation.$$.log}"
export OCI_OBJECT_STORAGE_BUCKET="${P1_FAILURE_BUCKET:-crawler-p1-missing-bucket-$(date +%Y%m%d%H%M%S)}"
export P1_VALIDATION_REPEAT="${P1_VALIDATION_REPEAT:-1}"
export P1_VALIDATION_MAX_PAGES="${P1_VALIDATION_MAX_PAGES:-1}"

echo "运行 P1 对象存储失败验证："
echo "SEED_FILE=${SEED_FILE}"
echo "OCI_OBJECT_STORAGE_BUCKET=${OCI_OBJECT_STORAGE_BUCKET}"
echo "LOG_FILE=${LOG_FILE}"

set +e
"${ROOT_DIR}/deploy/scripts/run-p1-persistence-validation.sh" "${SEED_FILE}" 2>&1 | tee "${LOG_FILE}"
status=${PIPESTATUS[0]}
set -e

if [[ "${status}" -ne 0 ]]; then
  echo "Step T037 验证失败：Scrapy 进程异常退出，status=${status}"
  exit 1
fi

if ! grep -q "p1_storage_upload_failed" "${LOG_FILE}"; then
  echo "Step T037 验证失败：未发现 p1_storage_upload_failed 日志。"
  exit 1
fi

if grep -q "p1_page_metadata_published" "${LOG_FILE}"; then
  echo "Step T037 验证失败：对象存储失败后仍发布了 page metadata。"
  exit 1
fi

echo "Step T037 验证通过：对象存储失败后未发布 page metadata。"
