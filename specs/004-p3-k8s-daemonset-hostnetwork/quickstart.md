# 快速开始：P3 K8s DaemonSet + hostNetwork 生产部署基础

本文档定义 004 的目标集群验证流程。当前 004 已从暂停状态恢复，进入 staging 等价镜像环境验证与关闭收口阶段；production 复刻属于后续发布验证，不阻塞以 staging 为口径关闭 004。

## 当前状态

**暂停日期**：2026-04-30
**恢复日期**：2026-05-03

**恢复原因**：生产部署前发现的功能性遗漏已由 005 补齐，并已在 staging OKE 等价镜像环境完成核心验证。004 现在继续执行原 M3 目标中的部署、消费、debug、pause、PEL reclaim 和 Object Storage 验证。

**staging 已记录现场**：

| 项目 | 当前值 / 状态 |
|---|---|
| node pool | `scrapy-node-pool` |
| subnet | `subnetCollection` |
| node count | `2` |
| node label | `scrapy-egress=true` |
| taint | 暂不配置 |
| host interface | `enp0s5` |
| per-node IPv4 count | `5`，即 1 个 primary + 4 个 secondary |
| staging IP range | `M3_IP_POOL_EXPECTED_RANGE=5-5` |
| production IP range | `M3_IP_POOL_EXPECTED_RANGE=60-70`，仅 production 复刻时使用 |
| namespace | `crawler-executor` |
| Redis Stream | staging PEL 已清空，`pending=0` |
| Redis Secret | `crawler-executor-redis` key 已确认 |
| Kafka Secret | `crawler-executor-kafka` key 已确认 |
| Kafka | bootstrap / broker TCP 9092 连通；producer smoke 已通过 |
| ConfigMap | 已 apply |
| DaemonSet | 已部署，staging 审计通过 |

**继续入口**：从本文 “Step 5：常驻消费验证”继续，重新投递干净 smoke 消息并补齐 `crawl_attempt` 后 `XACK`、Object Storage、debug、pause 与 PEL reclaim 证据。

## 前置条件

- P2 Redis Streams consumer group 目标节点验证通过。
- 至少 1-2 台 K8s node 具备 crawler 多出口 IPv4。
- crawler node 已打 label，并与普通 workload 隔离。
- Redis / Valkey、Kafka、OCI Object Storage 配置沿用 P2 / P1。
- 目标集群已具备 Prometheus 抓取能力或等价指标采集。

## 建议环境变量

### Secret 注入

Secret 名称和 key 以 `contracts/k8s-secrets.md` 为准，目标集群创建真实 Secret，仓库只提交引用模板。

| Secret 名称 | key | 映射环境变量 / 挂载路径 | 说明 |
|---|---|---|---|
| `crawler-executor-redis` | `fetch_queue_redis_url` | `FETCH_QUEUE_REDIS_URL` | Redis Streams Fetch Command 队列连接串。 |
| `crawler-executor-redis` | `redis_url` | `REDIS_URL` | P0 IP health / blacklist Redis 连接串；可与队列 Redis 相同。 |
| `crawler-executor-kafka` | `username` | `KAFKA_USERNAME` | Kafka SASL 用户名。 |
| `crawler-executor-kafka` | `password` | `KAFKA_PASSWORD` | Kafka SASL 密码。 |
| `crawler-executor-oci-api-key` | `config` | `/var/run/secrets/oci/config` | 仅 `OCI_AUTH_MODE=api_key` 时挂载。 |
| `crawler-executor-oci-api-key` | `oci_api_key.pem` | `/var/run/secrets/oci/oci_api_key.pem` | 仅 `OCI_AUTH_MODE=api_key` 时挂载。 |

### ConfigMap / env 注入

ConfigMap 名称和 key 以 `contracts/k8s-configmap.md` 为准。核心字段如下：

注意：004 production / staging 默认均已切换到 005 的 `EGRESS_SELECTION_STRATEGY=STICKY_POOL` / `IP_SELECTION_STRATEGY=STICKY_POOL`。`CONCURRENT_REQUESTS_PER_DOMAIN`、`DOWNLOAD_DELAY` 仅作为 Scrapy fallback 约束，`STICKY_BY_HOST` 只允许 P0 / 回退验证显式启用。

