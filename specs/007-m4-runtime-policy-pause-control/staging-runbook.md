# M4 staging 验证 Runbook

**适用范围**：staging 等价镜像环境。  
**执行位置**：跳板机。  
**目标**：在 K8s DaemonSet 真实 Pod 中复跑 M4 的 policy reload / last-known-good / pause / `deadline_at` / `max_retries` / SIGTERM 停机信号，不改变 executor 只消费 Fetch Command 的边界。

## 0. 验证边界

- 只在 staging namespace 执行。
- 优先启用 `CRAWLER_DEBUG_MODE=true`，让 worker 消费 `crawl:tasks:debug:{node_name}`，避免污染真实 `crawl:tasks`。
- policy 文件通过 `crawler-executor-config.data.runtime_policy` 挂载到 `/etc/crawler/runtime/runtime_policy.json`。
- policy 文件不得包含 Redis / Kafka / OCI 凭据。
- 验证完成前不要更新 `state/current.md` 或 `state/roadmap.md`；只有实际结果收集完再写现状层。

## 1. 跳板机前置检查

```bash
cd /path/to/crawler-executor

export PYTHON_BIN="${PYTHON_BIN:-python3}"

set -a
. deploy/environments/staging.env
set +a

kubectl config current-context
kubectl -n "$M3_K8S_NAMESPACE" get daemonset "$M3_DAEMONSET_NAME"
kubectl -n "$M3_K8S_NAMESPACE" get pods -l "$M3_LABEL_SELECTOR" -o wide

export FETCH_QUEUE_REDIS_URL="$(
  kubectl -n "$M3_K8S_NAMESPACE" get secret crawler-executor-redis \
    -o jsonpath='{.data.fetch_queue_redis_url}' | base64 -d
)"
```

通过条件：

- 当前 kube context 指向 staging。
- DaemonSet 和 Pod 均存在，Pod 处于 Running。
- 目标 Pod 运行在 `scrapy-egress=true` 节点上。

## 2. 应用 M4 runtime policy 配置

首次在 staging 复跑 M4 前，需要让 Pod 获得 `RUNTIME_POLICY_*` 环境变量和 `runtime_policy.json` ConfigMap volume。

```bash
export CRAWLER_DEBUG_MODE=true

deploy/scripts/render-k8s-configmap-from-env.sh >/tmp/crawler-executor-config.m4-staging.yaml
kubectl -n "$M3_K8S_NAMESPACE" apply -f /tmp/crawler-executor-config.m4-staging.yaml

export IMAGE_REF="$(kubectl -n "$M3_K8S_NAMESPACE" get daemonset "$M3_DAEMONSET_NAME" -o jsonpath='{.spec.template.spec.containers[0].image}')"
deploy/scripts/render-k8s-daemonset-from-env.sh >/tmp/crawler-executor-daemonset.m4-staging.yaml
kubectl -n "$M3_K8S_NAMESPACE" apply -f /tmp/crawler-executor-daemonset.m4-staging.yaml

kubectl -n "$M3_K8S_NAMESPACE" rollout status "daemonset/$M3_DAEMONSET_NAME" --timeout=5m
deploy/scripts/run-m4-k8s-policy-config-audit.sh
```

通过条件：

- 审计脚本输出 `m4_k8s_policy_config_audit_ok`。
- Pod 内 `/etc/crawler/runtime/runtime_policy.json` 是合法 `schema_version=1.0` policy。

## 2.1 镜像版本检查

配置审计只证明 K8s 模板具备 M4 配置，不证明镜像内包含 M4 代码。继续行为验证前必须确认镜像内存在 runtime policy 模块和 M4 指标。

```bash
POD="$(kubectl -n "$M3_K8S_NAMESPACE" get pods -l "$M3_LABEL_SELECTOR" -o jsonpath='{.items[0].metadata.name}')"

kubectl -n "$M3_K8S_NAMESPACE" exec -i "$POD" -- python - <<'PY'
import importlib.util
import inspect

for name in ("crawler.policy_provider", "crawler.runtime_policy"):
    spec = importlib.util.find_spec(name)
    print(name, "FOUND" if spec else "MISSING", getattr(spec, "origin", ""))

from crawler.spiders.fetch_queue import FetchQueueSpider
source = inspect.getsource(FetchQueueSpider)
print("fetch_queue_has_policy_provider", "policy_provider" in source)
print("fetch_queue_has_deadline_expired", "deadline_expired" in source)

from crawler.metrics import metrics
for attr in ("policy_load_total", "policy_current_version", "policy_lkg_active", "fetch_deadline_expired_total", "shutdown_events_total"):
    print(attr, hasattr(metrics, attr))
PY
```

