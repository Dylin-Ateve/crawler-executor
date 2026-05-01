#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${M3_K8S_NAMESPACE:-crawler-executor}"
DAEMONSET="${M3_DAEMONSET_NAME:-crawler-executor}"
LABEL_SELECTOR="${M3_LABEL_SELECTOR:-app.kubernetes.io/name=crawler-executor,app.kubernetes.io/component=fetch-worker}"
NODE_SELECTOR_KEY="${M3_NODE_SELECTOR_KEY:-scrapy-egress}"
NODE_SELECTOR_VALUE="${M3_NODE_SELECTOR_VALUE:-true}"
EXPECTED_MIN_PODS="${M3_EXPECTED_MIN_PODS:-1}"
CRAWL_INTERFACE="${M3_CRAWL_INTERFACE:-enp0s5}"
IP_POOL_MIN_EXPECTED="${M3_IP_POOL_MIN_EXPECTED:-1}"
IP_POOL_EXPECTED_RANGE="${M3_IP_POOL_EXPECTED_RANGE:-}"
SKIP_HEALTH_CHECK="${M3_SKIP_HEALTH_CHECK:-false}"
SKIP_IP_POOL_CHECK="${M3_SKIP_IP_POOL_CHECK:-false}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "m3_k8s_audit_failed: 缺少命令 $1"
    exit 2
  fi
}

jsonpath() {
  kubectl -n "${NAMESPACE}" get daemonset "${DAEMONSET}" -o "jsonpath=$1"
}

daemonset_json_field() {
  local expression="$1"
  kubectl -n "${NAMESPACE}" get daemonset "${DAEMONSET}" -o json |
    python -c "import json, sys; data=json.load(sys.stdin); value=${expression}; print('' if value is None else value)"
}

assert_eq() {
  local name="$1"
  local actual="$2"
  local expected="$3"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "m3_k8s_audit_failed: ${name}=${actual}, expected=${expected}"
    exit 1
  fi
  echo "ok ${name}=${actual}"
}

assert_nonempty() {
  local name="$1"
  local actual="$2"
  if [[ -z "${actual}" ]]; then
    echo "m3_k8s_audit_failed: ${name} 为空"
    exit 1
  fi
  echo "ok ${name}=${actual}"
}

require_cmd kubectl

echo "运行 M3 K8s DaemonSet 审计："
echo "NAMESPACE=${NAMESPACE}"
echo "DAEMONSET=${DAEMONSET}"
echo "LABEL_SELECTOR=${LABEL_SELECTOR}"
echo "NODE_SELECTOR=${NODE_SELECTOR_KEY}=${NODE_SELECTOR_VALUE}"
echo "CRAWL_INTERFACE=${CRAWL_INTERFACE}"
echo

kubectl -n "${NAMESPACE}" get daemonset "${DAEMONSET}" >/dev/null

host_network="$(jsonpath '{.spec.template.spec.hostNetwork}')"
dns_policy="$(jsonpath '{.spec.template.spec.dnsPolicy}')"
update_strategy="$(jsonpath '{.spec.updateStrategy.type}')"
termination_grace="$(jsonpath '{.spec.template.spec.terminationGracePeriodSeconds}')"
node_selector="$(
  daemonset_json_field "data.get('spec', {}).get('template', {}).get('spec', {}).get('nodeSelector', {}).get('${NODE_SELECTOR_KEY}')"
)"
liveness_path="$(jsonpath '{.spec.template.spec.containers[0].livenessProbe.httpGet.path}')"
liveness_port="$(jsonpath '{.spec.template.spec.containers[0].livenessProbe.httpGet.port}')"
readiness_path="$(jsonpath '{.spec.template.spec.containers[0].readinessProbe.httpGet.path}')"
readiness_port="$(jsonpath '{.spec.template.spec.containers[0].readinessProbe.httpGet.port}')"
metrics_port_annotation="$(jsonpath '{.spec.template.metadata.annotations.prometheus\.io/port}')"
metrics_path_annotation="$(jsonpath '{.spec.template.metadata.annotations.prometheus\.io/path}')"
pause_file_env="$(jsonpath '{.spec.template.spec.containers[0].env[?(@.name=="CRAWLER_PAUSE_FILE")].value}')"
pause_config_volume="$(jsonpath '{.spec.template.spec.volumes[?(@.name=="crawler-runtime-config")].configMap.name}')"