| 分类 | 字段 |
|---|---|
| queue | `FETCH_QUEUE_BACKEND`、`FETCH_QUEUE_STREAM`、`FETCH_QUEUE_GROUP`、`FETCH_QUEUE_CONSUMER_TEMPLATE`、`FETCH_QUEUE_READ_COUNT`、`FETCH_QUEUE_BLOCK_MS`、`FETCH_QUEUE_MAX_DELIVERIES`、`FETCH_QUEUE_CLAIM_MIN_IDLE_MS`、`FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS` |
| Scrapy | `CONCURRENT_REQUESTS`、`CONCURRENT_REQUESTS_PER_DOMAIN`、`DOWNLOAD_DELAY`、`DOWNLOAD_TIMEOUT`、`RETRY_ENABLED`、`RETRY_TIMES`、`FORCE_CLOSE_CONNECTIONS` |
| IP 池与 005 出口策略 | `CRAWL_INTERFACE=enp0s5`、`EXCLUDED_LOCAL_IPS`、`LOCAL_IP_POOL`、`IP_SELECTION_STRATEGY=STICKY_POOL`、`EGRESS_SELECTION_STRATEGY=STICKY_POOL`、`STICKY_POOL_SIZE`、`HOST_IP_MIN_DELAY_MS`、`LOCAL_DELAYED_BUFFER_CAPACITY`、`EXECUTION_STATE_REDIS_PREFIX` |
| P1 / Kafka 非敏感参数 | `ENABLE_P1_PERSISTENCE`、`OBJECT_STORAGE_PROVIDER`、OCI bucket / namespace / region / endpoint、Kafka bootstrap / protocol / topic / timeout |
| 运维 | `PROMETHEUS_PORT`、`LOG_LEVEL`、`CRAWLER_PAUSED`、`CRAWLER_PAUSE_FILE`、`CRAWLER_DEBUG_MODE`、debug stream / group / consumer 模板 |

`FETCH_QUEUE_CONSUMER` 不从 ConfigMap 静态下发。应用优先使用显式 `FETCH_QUEUE_CONSUMER`，否则用 `FETCH_QUEUE_CONSUMER_TEMPLATE=${NODE_NAME}-${POD_NAME}` 和 Downward API 注入的 `NODE_NAME` / `POD_NAME` 生成。

仓库提供了环境 profile：

| 文件 | 用途 |
|---|---|
| `deploy/environments/production.env` | 当前 OCI / OKE 生产候选配置：`scrapy-node-pool`、`subnetCollection`、`scrapy-egress=true`、`CRAWL_INTERFACE=enp0s5`、`M3_IP_POOL_EXPECTED_RANGE=60-70`。 |
| `deploy/environments/staging.env` | 复刻 production 功能口径：同 namespace / workload / node label key / 005 策略；仅保留 staging 物理差异，如 `M3_IP_POOL_EXPECTED_RANGE=5-5`、staging 存储与 Kafka / Redis 端点。 |

使用示例：

```bash
set -a
source deploy/environments/production.env
set +a

deploy/scripts/render-k8s-configmap-from-env.sh | kubectl -n "$M3_K8S_NAMESPACE" apply -f -
deploy/scripts/run-m3-k8s-daemonset-audit.sh
```

恢复 004 前需先执行 005 验证脚本；当前 staging 已通过，后续 production 复刻时仍需重跑：

```bash
deploy/scripts/run-m3a-config-audit.sh
deploy/scripts/run-m3a-sticky-pool-validation.sh
deploy/scripts/run-m3a-pacer-validation.sh
deploy/scripts/run-m3a-soft-ban-feedback-validation.sh
deploy/scripts/run-m3a-delayed-buffer-validation.sh
deploy/scripts/run-m3a-redis-boundary-validation.sh
```

M3 第一版建议使用以下 reclaim idle 组合：

| 参数 | 建议值 |
|---|---:|
| `terminationGracePeriodSeconds` | `30` |
| `safety_margin_ms` | `30000` |
| `FETCH_QUEUE_CLAIM_MIN_IDLE_MS` | `600000` |

如果后续调高 `terminationGracePeriodSeconds`、`MAX_LOCAL_DELAY_SECONDS`、`DOWNLOAD_TIMEOUT`、`RETRY_TIMES` 或 `KAFKA_DELIVERY_TIMEOUT_MS`，则 `FETCH_QUEUE_CLAIM_MIN_IDLE_MS` 必须重新推导。当前 `600000ms` 用于避免 005 delayed buffer / 下载重试 / Kafka delivery timeout 期间的 active PEL 被过早 `XAUTOCLAIM`。