通过条件：

- `crawler.policy_provider FOUND`
- `crawler.runtime_policy FOUND`
- 其余检查均为 `True`

若不满足，先构建并切换 M4 镜像：

```bash
IMAGE_REF=phx.ocir.io/axfwvgxlpupm/crawler-executor:m4-staging-20260504-001 \
PUSH_IMAGE=true \
deploy/scripts/build-container-image.sh

export IMAGE_REF=phx.ocir.io/axfwvgxlpupm/crawler-executor:m4-staging-20260504-001
deploy/scripts/set-daemonset-image.sh
kubectl -n "$M3_K8S_NAMESPACE" rollout status "daemonset/$M3_DAEMONSET_NAME" --timeout=5m
```

## 3. 选择验证 Pod 与 debug stream

```bash
POD="$(kubectl -n "$M3_K8S_NAMESPACE" get pods -l "$M3_LABEL_SELECTOR" -o jsonpath='{.items[0].metadata.name}')"
NODE="$(kubectl -n "$M3_K8S_NAMESPACE" get pod "$POD" -o jsonpath='{.spec.nodeName}')"
DEBUG_STREAM="crawl:tasks:debug:${NODE}"
DEBUG_GROUP="crawler-executor-debug:${NODE}"

echo "POD=$POD"
echo "NODE=$NODE"
echo "DEBUG_STREAM=$DEBUG_STREAM"
echo "DEBUG_GROUP=$DEBUG_GROUP"
```

## 3.1 投递 debug Fetch Command helper

staging 镜像只保证包含应用运行所需文件，不保证包含全部 `deploy/scripts`。后续投递 debug command 时，直接使用 Pod 内 Python 和运行时 Redis 依赖写入 debug stream。

```bash
enqueue_debug_command() {
  local job_id="$1"
  local url="${2:-https://www.wikipedia.org/}"
  local extra_json="${3:-{}}"
  kubectl -n "$M3_K8S_NAMESPACE" exec -i "$POD" -- \
    env FETCH_QUEUE_STREAM="$DEBUG_STREAM" JOB_ID="$job_id" URL="$url" EXTRA_JSON="$extra_json" python - <<'PY'
import json
import os
import redis

stream = os.environ["FETCH_QUEUE_STREAM"]
job_id = os.environ["JOB_ID"]
url = os.environ["URL"]
extra = json.loads(os.environ["EXTRA_JSON"])
redis_url = os.environ.get("FETCH_QUEUE_REDIS_URL") or os.environ.get("REDIS_URL")

payload = {
    "url": url,
    "canonical_url": url.rstrip("/"),
    "job_id": job_id,
    "command_id": job_id,
    "trace_id": "m4-staging",
    "tier": "debug",
}
payload.update(extra)

client = redis.from_url(redis_url, decode_responses=False)
message_id = client.xadd(stream, {k: str(v) for k, v in payload.items()})
print("m4_debug_command_enqueued", message_id.decode() if isinstance(message_id, bytes) else message_id, job_id)
PY
}
```

## 4. policy reload 验证

写入 `policy-staging-m4-001`，投递一条 debug Fetch Command，让 worker 触发 provider 读取；再写入 `policy-staging-m4-002`，等待 reload interval 后再次投递。

```bash
cat >/tmp/m4-policy-v1.json <<'JSON'
{"schema_version":"1.0","version":"policy-staging-m4-001","generated_at":"2026-05-03T10:00:00Z","default_policy":{"enabled":true,"paused":false,"egress_selection_strategy":"STICKY_POOL","sticky_pool_size":4,"host_ip_min_delay_ms":2000,"host_ip_jitter_ms":500,"download_timeout_seconds":30,"max_retries":2,"max_local_delay_seconds":300}}
JSON

"$PYTHON_BIN" - <<'PY' >/tmp/m4-policy-patch.json
import json
from pathlib import Path
print(json.dumps({"data": {"runtime_policy": Path("/tmp/m4-policy-v1.json").read_text(encoding="utf-8")}}))
PY
kubectl -n "$M3_K8S_NAMESPACE" patch configmap crawler-executor-config --type merge -p "$(cat /tmp/m4-policy-patch.json)"
sleep 90

enqueue_debug_command "m4-reload:${NODE}:001"
kubectl -n "$M3_K8S_NAMESPACE" logs "$POD" --since=3m --tail=300 | grep -E 'policy-staging-m4-001|crawler_policy|p1_crawl_attempt_published|fetch_queue'
```

