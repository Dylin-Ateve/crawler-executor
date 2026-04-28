#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SEED_FILE="${1:-${SEED_FILE:-}}"

if [[ -z "${SEED_FILE}" ]]; then
  echo "用法：$0 <seed-url-file>"
  echo "也可以通过 SEED_FILE 环境变量传入。"
  exit 2
fi

LOG_FILE="${P1_VALIDATION_LOG:-/tmp/p1-kafka-failure-validation.$$.log}"
export KAFKA_BOOTSTRAP_SERVERS="${P1_FAILURE_KAFKA_BOOTSTRAP_SERVERS:-127.0.0.1:1}"
export KAFKA_PRODUCER_RETRIES="${KAFKA_PRODUCER_RETRIES:-1}"
export KAFKA_REQUEST_TIMEOUT_MS="${KAFKA_REQUEST_TIMEOUT_MS:-3000}"
export KAFKA_DELIVERY_TIMEOUT_MS="${KAFKA_DELIVERY_TIMEOUT_MS:-6000}"
export KAFKA_FLUSH_TIMEOUT_MS="${KAFKA_FLUSH_TIMEOUT_MS:-8000}"
export P1_VALIDATION_REPEAT="${P1_VALIDATION_REPEAT:-1}"
export P1_VALIDATION_MAX_PAGES="${P1_VALIDATION_MAX_PAGES:-1}"

echo "运行 P1 Kafka 失败验证："
echo "SEED_FILE=${SEED_FILE}"
echo "KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS}"
echo "KAFKA_DELIVERY_TIMEOUT_MS=${KAFKA_DELIVERY_TIMEOUT_MS}"
echo "KAFKA_FLUSH_TIMEOUT_MS=${KAFKA_FLUSH_TIMEOUT_MS}"
echo "LOG_FILE=${LOG_FILE}"

set +e
"${ROOT_DIR}/deploy/scripts/run-p1-persistence-validation.sh" "${SEED_FILE}" 2>&1 | tee "${LOG_FILE}"
status=${PIPESTATUS[0]}
set -e

if [[ "${status}" -ne 0 ]]; then
  echo "Step T038 验证失败：Scrapy 进程异常退出，status=${status}"
  exit 1
fi

if grep -q "p1_storage_upload_failed" "${LOG_FILE}"; then
  echo "Step T038 验证失败：对象存储写入失败，无法验证 Kafka 发布失败语义。"
  exit 1
fi

if ! grep -q "p1_kafka_publish_failed" "${LOG_FILE}"; then
  echo "Step T038 验证失败：未发现 p1_kafka_publish_failed 日志。"
  exit 1
fi

if grep -q "p1_page_metadata_published" "${LOG_FILE}"; then
  echo "Step T038 验证失败：Kafka 失败场景仍出现发布成功日志。"
  exit 1
fi

echo "Step T038 验证通过：对象已写入，Kafka 发布失败被记录。"
