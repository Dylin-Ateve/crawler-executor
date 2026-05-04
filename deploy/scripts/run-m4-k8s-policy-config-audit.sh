#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${M3_K8S_NAMESPACE:-crawler-executor}"
DAEMONSET="${M3_DAEMONSET_NAME:-crawler-executor}"
CONFIGMAP="${M3_CONFIGMAP_NAME:-crawler-executor-config}"
LABEL_SELECTOR="${M3_LABEL_SELECTOR:-app.kubernetes.io/name=crawler-executor,app.kubernetes.io/component=fetch-worker}"
POLICY_FILE="${M4_RUNTIME_POLICY_FILE:-/etc/crawler/runtime/runtime_policy.json}"
SKIP_POD_FILE_CHECK="${M4_SKIP_POD_FILE_CHECK:-false}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "m4_k8s_policy_config_audit_failed: 缺少命令 $1"
    exit 2
  fi
}

jsonpath() {
  kubectl -n "${NAMESPACE}" get daemonset "${DAEMONSET}" -o "jsonpath=$1"
}

config_value() {
  local key="$1"
  kubectl -n "${NAMESPACE}" get configmap "${CONFIGMAP}" -o json |
    "${PYTHON_BIN}" -c "import json, sys; data=json.load(sys.stdin); print(data.get('data', {}).get('${key}', ''))"
}

assert_eq() {
  local name="$1"
  local actual="$2"
  local expected="$3"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "m4_k8s_policy_config_audit_failed: ${name}=${actual}, expected=${expected}"
    exit 1
  fi
  echo "ok ${name}=${actual}"
}

assert_nonempty() {
  local name="$1"
  local actual="$2"
  if [[ -z "${actual}" ]]; then
    echo "m4_k8s_policy_config_audit_failed: ${name} 为空"
    exit 1
  fi
  echo "ok ${name}=${actual}"
}

validate_policy_json() {
  "${PYTHON_BIN}" - "$1" <<'PY'
import json
import sys

raw = sys.argv[1]
try:
    doc = json.loads(raw)
except json.JSONDecodeError as exc:
    raise SystemExit(f"m4_k8s_policy_config_audit_failed: runtime_policy 不是合法 JSON: {exc}") from exc

for key in ("schema_version", "version", "generated_at", "default_policy"):
    if key not in doc:
        raise SystemExit(f"m4_k8s_policy_config_audit_failed: runtime_policy 缺少 {key}")
if doc["schema_version"] != "1.0":
    raise SystemExit("m4_k8s_policy_config_audit_failed: runtime_policy.schema_version 必须为 1.0")
if not isinstance(doc["default_policy"], dict):
    raise SystemExit("m4_k8s_policy_config_audit_failed: runtime_policy.default_policy 必须是 object")
print(f"ok runtime_policy.version={doc['version']}")
PY
}

require_cmd kubectl
require_cmd "${PYTHON_BIN}"

echo "运行 M4 K8s runtime policy 配置审计："
echo "NAMESPACE=${NAMESPACE}"
echo "DAEMONSET=${DAEMONSET}"
echo "CONFIGMAP=${CONFIGMAP}"
echo "POLICY_FILE=${POLICY_FILE}"
echo

kubectl -n "${NAMESPACE}" get daemonset "${DAEMONSET}" >/dev/null
kubectl -n "${NAMESPACE}" get configmap "${CONFIGMAP}" >/dev/null

provider_key="$(jsonpath '{.spec.template.spec.containers[0].env[?(@.name=="RUNTIME_POLICY_PROVIDER")].valueFrom.configMapKeyRef.key}')"
file_key="$(jsonpath '{.spec.template.spec.containers[0].env[?(@.name=="RUNTIME_POLICY_FILE")].valueFrom.configMapKeyRef.key}')"
reload_key="$(jsonpath '{.spec.template.spec.containers[0].env[?(@.name=="RUNTIME_POLICY_RELOAD_INTERVAL_SECONDS")].valueFrom.configMapKeyRef.key}')"
lkg_key="$(jsonpath '{.spec.template.spec.containers[0].env[?(@.name=="RUNTIME_POLICY_LKG_MAX_AGE_SECONDS")].valueFrom.configMapKeyRef.key}')"
policy_volume_key="$(jsonpath '{.spec.template.spec.volumes[?(@.name=="crawler-runtime-config")].configMap.items[?(@.path=="runtime_policy.json")].key}')"

assert_eq "RUNTIME_POLICY_PROVIDER.config_key" "${provider_key}" "runtime_policy_provider"
assert_eq "RUNTIME_POLICY_FILE.config_key" "${file_key}" "runtime_policy_file"
assert_eq "RUNTIME_POLICY_RELOAD_INTERVAL_SECONDS.config_key" "${reload_key}" "runtime_policy_reload_interval_seconds"
assert_eq "RUNTIME_POLICY_LKG_MAX_AGE_SECONDS.config_key" "${lkg_key}" "runtime_policy_lkg_max_age_seconds"
assert_eq "runtime_policy.volume_key" "${policy_volume_key}" "runtime_policy"

provider="$(config_value runtime_policy_provider)"
policy_file="$(config_value runtime_policy_file)"
reload_interval="$(config_value runtime_policy_reload_interval_seconds)"
lkg_age="$(config_value runtime_policy_lkg_max_age_seconds)"
policy_body="$(config_value runtime_policy)"

assert_eq "runtime_policy_provider" "${provider}" "file"
assert_eq "runtime_policy_file" "${policy_file}" "${POLICY_FILE}"
assert_nonempty "runtime_policy_reload_interval_seconds" "${reload_interval}"
assert_nonempty "runtime_policy_lkg_max_age_seconds" "${lkg_age}"
assert_nonempty "runtime_policy" "${policy_body}"
validate_policy_json "${policy_body}"

if [[ "${SKIP_POD_FILE_CHECK}" != "true" ]]; then
  sample_pod="$(
    kubectl -n "${NAMESPACE}" get pods -l "${LABEL_SELECTOR}" \
      -o jsonpath='{range .items[?(@.status.phase=="Running")]}{.metadata.name}{"\n"}{end}' |
      awk 'NF {print; exit}'
  )"
  assert_nonempty "sample_pod" "${sample_pod}"
  mounted_policy="$(
    kubectl -n "${NAMESPACE}" exec "${sample_pod}" -- sh -c "cat '${POLICY_FILE}'"
  )"
  validate_policy_json "${mounted_policy}"
fi

echo
echo "m4_k8s_policy_config_audit_ok namespace=${NAMESPACE} daemonset=${DAEMONSET} configmap=${CONFIGMAP}"