然后更新到 v2：

```bash
cat >/tmp/m4-policy-v2.json <<'JSON'
{"schema_version":"1.0","version":"policy-staging-m4-002","generated_at":"2026-05-03T10:05:00Z","default_policy":{"enabled":true,"paused":false,"egress_selection_strategy":"STICKY_POOL","sticky_pool_size":4,"host_ip_min_delay_ms":5000,"host_ip_jitter_ms":500,"download_timeout_seconds":30,"max_retries":2,"max_local_delay_seconds":300}}
JSON

"$PYTHON_BIN" - <<'PY' >/tmp/m4-policy-patch.json
import json
from pathlib import Path
print(json.dumps({"data": {"runtime_policy": Path("/tmp/m4-policy-v2.json").read_text(encoding="utf-8")}}))
PY
kubectl -n "$M3_K8S_NAMESPACE" patch configmap crawler-executor-config --type merge -p "$(cat /tmp/m4-policy-patch.json)"
sleep 90

enqueue_debug_command "m4-reload:${NODE}:002"
kubectl -n "$M3_K8S_NAMESPACE" exec -i "$POD" -- python - <<'PY'
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:9410/metrics", timeout=3).read().decode())
PY
```

通过条件：

- metrics 中出现 `crawler_policy_load_total{result="success"}`。
- metrics 中出现 `crawler_policy_current_version{version="policy-staging-m4-002"} 1.0`。
- Pod 未因 policy 变更重启。

## 5. last-known-good 验证

```bash
kubectl -n "$M3_K8S_NAMESPACE" patch configmap crawler-executor-config \
  --type merge \
  -p '{"data":{"runtime_policy":"{bad-json"}}'
sleep 90

enqueue_debug_command "m4-lkg:${NODE}:001"
kubectl -n "$M3_K8S_NAMESPACE" exec -i "$POD" -- python - <<'PY'
import urllib.request
metrics = urllib.request.urlopen("http://127.0.0.1:9410/metrics", timeout=3).read().decode()
for line in metrics.splitlines():
    if line.startswith(("crawler_policy_load_total", "crawler_policy_current_version", "crawler_policy_lkg_active", "crawler_policy_lkg_age_seconds")):
        print(line)
PY
```

通过条件：

- `crawler_policy_lkg_active 1.0`。
- `crawler_policy_load_total{result="validation_error"}` 增加。
- 当前 policy version 仍是上一条有效版本。

恢复有效 policy：

```bash
kubectl -n "$M3_K8S_NAMESPACE" patch configmap crawler-executor-config --type merge -p "$(cat /tmp/m4-policy-patch.json)"
sleep 90
```

## 6. pause 与 deadline 验证

写入作用域 pause policy：

```bash
cat >/tmp/m4-policy-paused.json <<'JSON'
{"schema_version":"1.0","version":"policy-staging-m4-paused","generated_at":"2026-05-03T10:10:00Z","default_policy":{"enabled":true,"paused":false,"egress_selection_strategy":"STICKY_POOL","sticky_pool_size":4,"host_ip_min_delay_ms":2000,"host_ip_jitter_ms":500,"download_timeout_seconds":30,"max_retries":2,"max_local_delay_seconds":300},"scope_policies":[{"scope_type":"policy_scope_id","scope_id":"m4-staging-paused","policy":{"paused":true,"pause_reason":"staging_validation_pause"}}]}
JSON
"$PYTHON_BIN" - <<'PY' >/tmp/m4-policy-patch.json
import json
from pathlib import Path
print(json.dumps({"data": {"runtime_policy": Path("/tmp/m4-policy-paused.json").read_text(encoding="utf-8")}}))
PY
kubectl -n "$M3_K8S_NAMESPACE" patch configmap crawler-executor-config --type merge -p "$(cat /tmp/m4-policy-patch.json)"
sleep 90
```

