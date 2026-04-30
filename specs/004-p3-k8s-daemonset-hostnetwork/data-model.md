# 数据模型：P3 K8s DaemonSet + hostNetwork 生产部署基础

## 1. Crawler Node

K8s node 中具备多出口 IPv4 的爬虫执行节点。

| 字段 / 属性 | 来源 | 说明 |
|---|---|---|
| `node_name` | K8s Downward API | 节点名称，进入 consumer name、日志和指标。 |
| `node_pool_name` | OCI / OKE | M3 第一轮实测使用 `scrapy-node-pool`。 |
| `subnet` | OCI / OKE | M3 第一轮实测使用 `subnetCollection`。 |
| `labels` | K8s node label | 至少包含 crawler 调度 label：`scrapy-egress=true`。 |
| `taints` | K8s node taint | 第一轮实测暂不配置；后续生产增强隔离建议使用 `scrapy-egress=true:NoSchedule`。 |
| local IPv4 pool | host network scan | 启动时扫描并经过排除列表过滤。 |
| max IP assumption | spec | M3 暂按 50-70 个本地出口 IPv4 设计。 |

不建模云厂商 EIP、网卡生命周期或 Terraform 状态；这些属于节点基础设施层。

## 2. Crawler Pod

DaemonSet 在每个 crawler node 上运行的执行 pod。

| 字段 / 属性 | 来源 | 说明 |
|---|---|---|
| `pod_name` | K8s Downward API | pod 名称，进入 consumer name 和日志。 |
| `namespace` | K8s Downward API | 运行 namespace。 |
| `hostNetwork` | manifest | 必须为 `true`。 |
| `dnsPolicy` | manifest | `ClusterFirstWithHostNet`。 |
| `consumer_name` | env 模板 | 建议 `${NODE_NAME}-${POD_NAME}`。 |
| `prometheus_port` | ConfigMap | Prometheus 指标端口。 |
| `pause_flag` | ConfigMap / env / 后续控制面 | 停止读取新 Fetch Command 的最小停抓开关。 |

## 3. Deployment Config

运行配置分层为 Secret 与 ConfigMap / env。

### Secret 字段

| 字段 | 说明 |
|---|---|
| `FETCH_QUEUE_REDIS_URL` | 可包含 Redis 用户名和密码。 |
| `KAFKA_USERNAME` | Kafka SASL 用户名。 |
| `KAFKA_PASSWORD` | Kafka SASL 密码。 |
| `KAFKA_SSL_CA_LOCATION` 或证书挂载 | 如使用私有 CA。 |
| `OCI_CONFIG_FILE` / API key secret | 仅 `api_key` 模式需要。 |

### ConfigMap 字段

| 字段 | 说明 |
|---|---|
| `FETCH_QUEUE_STREAM` | 生产默认 `crawl:tasks`。 |
| `FETCH_QUEUE_GROUP` | 生产默认 `crawler-executor`。 |
| `FETCH_QUEUE_CONSUMER_TEMPLATE` | 建议 `${NODE_NAME}-${POD_NAME}`；最终 `FETCH_QUEUE_CONSUMER` 不作为静态 ConfigMap 值。 |
| `FETCH_QUEUE_BLOCK_MS` | 第一版建议 `1000`；空队列 SIGTERM 响应延迟约 1 秒，代价是 Redis 空轮询更频繁。 |
| `FETCH_QUEUE_READ_COUNT` | 单次读取数量。 |
| `FETCH_QUEUE_CLAIM_MIN_IDLE_MS` | 按 grace period 公式推导。 |
| `FETCH_QUEUE_MAX_DELIVERIES` | 最大投递次数。 |
| `FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS` | 退出总结窗口。 |
| `DOWNLOAD_TIMEOUT` | Scrapy 下载超时。 |
| `CONCURRENT_REQUESTS` | 全局并发，由 IP 池规模推导。 |
| `CONCURRENT_REQUESTS_PER_DOMAIN` | 单域名并发。 |
| `CRAWL_INTERFACE` | M3 生产第一版默认 `enp0s5`；`all` / `*` 仅作为显式全接口诊断能力。 |
| `EXCLUDED_LOCAL_IPS` | 不参与出口选择的本地 IP。 |
| `CRAWLER_PAUSED` | 最小停抓开关启动默认值。 |
| `CRAWLER_PAUSE_FILE` | K8s ConfigMap volume 文件路径，运行中 worker 周期读取以动态停抓。 |

## 4. IP Pool Runtime State

pod 启动时生成的节点本地 IP 池。

| 字段 | 说明 |
|---|---|
| `discovered_ips` | 从 host network 扫描得到的本地 IPv4。 |
| `excluded_ips` | 由配置排除。 |
| `active_ips` | `discovered_ips - excluded_ips - blacklisted_ips`。 |
| `blacklisted_ips` | P0 短窗口黑名单状态。 |
| `ip_count` | `active_ips` 数量，用于并发推导和指标。 |

运行期新增 / 删除 NIC 不自动生效，M3 不做周期性 rescan；需删除目标 pod，由 DaemonSet 重建后在新进程启动时重新扫描。

## 5. Queue Runtime Config

Redis Streams 常驻消费配置。

| 字段 | 生产值 | 调试值 |
|---|---|---|
| `FETCH_QUEUE_STREAM` | `crawl:tasks` | `crawl:tasks:debug:<node_name>` |
| `FETCH_QUEUE_GROUP` | `crawler-executor` | `crawler-executor-debug:<node_name>` |
| `FETCH_QUEUE_CONSUMER` | `${NODE_NAME}-${POD_NAME}` | `${NODE_NAME}-${POD_NAME}-debug` |
| `tier` | 第六类设置 | `debug` |

## 6. Debug Fetch Command Context

调试流量必须携带下游可识别上下文。

| 字段 | 要求 |
|---|---|
| `tier` | 必须为 `debug`。 |
| `job_id` | 必须可识别为 debug 任务，建议 `debug:<node_name>:<ticket_or_session>`。 |
| `command_id` | 建议 `debug:<node_name>:<sequence>`。 |
| `trace_id` | 必须可关联一次调试会话，建议 `debug:<node_name>:<yyyyMMddHHmmss>`。 |
| `host_id` / `site_id` | 有则透传；没有时第五类按 debug 规则处理。 |

## 7. Health Probe State

探针状态不直接等同外部依赖健康。

| 状态 | 来源 | 用途 |
|---|---|---|
| process alive | liveness endpoint / metrics endpoint | 判断进程是否存活。 |
| reactor alive | Scrapy / Twisted heartbeat | 判断事件循环是否卡死。 |
| consumer heartbeat | 最近一次消费循环 tick | readiness 参考。 |
| redis health | 指标 | 告警，不直接触发 liveness。 |
| kafka health | 指标 | 告警，不直接触发 liveness。 |
| object storage health | 指标 | 告警，不直接触发 liveness。 |

## 8. 不建模内容

M3 不建模：

- 第五类 facts table。
- 第三类解析任务。
- 控制平面完整策略模型。
- 云厂商网卡 / EIP 生命周期。
- Terraform / cloud-init。