`FETCH_QUEUE_BLOCK_MS` 第一版固定建议 `1000`。目标集群验证时需确认运行参数没有退回 `5000` 或永久阻塞；空队列手动删除 pod 时，消费循环不应被 `XREADGROUP` 阻塞超过约 1 秒。

## Step 1：节点标签与隔离检查

当前 OCI / OKE 第一轮实测配置：

| 项目 | 当前值 |
|---|---|
| node pool | `scrapy-node-pool` |
| subnet | `subnetCollection` |
| node label | `scrapy-egress=true` |
| taint | 暂不配置 |

命令示例：

```bash
kubectl get nodes --show-labels
kubectl describe node <crawler-node>
kubectl get nodes -l scrapy-egress=true -o wide
```

目标：

- crawler node 带有 `scrapy-egress=true` 调度 label。
- 普通 node 不匹配 crawler DaemonSet。
- 当前第一轮实测不要求 taint；后续进入更严格生产隔离前，再增加 `scrapy-egress=true:NoSchedule` taint 并保留 DaemonSet toleration。

## Step 2：DaemonSet dry-run

命令示例：

```bash
kubectl apply --dry-run=server -f deploy/k8s/
```

如使用当前 base 模板，可先针对 `deploy/k8s/base/configmap.yaml` 与 `deploy/k8s/base/daemonset.yaml` dry-run；真实 Secret 由目标集群侧创建，`secrets.example.yaml` 只作为 key 名称参考。

目标：

- manifest 可被 apiserver 接受。
- DaemonSet 包含 `hostNetwork: true`。
- `dnsPolicy=ClusterFirstWithHostNet`。
- `nodeSelector.scrapy-egress=true`。
- updateStrategy 为 `RollingUpdate maxUnavailable=1`。
- Secret 仅引用名称，不包含明文凭据。
- Prometheus 可通过 pod annotations 抓取 `:9410/metrics`。
- health probe 使用 `:9411/health/liveness` 与 `:9411/health/readiness`。

## Step 3：单 node 部署验证

命令示例：

```bash
kubectl apply -f deploy/k8s/
kubectl get pods -n <namespace> -o wide \
  -l app.kubernetes.io/name=crawler-executor,app.kubernetes.io/component=fetch-worker

M3_K8S_NAMESPACE=<namespace> \
M3_EXPECTED_MIN_PODS=1 \
deploy/scripts/run-m3-k8s-daemonset-audit.sh
```

目标：

- 目标 node 上运行一个 crawler pod。
- pod 运行在预期 node。
- pod 使用 host network。
- pod 暴露 Prometheus 指标端口。
- DaemonSet 配置满足 `hostNetwork=true`、`ClusterFirstWithHostNet`、`RollingUpdate maxUnavailable=1`、`terminationGracePeriodSeconds=30`。

## Step 4：IP 池发现验证

命令示例：

```bash
M3_K8S_NAMESPACE=<namespace> \
M3_CRAWL_INTERFACE="${M3_CRAWL_INTERFACE:-enp0s5}" \
M3_IP_POOL_EXPECTED_RANGE="${M3_IP_POOL_EXPECTED_RANGE:-5-5}" \
deploy/scripts/run-m3-k8s-daemonset-audit.sh

kubectl exec -n <namespace> <crawler-pod> -- \
  env CRAWL_INTERFACE=enp0s5 M3_IP_POOL_MIN_EXPECTED=1 \
  /app/deploy/scripts/inspect-k8s-ip-pool.sh

kubectl exec -n <namespace> <crawler-pod> -- \
  env CRAWL_INTERFACE=enp0s5 M3_IP_POOL_EXPECTED_RANGE="${M3_IP_POOL_EXPECTED_RANGE:-5-5}" \
  /app/deploy/scripts/inspect-k8s-ip-pool.sh

kubectl exec -n <namespace> <crawler-pod> -- \
  env CRAWL_INTERFACE=enp0s5 EXCLUDED_LOCAL_IPS=<reserved-ip> M3_IP_POOL_MIN_EXPECTED=1 \
  /app/deploy/scripts/inspect-k8s-ip-pool.sh

kubectl logs -n <namespace> <crawler-pod> | grep -E 'ip_pool|active_ips|excluded'
```

目标：

