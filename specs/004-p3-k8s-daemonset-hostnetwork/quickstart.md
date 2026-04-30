# 快速开始：P3 K8s DaemonSet + hostNetwork 生产部署基础

本文档定义 004 的目标集群验证流程。当前 004 已暂停；本文只保留已完成现场和恢复后的验证步骤，不作为立即上生产的操作指引。

## 暂停状态

**暂停日期**：2026-04-30

**暂停原因**：生产部署前发现功能性遗漏，需先通过后续新 spec 明确并补齐。004 暂停在资源准备和现场记录阶段。

**已记录现场**：

| 项目 | 当前值 / 状态 |
|---|---|
| node pool | `scrapy-node-pool` |
| subnet | `subnetCollection` |
| node count | `2` |
| node label | `scrapy-egress=true` |
| taint | 暂不配置 |
| host interface | `enp0s5` |
| per-node IPv4 count | 约 `65` |
| production IP range | `M3_IP_POOL_EXPECTED_RANGE=60-70` |
| namespace | `crawler-executor` |
| Redis TCP | `aaajqtckmia7tfijfk75vfiz4rw4goapkg3geaw2tmaaog4ogcwh6ta-p.redis.us-phoenix-1.oci.oraclecloud.com:7379` 已连通 |
| Redis PING | 待补 |
| Redis Secret | `crawler-executor-redis` key 已确认 |
| Kafka Secret | `crawler-executor-kafka` key 已确认 |
| ConfigMap | 未 apply |
| DaemonSet | 未部署 |

**恢复入口**：后续新 spec 按 ADR-0012 补齐自适应 Politeness 与出口并发控制后，从“Step 2：DaemonSet dry-run”前的 ConfigMap 审核继续，随后再执行 DaemonSet 审计、IP 池、消费、debug、pause 与 PEL 验证。

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

注意：004 当前保留的 `CONCURRENT_REQUESTS_PER_DOMAIN`、`DOWNLOAD_DELAY`、`IP_SELECTION_STRATEGY=STICKY_BY_HOST` 是 P0 / staging 口径或 fallback。恢复 004 前，必须先完成 ADR-0012 后续新 spec，把生产策略切换为 sticky-pool、per-(host, ip) pacer、IP cooldown、host slowdown 和软封禁反馈。

| 分类 | 字段 |
|---|---|
| queue | `FETCH_QUEUE_BACKEND`、`FETCH_QUEUE_STREAM`、`FETCH_QUEUE_GROUP`、`FETCH_QUEUE_CONSUMER_TEMPLATE`、`FETCH_QUEUE_READ_COUNT`、`FETCH_QUEUE_BLOCK_MS`、`FETCH_QUEUE_MAX_DELIVERIES`、`FETCH_QUEUE_CLAIM_MIN_IDLE_MS`、`FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS` |
| Scrapy | `CONCURRENT_REQUESTS`、`CONCURRENT_REQUESTS_PER_DOMAIN`、`DOWNLOAD_DELAY`、`DOWNLOAD_TIMEOUT`、`RETRY_ENABLED`、`RETRY_TIMES`、`FORCE_CLOSE_CONNECTIONS` |
| IP 池 | `CRAWL_INTERFACE=enp0s5`、`EXCLUDED_LOCAL_IPS`、`LOCAL_IP_POOL`、`IP_SELECTION_STRATEGY`、`IP_FAILURE_THRESHOLD`、`IP_FAILURE_WINDOW_SECONDS`、`IP_COOLDOWN_SECONDS` |
| P1 / Kafka 非敏感参数 | `ENABLE_P1_PERSISTENCE`、`OBJECT_STORAGE_PROVIDER`、OCI bucket / namespace / region / endpoint、Kafka bootstrap / protocol / topic / timeout |
| 运维 | `PROMETHEUS_PORT`、`LOG_LEVEL`、`CRAWLER_PAUSED`、`CRAWLER_PAUSE_FILE`、`CRAWLER_DEBUG_MODE`、debug stream / group / consumer 模板 |

`FETCH_QUEUE_CONSUMER` 不从 ConfigMap 静态下发。应用优先使用显式 `FETCH_QUEUE_CONSUMER`，否则用 `FETCH_QUEUE_CONSUMER_TEMPLATE=${NODE_NAME}-${POD_NAME}` 和 Downward API 注入的 `NODE_NAME` / `POD_NAME` 生成。

仓库提供了环境 profile：

| 文件 | 用途 |
|---|---|
| `deploy/environments/production.env` | 当前 OCI / OKE 生产候选配置：`scrapy-node-pool`、`subnetCollection`、`scrapy-egress=true`、`CRAWL_INTERFACE=enp0s5`、`M3_IP_POOL_EXPECTED_RANGE=60-70`。 |
| `deploy/environments/staging.env` | 保留早期 staging / 历史验证默认：`CRAWL_INTERFACE=ens3`、`ateve.io/crawler-egress=true`、`M3_IP_POOL_EXPECTED_RANGE=50-60`。 |

使用示例：

```bash
set -a
source deploy/environments/production.env
set +a

deploy/scripts/run-m3-k8s-daemonset-audit.sh
```

M3 第一版建议使用以下 reclaim idle 组合：

| 参数 | 建议值 |
|---|---:|
| `terminationGracePeriodSeconds` | `30` |
| `safety_margin_ms` | `30000` |
| `FETCH_QUEUE_CLAIM_MIN_IDLE_MS` | `60000` |