投递 paused 和 deadline expired 命令：

```bash
enqueue_debug_command "m4-staging-paused" "https://www.wikipedia.org/" '{"policy_scope_id":"m4-staging-paused"}'
enqueue_debug_command "m4-staging-deadline" "https://www.wikipedia.org/" '{"deadline_at":"2026-01-01T00:00:00Z"}'
sleep 20
kubectl -n "$M3_K8S_NAMESPACE" logs "$POD" --since=5m --tail=500 | grep -E 'paused|deadline_expired|p1_crawl_attempt_published'
```

通过条件：

- 日志或 Kafka 抽样中出现 `error_type=paused`。
- 日志或 Kafka 抽样中出现 `error_type=deadline_expired`。
- 对应消息最终 `XACK`，debug stream PEL 清空。

PEL 检查：

```bash
"$PYTHON_BIN" - <<PY
import os, redis
r = redis.from_url(os.environ["FETCH_QUEUE_REDIS_URL"], decode_responses=True)
print(r.xpending("$DEBUG_STREAM", "$DEBUG_GROUP"))
PY
```

## 7. max_retries 验证

投递 `max_retries=0` 的 fetch 层失败命令：

```bash
enqueue_debug_command "m4-staging-retry-zero" "http://127.0.0.1:1/" '{"max_retries":"0"}'
sleep 20
kubectl -n "$M3_K8S_NAMESPACE" logs "$POD" --since=5m --tail=500 | grep -E 'retry_exhausted|crawler_fetch_retry_terminal|p1_crawl_attempt_published'
```

通过条件：

- 第一次 fetch 层失败即进入 `error_type=retry_exhausted` terminal attempt。
- Kafka 发布成功后消息被 `XACK`。

## 8. SIGTERM / PEL 验证

选择一个 Pod 做滚动删除，观察 SIGTERM 后日志：

```bash
kubectl -n "$M3_K8S_NAMESPACE" delete pod "$POD"
kubectl -n "$M3_K8S_NAMESPACE" logs "$POD" --since=2m --tail=300 || true
kubectl -n "$M3_K8S_NAMESPACE" rollout status "daemonset/$M3_DAEMONSET_NAME" --timeout=5m
kubectl -n "$M3_K8S_NAMESPACE" logs -l "$M3_LABEL_SELECTOR" --since=5m --tail=500 | grep -E 'fetch_queue_shutdown_signal_received|fetch_queue_shutdown_loop_exit'
```

通过条件：

- 日志出现 `fetch_queue_shutdown_signal_received`。
- 日志出现 `fetch_queue_shutdown_loop_exit`。
- SIGTERM 后不再继续读取新消息或 claim 其它 pending 消息。
- 未完成消息保留 PEL，可由新 Pod 后续 reclaim。

## 9. 收尾恢复

```bash
export CRAWLER_DEBUG_MODE=false
set -a
. deploy/environments/staging.env
set +a

deploy/scripts/render-k8s-configmap-from-env.sh >/tmp/crawler-executor-config.restore-staging.yaml
kubectl -n "$M3_K8S_NAMESPACE" apply -f /tmp/crawler-executor-config.restore-staging.yaml

export IMAGE_REF="$(kubectl -n "$M3_K8S_NAMESPACE" get daemonset "$M3_DAEMONSET_NAME" -o jsonpath='{.spec.template.spec.containers[0].image}')"
deploy/scripts/render-k8s-daemonset-from-env.sh >/tmp/crawler-executor-daemonset.restore-staging.yaml
kubectl -n "$M3_K8S_NAMESPACE" apply -f /tmp/crawler-executor-daemonset.restore-staging.yaml
kubectl -n "$M3_K8S_NAMESPACE" rollout restart "daemonset/$M3_DAEMONSET_NAME"
kubectl -n "$M3_K8S_NAMESPACE" rollout status "daemonset/$M3_DAEMONSET_NAME" --timeout=5m
```

收集结果后，再把实际通过 / 失败项写入：

- `specs/007-m4-runtime-policy-pause-control/quickstart.md`
- `state/current.md`
- `state/roadmap.md`
- `state/changelog.md`