- pod 发现本 node 本地 IPv4。
- `EXCLUDED_LOCAL_IPS` 生效。
- staging `5-5` 与 production `60-70` 规模均不因固定上限失败；当前 004 staging 关闭仅要求 `5-5` 通过。
- 诊断输出中的 `all_interface_ipv4` 能反映 hostNetwork 下宿主机网卡 IPv4；`discovered_ips` 与 `CRAWL_INTERFACE=enp0s5` / `EXCLUDED_LOCAL_IPS` 一致。
- IP 规模验证时，`local_ip_pool_size` 与 `discovered_ip_count` 一致。
- 设置 `EXCLUDED_LOCAL_IPS=<reserved-ip>` 后，`discovered_ips` 中不得出现该 IP；脚本会在排除 IP 仍出现时失败。

### NIC 变更重扫验证

M3 不做运行期周期性 NIC rescan。pod 启动时扫描一次 IP 池；运行期新增 / 删除辅助 IPv4 后，必须重启对应 pod 才能生效。

命令示例：

```bash
kubectl exec -n <namespace> <crawler-pod> -- \
  env CRAWL_INTERFACE=enp0s5 M3_IP_POOL_MIN_EXPECTED=1 \
  /app/deploy/scripts/inspect-k8s-ip-pool.sh

# 运维在目标 node 上新增或删除辅助 IPv4 后，不期望存量进程自动刷新内存中的 LocalIpPool。
kubectl delete pod -n <namespace> <crawler-pod>
kubectl wait -n <namespace> --for=condition=Ready pod \
  -l app.kubernetes.io/name=crawler-executor,app.kubernetes.io/component=fetch-worker \
  --timeout=120s

kubectl exec -n <namespace> <new-crawler-pod> -- \
  env CRAWL_INTERFACE=enp0s5 M3_IP_POOL_MIN_EXPECTED=1 \
  /app/deploy/scripts/inspect-k8s-ip-pool.sh
```

目标：

- NIC 变更前的 `discovered_ips` 作为基线。
- 不要求存量进程在不重启的情况下更新 `LocalIpPool`。
- 删除 pod 后，DaemonSet 重建的新 pod 重新扫描并反映最新宿主机 IPv4。
- 如需紧急禁用某个出口 IP，优先通过更新 `EXCLUDED_LOCAL_IPS` 并重启目标 pod 生效。

## Step 5：常驻消费验证

命令示例。先确认没有旧 PEL，再投递新的 staging smoke：

```bash
POD="$(kubectl -n "$M3_K8S_NAMESPACE" get pods -l "$M3_LABEL_SELECTOR" -o jsonpath='{.items[0].metadata.name}')"

kubectl -n "$M3_K8S_NAMESPACE" exec "$POD" -- python -c 'import os,redis; r=redis.from_url(os.environ["FETCH_QUEUE_REDIS_URL"],decode_responses=True); print(r.xpending(os.environ["FETCH_QUEUE_STREAM"], os.environ["FETCH_QUEUE_GROUP"]))'

kubectl -n "$M3_K8S_NAMESPACE" exec "$POD" -- python -c 'import os,time,redis; r=redis.from_url(os.environ["FETCH_QUEUE_REDIS_URL"],decode_responses=True); stream=os.environ["FETCH_QUEUE_STREAM"]; s=int(time.time()); url=f"https://httpbin.org/status/204?m3_smoke={s}"; mid=r.xadd(stream,{"url":url,"canonical_url":url,"job_id":f"m3-staging-smoke-{s}","command_id":f"m3-staging-smoke-{s}-1","trace_id":f"m3-staging-smoke-{s}","tier":"staging-smoke"}); print("enqueued",mid,url)'

kubectl -n "$M3_K8S_NAMESPACE" logs -l "$M3_LABEL_SELECTOR" --since=5m --tail=1000 | \
  grep -E 'fetch_queue_response_observed|p1_crawl_attempt_published|p1_kafka_publish_failed|ERROR|Traceback'

kubectl -n "$M3_K8S_NAMESPACE" exec "$POD" -- python -c 'import os,redis; r=redis.from_url(os.environ["FETCH_QUEUE_REDIS_URL"],decode_responses=True); print(r.xpending(os.environ["FETCH_QUEUE_STREAM"], os.environ["FETCH_QUEUE_GROUP"]))'
```

目标：