如果后续把 `terminationGracePeriodSeconds` 调成 `N`，则 `FETCH_QUEUE_CLAIM_MIN_IDLE_MS` 必须不小于 `N * 1000 + 30000`。

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
- updateStrategy 第一版为 `OnDelete`。
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
- DaemonSet 配置满足 `hostNetwork=true`、`ClusterFirstWithHostNet`、`OnDelete`、`terminationGracePeriodSeconds=30`。

## Step 4：IP 池发现验证

命令示例：

```bash
M3_K8S_NAMESPACE=<namespace> \
M3_CRAWL_INTERFACE="${M3_CRAWL_INTERFACE:-enp0s5}" \
M3_IP_POOL_EXPECTED_RANGE="${M3_IP_POOL_EXPECTED_RANGE:-60-70}" \
deploy/scripts/run-m3-k8s-daemonset-audit.sh

kubectl exec -n <namespace> <crawler-pod> -- \
  env CRAWL_INTERFACE=enp0s5 M3_IP_POOL_MIN_EXPECTED=1 \
  deploy/scripts/inspect-k8s-ip-pool.sh

kubectl exec -n <namespace> <crawler-pod> -- \
  env CRAWL_INTERFACE=enp0s5 M3_IP_POOL_EXPECTED_RANGE=60-70 \
  deploy/scripts/inspect-k8s-ip-pool.sh

kubectl exec -n <namespace> <crawler-pod> -- \
  env CRAWL_INTERFACE=enp0s5 EXCLUDED_LOCAL_IPS=<reserved-ip> M3_IP_POOL_MIN_EXPECTED=1 \
  deploy/scripts/inspect-k8s-ip-pool.sh

kubectl logs -n <namespace> <crawler-pod> | grep -E 'ip_pool|active_ips|excluded'
```

目标：

- pod 发现本 node 本地 IPv4。
- `EXCLUDED_LOCAL_IPS` 生效。
- 60-70 个 IP 规模下无固定上限失败。
- 诊断输出中的 `all_interface_ipv4` 能反映 hostNetwork 下宿主机网卡 IPv4；`discovered_ips` 与 `CRAWL_INTERFACE=enp0s5` / `EXCLUDED_LOCAL_IPS` 一致。
- 60-70 IP 规模验证时，`local_ip_pool_size` 与 `discovered_ip_count` 一致。
- 设置 `EXCLUDED_LOCAL_IPS=<reserved-ip>` 后，`discovered_ips` 中不得出现该 IP；脚本会在排除 IP 仍出现时失败。

### NIC 变更重扫验证

M3 不做运行期周期性 NIC rescan。pod 启动时扫描一次 IP 池；运行期新增 / 删除辅助 IPv4 后，必须重启对应 pod 才能生效。

命令示例：

```bash
kubectl exec -n <namespace> <crawler-pod> -- \
  env CRAWL_INTERFACE=enp0s5 M3_IP_POOL_MIN_EXPECTED=1 \
  deploy/scripts/inspect-k8s-ip-pool.sh

# 运维在目标 node 上新增或删除辅助 IPv4 后，不期望存量进程自动刷新内存中的 LocalIpPool。
kubectl delete pod -n <namespace> <crawler-pod>
kubectl wait -n <namespace> --for=condition=Ready pod \
  -l app.kubernetes.io/name=crawler-executor,app.kubernetes.io/component=fetch-worker \
  --timeout=120s

kubectl exec -n <namespace> <new-crawler-pod> -- \
  env CRAWL_INTERFACE=enp0s5 M3_IP_POOL_MIN_EXPECTED=1 \
  deploy/scripts/inspect-k8s-ip-pool.sh
```

目标：

- NIC 变更前的 `discovered_ips` 作为基线。
- 不要求存量进程在不重启的情况下更新 `LocalIpPool`。
- 删除 pod 后，DaemonSet 重建的新 pod 重新扫描并反映最新宿主机 IPv4。
- 如需紧急禁用某个出口 IP，优先通过更新 `EXCLUDED_LOCAL_IPS` 并重启目标 pod 生效。

## Step 5：常驻消费验证

命令示例：

```bash
deploy/scripts/p2-enqueue-fetch-commands.sh
```

目标：

- DaemonSet pod 从 Redis Stream 消费 Fetch Command。
- 成功发布 `crawl_attempt` 后 `XACK`。
- consumer name 包含 node / pod 身份。

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
deploy/scripts/m3-enqueue-debug-fetch-command.sh <node-name> https://www.wikipedia.org/

export FETCH_QUEUE_STREAM="crawl:tasks:debug:<node-name>"
export FETCH_QUEUE_GROUP="crawler-executor-debug:<node-name>"
export FETCH_QUEUE_CONSUMER="<node-name>-<pod-name>-debug"
```

目标：

- 指定 node / pod 消费 debug stream。
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
| DaemonSet 调度 | 每个 crawler node 一个 pod | 待实现后填写 | 待验证 |
| hostNetwork | pod 可见宿主机 IP 池 | 待实现后填写 | 待验证 |
| IP 池规模 | 支持 50-70 个本地出口 IPv4 | 待实现后填写 | 待验证 |
| 常驻消费 | Redis Streams 消费并发布 `crawl_attempt` 后 ack | 待实现后填写 | 待验证 |
| 探针 | liveness 不因依赖短暂抖动失败 | 待实现后填写 | 待验证 |
| debug stream | 指定 node / pod 消费 debug 流量 | 待实现后填写 | 待验证 |
| 手动滚动 | PEL 可恢复，允许少量重复 | 待实现后填写 | 待验证 |
| pause flag | 停止读取新消息并可恢复 | 待实现后填写 | 待验证 |