assert_eq "hostNetwork" "${host_network}" "true"
assert_eq "dnsPolicy" "${dns_policy}" "ClusterFirstWithHostNet"
assert_eq "updateStrategy" "${update_strategy}" "OnDelete"
assert_eq "terminationGracePeriodSeconds" "${termination_grace}" "30"
assert_eq "nodeSelector.${NODE_SELECTOR_KEY}" "${node_selector}" "${NODE_SELECTOR_VALUE}"
assert_eq "liveness.path" "${liveness_path}" "/health/liveness"
assert_eq "liveness.port" "${liveness_port}" "health"
assert_eq "readiness.path" "${readiness_path}" "/health/readiness"
assert_eq "readiness.port" "${readiness_port}" "health"
assert_eq "prometheus.port" "${metrics_port_annotation}" "9410"
assert_eq "prometheus.path" "${metrics_path_annotation}" "/metrics"
assert_eq "CRAWLER_PAUSE_FILE" "${pause_file_env}" "/etc/crawler/runtime/crawler_paused"
assert_eq "pause.configMap" "${pause_config_volume}" "crawler-executor-config"

echo
echo "检查 DaemonSet pod 分布："
pod_rows="$(
  kubectl -n "${NAMESPACE}" get pods -l "${LABEL_SELECTOR}" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.nodeName}{"\t"}{.spec.hostNetwork}{"\t"}{.status.podIP}{"\t"}{.status.hostIP}{"\t"}{.status.phase}{"\n"}{end}'
)"

if [[ -z "${pod_rows}" ]]; then
  echo "m3_k8s_audit_failed: 未找到匹配 pod"
  exit 1
fi

printf '%s\n' "${pod_rows}"

pod_count="$(printf '%s\n' "${pod_rows}" | awk 'NF {count += 1} END {print count + 0}')"
if (( pod_count < EXPECTED_MIN_PODS )); then
  echo "m3_k8s_audit_failed: pod_count=${pod_count}, expected_min=${EXPECTED_MIN_PODS}"
  exit 1
fi

duplicate_nodes="$(printf '%s\n' "${pod_rows}" | awk 'NF {nodes[$2] += 1} END {for (node in nodes) if (nodes[node] > 1) print node ":" nodes[node]}')"
if [[ -n "${duplicate_nodes}" ]]; then
  echo "m3_k8s_audit_failed: 同一 node 出现多个 crawler pod: ${duplicate_nodes}"
  exit 1
fi
echo "ok one_pod_per_node pod_count=${pod_count}"

non_host_network="$(printf '%s\n' "${pod_rows}" | awk 'NF && $3 != "true" {print $1}')"
if [[ -n "${non_host_network}" ]]; then
  echo "m3_k8s_audit_failed: 以下 pod 未使用 hostNetwork: ${non_host_network}"
  exit 1
fi
echo "ok pods_hostNetwork=true"

non_running="$(printf '%s\n' "${pod_rows}" | awk 'NF && $6 != "Running" {print $1 ":" $6}')"
if [[ -n "${non_running}" ]]; then
  echo "m3_k8s_audit_failed: 以下 pod 非 Running: ${non_running}"
  exit 1
fi
echo "ok pods_running=true"

sample_pod="$(printf '%s\n' "${pod_rows}" | awk 'NF {print $1; exit}')"
assert_nonempty "sample_pod" "${sample_pod}"

if [[ "${SKIP_HEALTH_CHECK}" != "true" ]]; then
  echo
  echo "检查 ${sample_pod} health endpoint："
  kubectl -n "${NAMESPACE}" exec "${sample_pod}" -- \
    python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:9411/health/liveness", timeout=3).read().decode())'
  kubectl -n "${NAMESPACE}" exec "${sample_pod}" -- \
    python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:9411/health/readiness", timeout=3).read().decode())'
fi

if [[ "${SKIP_IP_POOL_CHECK}" != "true" ]]; then
  echo
  echo "检查 ${sample_pod} IP 池发现："
  ip_pool_env=("CRAWL_INTERFACE=${CRAWL_INTERFACE}" "M3_IP_POOL_MIN_EXPECTED=${IP_POOL_MIN_EXPECTED}")
  if [[ -n "${IP_POOL_EXPECTED_RANGE}" ]]; then
    ip_pool_env+=("M3_IP_POOL_EXPECTED_RANGE=${IP_POOL_EXPECTED_RANGE}")
  fi
  kubectl -n "${NAMESPACE}" exec "${sample_pod}" -- \
    env "${ip_pool_env[@]}" /app/deploy/scripts/inspect-k8s-ip-pool.sh
fi

echo
echo "m3_k8s_daemonset_audit_ok namespace=${NAMESPACE} daemonset=${DAEMONSET} pod_count=${pod_count} sample_pod=${sample_pod}"