- DaemonSet pod 从 Redis Stream 消费 Fetch Command。
- 成功发布 `crawl_attempt` 后 `XACK`。
- consumer name 包含 node / pod 身份。
- 验证完成后 PEL 应回到 `pending=0`。

### Object Storage 内容持久化验证

`httpbin /status/204` 只验证抓取、Kafka 和 XACK，不验证内容写入。004 关闭前需补一次会产生正文的 HTML 抓取，确认对象存储权限：

```bash
kubectl -n "$M3_K8S_NAMESPACE" exec "$POD" -- python -c 'import os,time,redis; r=redis.from_url(os.environ["FETCH_QUEUE_REDIS_URL"],decode_responses=True); stream=os.environ["FETCH_QUEUE_STREAM"]; s=int(time.time()); url=f"https://httpbin.org/html?m3_storage={s}"; mid=r.xadd(stream,{"url":url,"canonical_url":url,"job_id":f"m3-storage-smoke-{s}","command_id":f"m3-storage-smoke-{s}-1","trace_id":f"m3-storage-smoke-{s}","tier":"staging-storage-smoke"}); print("enqueued",mid,url)'

kubectl -n "$M3_K8S_NAMESPACE" logs -l "$M3_LABEL_SELECTOR" --since=5m --tail=1000 | \
  grep -E 'storage_result|p1_crawl_attempt_published|p1_kafka_publish_failed|ERROR|Traceback'
```

目标：

- `crawl_attempt` 中出现 `storage_result=stored` 或等价成功字段。
- 若对象存储失败，必须先修复 IAM / bucket / namespace / instance principal，再关闭 004。

## Step 6：探针与依赖抖动验证

命令示例：

```bash
deploy/scripts/run-m3-health-probe-validation.sh

M3_K8S_NAMESPACE=<namespace> \
M3_SKIP_IP_POOL_CHECK=true \
deploy/scripts/run-m3-k8s-daemonset-audit.sh

kubectl exec -n <namespace> <crawler-pod> -- \
  curl -fsS http://127.0.0.1:9411/health/liveness

kubectl exec -n <namespace> <crawler-pod> -- \
  curl -fsS http://127.0.0.1:9411/health/readiness
```

目标：

- Kafka / Redis / OCI 短暂不可达不会触发 liveness 失败。
- readiness 只依赖 worker 初始化完成和消费循环最近心跳，不因 Kafka / Redis / OCI 单次抖动失败。
- 依赖异常能在 Prometheus 指标中观察，例如 `crawler_dependency_health_status{dependency="redis|kafka|oci"}`。
- 进程或 reactor 卡死时 liveness 能失败。
- `run-m3-health-probe-validation.sh` 本地验证依赖失败指标不会改变 liveness 判定。

## Step 7：debug stream 定向验证

命令示例：

```bash
POD="$(kubectl -n "$M3_K8S_NAMESPACE" get pods -l "$M3_LABEL_SELECTOR" -o jsonpath='{.items[0].metadata.name}')"
NODE_NAME="$(kubectl -n "$M3_K8S_NAMESPACE" get pod "$POD" -o jsonpath='{.spec.nodeName}')"

kubectl -n "$M3_K8S_NAMESPACE" patch configmap crawler-executor-config \
  --type merge \
  -p '{"data":{"crawler_debug_mode":"true"}}'

kubectl -n "$M3_K8S_NAMESPACE" rollout restart daemonset "$M3_DAEMONSET_NAME"
kubectl -n "$M3_K8S_NAMESPACE" rollout status daemonset "$M3_DAEMONSET_NAME" --timeout=180s
POD="$(kubectl -n "$M3_K8S_NAMESPACE" get pods -l "$M3_LABEL_SELECTOR" --field-selector "spec.nodeName=$NODE_NAME" -o jsonpath='{.items[0].metadata.name}')"

kubectl -n "$M3_K8S_NAMESPACE" exec "$POD" -- python -c 'import os,time,redis; node=os.environ["NODE_NAME"]; r=redis.from_url(os.environ["FETCH_QUEUE_REDIS_URL"],decode_responses=True); stream=f"crawl:tasks:debug:{node}"; s=int(time.time()); url=f"https://httpbin.org/html?m3_debug={s}"; mid=r.xadd(stream,{"url":url,"canonical_url":url,"job_id":f"debug:{node}:{s}","command_id":f"debug:{node}:1","trace_id":f"debug:{node}:{s}","tier":"debug"}); print("debug_enqueued",stream,mid,url)'

kubectl -n "$M3_K8S_NAMESPACE" logs -l "$M3_LABEL_SELECTOR" --since=5m --tail=1000 | \
  grep -E 'crawl:tasks:debug|tier=debug|p1_crawl_attempt_published|p1_kafka_publish_failed|ERROR|Traceback'

kubectl -n "$M3_K8S_NAMESPACE" patch configmap crawler-executor-config \
  --type merge \
  -p '{"data":{"crawler_debug_mode":"false"}}'

kubectl -n "$M3_K8S_NAMESPACE" rollout restart daemonset "$M3_DAEMONSET_NAME"
kubectl -n "$M3_K8S_NAMESPACE" rollout status daemonset "$M3_DAEMONSET_NAME" --timeout=180s
```

