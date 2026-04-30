#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${M3_K8S_NAMESPACE:-crawler-executor}"
CONFIGMAP="${M3_CONFIGMAP_NAME:-crawler-executor-config}"
LABEL_SELECTOR="${M3_LABEL_SELECTOR:-app.kubernetes.io/name=crawler-executor,app.kubernetes.io/component=fetch-worker}"
PAUSE_FILE="${M3_PAUSE_FILE:-/etc/crawler/runtime/crawler_paused}"
TIMEOUT_SECONDS="${M3_PAUSE_PROPAGATION_TIMEOUT_SECONDS:-90}"
POLL_SECONDS="${M3_PAUSE_PROPAGATION_POLL_SECONDS:-5}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "m3_k8s_pause_validation_failed: 缺少命令 $1"
    exit 2
  fi
}

patch_pause() {
  local value="$1"
  kubectl -n "${NAMESPACE}" patch configmap "${CONFIGMAP}" \
    --type merge \
    -p "{\"data\":{\"crawler_paused\":\"${value}\"}}" >/dev/null
}

pod_names() {
  kubectl -n "${NAMESPACE}" get pods -l "${LABEL_SELECTOR}" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
}

wait_pause_file_value() {
  local expected="$1"
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  local pods
  pods="$(pod_names)"
  if [[ -z "${pods}" ]]; then
    echo "m3_k8s_pause_validation_failed: 未找到匹配 pod"
    exit 1
  fi

  while (( SECONDS <= deadline )); do
    local mismatches=()
    while IFS= read -r pod; do
      [[ -n "${pod}" ]] || continue
      value="$(
        kubectl -n "${NAMESPACE}" exec "${pod}" -- \
          sh -c "cat '${PAUSE_FILE}' 2>/dev/null || true"
      )"
      value="$(printf '%s' "${value}" | tr -d '[:space:]')"
      if [[ "${value}" != "${expected}" ]]; then
        mismatches+=("${pod}:${value:-<empty>}")
      fi
    done <<<"${pods}"

    if (( ${#mismatches[@]} == 0 )); then
      echo "ok pause_file=${expected} pods=$(printf '%s' "${pods}" | paste -sd, -)"
      return
    fi

    sleep "${POLL_SECONDS}"
  done

  echo "m3_k8s_pause_validation_failed: pause file 未在 ${TIMEOUT_SECONDS}s 内传播到 ${expected}"
  printf 'mismatches=%s\n' "${mismatches[*]:-}"
  exit 1
}

require_cmd kubectl

echo "运行 M3 K8s pause flag 验证："
echo "NAMESPACE=${NAMESPACE}"
echo "CONFIGMAP=${CONFIGMAP}"
echo "LABEL_SELECTOR=${LABEL_SELECTOR}"
echo "PAUSE_FILE=${PAUSE_FILE}"
echo

trap 'patch_pause false >/dev/null 2>&1 || true' EXIT

patch_pause true
wait_pause_file_value true

echo "等待 worker 输出 paused 日志（若 pod 正在处理长请求，日志可能晚于 ConfigMap 文件传播）"
sleep "${POLL_SECONDS}"
kubectl -n "${NAMESPACE}" logs -l "${LABEL_SELECTOR}" --since=2m --tail=200 | grep -q "fetch_queue_paused" \
  && echo "ok fetch_queue_paused_log_observed=true" \
  || echo "warn fetch_queue_paused_log_observed=false"

patch_pause false
wait_pause_file_value false

trap - EXIT
echo "m3_k8s_pause_flag_validation_ok namespace=${NAMESPACE} configmap=${CONFIGMAP}"