目标：

- 指定 node / pod 消费 debug stream；注意当前实现需要以 `CRAWLER_DEBUG_MODE=true` 重启 pod 后才会切换到 debug stream。
- Fetch Command 携带 `tier=debug`。
- `crawl_attempt` 发布到正式 topic，事件保留 `tier=debug` / `job_id` / `trace_id`，供第五类过滤或标记。
- 调试结束后恢复 `crawl:tasks` / `crawler-executor` / `${NODE_NAME}-${POD_NAME}`。

## Step 8：手动滚动与 PEL 恢复验证

命令示例：

```bash
kubectl get pods -n <namespace> -l app.kubernetes.io/name=crawler-executor,app.kubernetes.io/component=fetch-worker -o wide
kubectl delete pod <crawler-pod>
kubectl wait -n <namespace> --for=condition=Ready pod -l app.kubernetes.io/name=crawler-executor,app.kubernetes.io/component=fetch-worker --timeout=120s

M3_K8S_NAMESPACE=<namespace> \
M3_SKIP_IP_POOL_CHECK=true \
deploy/scripts/run-m3-k8s-daemonset-audit.sh
```

目标：

- DaemonSet 重建 pod。
- 未完成消息不被清空。
- PEL 可由后续 worker reclaim。
- 允许少量重复抓取，但已 ack 消息必须已有 `crawl_attempt`。

## Step 9：pause flag 验证

命令示例：

```bash
deploy/scripts/run-m3-pause-flag-validation.sh

M3_K8S_NAMESPACE=<namespace> \
deploy/scripts/run-m3-k8s-pause-flag-validation.sh

kubectl -n <namespace> patch configmap crawler-executor-config \
  --type merge \
  -p '{"data":{"crawler_paused":"true"}}'

kubectl -n <namespace> exec <crawler-pod> -- \
  cat /etc/crawler/runtime/crawler_paused

kubectl -n <namespace> patch configmap crawler-executor-config \
  --type merge \
  -p '{"data":{"crawler_paused":"false"}}'
```

目标：

- `CRAWLER_PAUSED=true` 后 worker 停止读取新 Fetch Command。
- 已在 PEL 中的消息不被主动清空。
- `CRAWLER_PAUSED=false` 后恢复消费。
- K8s 内运行中的 pod 通过 `/etc/crawler/runtime/crawler_paused` 感知 ConfigMap volume 更新；不依赖删除 DaemonSet。

## 结果记录表

| 项目 | 目标 | 实测 | 结论 |
|---|---|---|---|
| DaemonSet 调度 | 每个 crawler node 一个 pod | staging 2 node / 2 pod 已通过 | staging 通过 |
| hostNetwork | pod 可见宿主机 IP 池 | `hostNetwork=true`、pod IP 等于 host IP 已通过 | staging 通过 |
| IP 池规模 | staging 5-5；production 60-70 | staging `enp0s5` 发现 5 个 IPv4 | staging 通过，production 待复刻 |
| 常驻消费 | Redis Streams 消费并发布 `crawl_attempt` 后 ack | 待实现后填写 | 待验证 |
| 探针 | liveness 不因依赖短暂抖动失败 | 待实现后填写 | 待验证 |
| debug stream | 指定 node / pod 消费 debug 流量 | 待实现后填写 | 待验证 |
| 手动滚动 | PEL 可恢复，允许少量重复 | 待实现后填写 | 待验证 |
| pause flag | 停止读取新消息并可恢复 | 待实现后填写 | 待验证 |
