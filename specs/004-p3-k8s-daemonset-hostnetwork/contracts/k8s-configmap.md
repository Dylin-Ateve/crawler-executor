# K8s ConfigMap 契约：P3 crawler-executor

本文档定义 M3 第一版 K8s 部署的非敏感运行参数。ConfigMap 只能包含行为参数、topic / stream 名称、超时、并发、指标和调试开关；任何凭据、完整 Redis URL、Kafka 密码、OCI 私钥或短期 token 必须走 `contracts/k8s-secrets.md`。

## ConfigMap 命名

| ConfigMap 名称 | 用途 | 是否必需 |
|---|---|---|
| `crawler-executor-config` | crawler-executor 生产运行参数 | 必需 |

## 队列消费参数

| key | 映射环境变量 | 建议值 | 说明 |
|---|---|---|---|
| `fetch_queue_backend` | `FETCH_QUEUE_BACKEND` | `redis_streams` | M3 第一版只支持 Redis Streams。 |
| `fetch_queue_stream` | `FETCH_QUEUE_STREAM` | `crawl:tasks` | 生产 Fetch Command stream。 |
| `fetch_queue_group` | `FETCH_QUEUE_GROUP` | `crawler-executor` | 生产 consumer group。 |
| `fetch_queue_consumer_template` | `FETCH_QUEUE_CONSUMER_TEMPLATE` | `${NODE_NAME}-${POD_NAME}` | consumer name 模板；最终值由 Downward API 注入的 node / pod 身份渲染。 |
| `fetch_queue_read_count` | `FETCH_QUEUE_READ_COUNT` | `10` | 单次读取数量；后续可按节点并发调优。 |
| `fetch_queue_block_ms` | `FETCH_QUEUE_BLOCK_MS` | `1000` | 阻塞读取时间；M3 选择较短 block 以降低 SIGTERM 响应延迟。 |
| `fetch_queue_max_deliveries` | `FETCH_QUEUE_MAX_DELIVERIES` | `3` | 非 Kafka publish failure 的最大投递次数。 |
| `fetch_queue_claim_min_idle_ms` | `FETCH_QUEUE_CLAIM_MIN_IDLE_MS` | `60000` | 必须满足 `terminationGracePeriodSeconds * 1000 + safety_margin_ms` 下限。 |
| `fetch_queue_shutdown_drain_seconds` | `FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS` | `25` | ADR-0011 下作为退出总结窗口，不承诺强制终止 Scrapy in-flight。 |
| `fetch_queue_max_messages` | `FETCH_QUEUE_MAX_MESSAGES` | `0` | 常驻生产消费设为 `0`，表示不按消息数自动退出。 |

`FETCH_QUEUE_CONSUMER` 不应作为静态 ConfigMap 值下发。应用优先使用显式 `FETCH_QUEUE_CONSUMER`，否则按 `FETCH_QUEUE_CONSUMER_TEMPLATE` 渲染；模板中的 `NODE_NAME` / `POD_NAME` 必须来自 Downward API，避免多个 pod 使用同一个 consumer name。

## 阻塞读取窗口

M3 第一版固定建议 `FETCH_QUEUE_BLOCK_MS=1000`。

取舍：

- 空队列时，SIGTERM / SIGINT 到达后，阻塞中的 `XREADGROUP` 最多等待约 1 秒自然返回，便于手动滚动和单 pod 调试。
- 相比 P2 / ADR-0009 早期的 `5000ms` 口径，空队列轮询频率约提升 5 倍；这是可接受的 Redis 读请求开销，用于换取更敏捷的停机响应。
- 不得设置为 `0` 或永久阻塞。永久阻塞会破坏 ADR-0004 / ADR-0009 对可退出消费循环的要求。
- 生产如需调大该值，必须同时说明 SIGTERM 响应延迟上限；不建议超过 `5000ms`。

验证要求：

- 后续 ConfigMap manifest 中 `fetch_queue_block_ms` 必须为字符串 `"1000"`。
- 目标集群验证日志中应能看到 `FETCH_QUEUE_BLOCK_MS=1000` 或等价运行参数。
- 手动删除 pod 时，若队列为空，消费循环退出不应被空队列 `XREADGROUP` 阻塞超过约 1 秒。

## Reclaim idle 推导

M3 采用 ADR-0011 的 PEL 可恢复关停姿态，`FETCH_QUEUE_CLAIM_MIN_IDLE_MS` 必须由 DaemonSet 的 `terminationGracePeriodSeconds` 推导，而不是拍固定值。

```text
FETCH_QUEUE_CLAIM_MIN_IDLE_MS >= terminationGracePeriodSeconds * 1000 + safety_margin_ms
```

第一版示例值：

| 参数 | 示例值 | 说明 |
|---|---:|---|
| `terminationGracePeriodSeconds` | `30` | 低频手动滚动，保持 K8s 默认级别 grace。 |
| `safety_margin_ms` | `30000` | 给 kubelet、网络抖动、日志 flush 和进程退出留 30 秒余量。 |
| `FETCH_QUEUE_CLAIM_MIN_IDLE_MS` | `60000` | `30 * 1000 + 30000`。 |

约束：

- 后续 DaemonSet 如果把 `terminationGracePeriodSeconds` 调高到 `N`，必须同步设置 `FETCH_QUEUE_CLAIM_MIN_IDLE_MS >= N * 1000 + 30000`。
- `FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS` 仍是退出总结窗口，不参与 reclaim idle 下限计算。
- 该公式只保证滚动 / 删除 pod 的 grace 窗口内不会过早接管 PEL；M3 选择 B，长下载、对象存储上传或 Kafka flush 超过 reclaim idle 时仍可能产生少量重复抓取，依赖 `attempt_id` 幂等和下游去重承接。
- 若未来要求严格无重复，必须重新修订 ADR-0011，并把 reclaim idle 进一步约束为覆盖下载、retry、存储、Kafka publish 和 ack 的最大处理时长。

## Scrapy 抓取与并发参数

004 当前已暂停。下表保留 M3 部署基础第一版参数，但恢复 004 前必须按 ADR-0012 重新审核并发与 politeness 参数：生产方向不再把 `CONCURRENT_REQUESTS_PER_DOMAIN` / `DOWNLOAD_DELAY` 当作主要防封模型，而应由后续新 spec 定义 sticky-pool、per-(host, ip) pacer、IP cooldown、host slowdown 和本地有界延迟。

| key | 映射环境变量 | 建议值 | 说明 |
|---|---|---|---|
| `concurrent_requests` | `CONCURRENT_REQUESTS` | 按公式推导 | 暂按 `min(ip_count * per_ip_concurrency, global_cap)`；恢复 004 前需纳入 sticky-pool 和 per-IP token / cooldown。 |
| `concurrent_requests_per_domain` | `CONCURRENT_REQUESTS_PER_DOMAIN` | `4` | 历史 / fallback 参数，不作为生产单 host 主并发上限。 |
| `download_delay` | `DOWNLOAD_DELAY` | `0.1` | 历史 / fallback 参数，不作为生产自适应防封主模型。 |
| `download_timeout` | `DOWNLOAD_TIMEOUT` | `30` | Scrapy 下载超时；M3 关停语义 B 不要求 drain 覆盖该值。 |
| `retry_enabled` | `RETRY_ENABLED` | `true` | 是否启用 Scrapy retry。 |
| `retry_times` | `RETRY_TIMES` | `2` | 与当前 Scrapy 默认验证口径一致。 |
| `force_close_connections` | `FORCE_CLOSE_CONNECTIONS` | `true` | 保持出口 IP bind 行为可观察，降低连接复用干扰。 |

## 节点 IP 池参数

| key | 映射环境变量 | 建议值 | 说明 |
|---|---|---|---|
| `crawl_interface` | `CRAWL_INTERFACE` | `enp0s5` | M3 生产第一版固定扫描 `enp0s5`；`all` / `*` 仅作为显式全接口诊断能力。 |
| `excluded_local_ips` | `EXCLUDED_LOCAL_IPS` | 按节点环境填写 | 逗号分隔，排除保留 / 禁用 / 管理 IP。 |
| `local_ip_pool` | `LOCAL_IP_POOL` | 空 | 生产默认不显式配置，优先启动时扫描；仅用于 debug 或回退。 |
| `ip_selection_strategy` | `IP_SELECTION_STRATEGY` | `STICKY_BY_HOST` | 仅作为 P0 / staging / 历史验证默认；生产恢复 004 前需由 ADR-0012 新 spec 替换为 host-aware sticky-pool。 |
| `ip_failure_threshold` | `IP_FAILURE_THRESHOLD` | `5` | 历史 IP health 参数；后续需区分 `(host, ip)`、`ip`、`host` 维度。 |
| `ip_failure_window_seconds` | `IP_FAILURE_WINDOW_SECONDS` | `300` | 历史 IP health 参数。 |
| `ip_cooldown_seconds` | `IP_COOLDOWN_SECONDS` | `1800` | 历史 IP cooldown 参数；生产需补充软封禁反馈和恢复试探。 |
| `redis_key_prefix` | `REDIS_KEY_PREFIX` | `crawler` | P0 IP health key 前缀，不包含 Redis 连接信息。 |

## P1 持久化与 Kafka 非敏感参数

| key | 映射环境变量 | 建议值 | 说明 |
|---|---|---|---|
| `enable_p1_persistence` | `ENABLE_P1_PERSISTENCE` | `true` | M3 生产常驻消费默认保留 P1 持久化链路。 |
| `object_storage_provider` | `OBJECT_STORAGE_PROVIDER` | `oci` | M3 第一版只支持 OCI。 |
| `oci_object_storage_bucket` | `OCI_OBJECT_STORAGE_BUCKET` | 目标环境填写 | bucket 名不视为凭据，但不得混入 token。 |
| `oci_object_storage_namespace` | `OCI_OBJECT_STORAGE_NAMESPACE` | 目标环境填写 | namespace 不视为凭据。 |
| `oci_object_storage_region` | `OCI_OBJECT_STORAGE_REGION` | 目标环境填写 | region 不视为凭据。 |
| `oci_object_storage_endpoint` | `OCI_OBJECT_STORAGE_ENDPOINT` | 目标环境填写 | endpoint 不视为凭据。 |
| `oci_auth_mode` | `OCI_AUTH_MODE` | `instance_principal` | M3 生产优先 instance principal。 |
| `oci_config_file` | `OCI_CONFIG_FILE` | `/var/run/secrets/oci/config` | 仅 `api_key` 模式设置。 |
| `oci_profile` | `OCI_PROFILE` | `DEFAULT` | 仅 `api_key` 模式设置。 |
| `content_compression` | `CONTENT_COMPRESSION` | `gzip` | 复用 P1 存储格式。 |
| `kafka_bootstrap_servers` | `KAFKA_BOOTSTRAP_SERVERS` | 目标环境填写 | broker 地址不含凭据时可放 ConfigMap。 |
| `kafka_security_protocol` | `KAFKA_SECURITY_PROTOCOL` | `SASL_SSL` | 非敏感协议参数。 |
| `kafka_sasl_mechanism` | `KAFKA_SASL_MECHANISM` | `SCRAM-SHA-512` | 非敏感协议参数。 |
| `kafka_ssl_ca_location` | `KAFKA_SSL_CA_LOCATION` | `/etc/pki/tls/certs/ca-bundle.crt` | 容器内 CA 路径。 |
| `kafka_topic_crawl_attempt` | `KAFKA_TOPIC_CRAWL_ATTEMPT` | `crawler.crawl-attempt.v1` | P1 / P2 既有 topic。 |
| `kafka_batch_size` | `KAFKA_BATCH_SIZE` | `100` | Kafka producer 参数。 |
| `kafka_producer_retries` | `KAFKA_PRODUCER_RETRIES` | `3` | Kafka producer 参数。 |
| `kafka_request_timeout_ms` | `KAFKA_REQUEST_TIMEOUT_MS` | `30000` | Kafka producer 参数。 |
| `kafka_delivery_timeout_ms` | `KAFKA_DELIVERY_TIMEOUT_MS` | `120000` | Kafka producer 参数。 |
| `kafka_flush_timeout_ms` | `KAFKA_FLUSH_TIMEOUT_MS` | `130000` | Kafka producer 参数。 |

## 指标、日志、debug 与 pause

| key | 映射环境变量 | 建议值 | 说明 |
|---|---|---|---|
| `prometheus_port` | `PROMETHEUS_PORT` | `9410` | Prometheus metrics endpoint。 |
| `health_port` | `HEALTH_PORT` | `9411` | K8s liveness / readiness HTTP endpoint。 |
| `readiness_max_heartbeat_age_seconds` | `READINESS_MAX_HEARTBEAT_AGE_SECONDS` | `30` | readiness 允许的最大消费循环心跳年龄。 |
| `log_level` | `LOG_LEVEL` | `INFO` | 生产默认日志级别。 |
| `crawler_paused` | `CRAWLER_PAUSED` + `/etc/crawler/runtime/crawler_paused` | `false` | 最小停抓开关；env 是启动默认值，K8s 通过 ConfigMap volume 文件让运行中 worker 周期感知变更。 |
| `crawler_pause_poll_seconds` | `CRAWLER_PAUSE_POLL_SECONDS` | `5` | pause 状态下检查退出信号的等待间隔。 |
| `crawler_debug_mode` | `CRAWLER_DEBUG_MODE` | `false` | debug stream 切换开关；T030 前先定义参数名。 |
| `debug_fetch_queue_stream_template` | `DEBUG_FETCH_QUEUE_STREAM_TEMPLATE` | `crawl:tasks:debug:{node_name}` | 指定 node debug stream 模板。 |
| `debug_fetch_queue_group_template` | `DEBUG_FETCH_QUEUE_GROUP_TEMPLATE` | `crawler-executor-debug:{node_name}` | 指定 node debug consumer group 模板。 |
| `debug_fetch_queue_consumer_template` | `DEBUG_FETCH_QUEUE_CONSUMER_TEMPLATE` | `${NODE_NAME}-${POD_NAME}-debug` | debug consumer name 模板。 |
| `debug_attempt_tier` | `DEBUG_ATTEMPT_TIER` | `debug` | debug Fetch Command 必须携带的 tier。 |

## Downward API 环境变量

以下字段不是 ConfigMap data，而是后续 DaemonSet 必须通过 Downward API 注入：

| 环境变量 | 来源 | 用途 |
|---|---|---|
| `NODE_NAME` | `spec.nodeName` | 生成 `FETCH_QUEUE_CONSUMER` 和 debug stream。 |
| `POD_NAME` | `metadata.name` | 生成 `FETCH_QUEUE_CONSUMER`。 |
| `POD_NAMESPACE` | `metadata.namespace` | 日志、指标和排障上下文。 |
| `POD_IP` | `status.podIP` | hostNetwork 下用于排障，不作为出口 IP 池来源。 |

## ConfigMap data 草案

后续 `deploy/k8s/` 模板可按如下结构创建 ConfigMap。示例只包含非敏感值和占位符。

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: crawler-executor-config
data:
  fetch_queue_backend: redis_streams
  fetch_queue_stream: crawl:tasks
  fetch_queue_group: crawler-executor
  fetch_queue_consumer_template: ${NODE_NAME}-${POD_NAME}
  fetch_queue_read_count: "10"
  fetch_queue_block_ms: "1000"
  fetch_queue_max_deliveries: "3"
  fetch_queue_claim_min_idle_ms: "60000"
  fetch_queue_shutdown_drain_seconds: "25"
  fetch_queue_max_messages: "0"
  concurrent_requests: "<min(ip_count * per_ip_concurrency, global_cap)>"
  concurrent_requests_per_domain: "4"
  download_delay: "0.1"
  download_timeout: "30"
  retry_enabled: "true"
  retry_times: "2"
  force_close_connections: "true"
  crawl_interface: enp0s5
  excluded_local_ips: ""
  local_ip_pool: ""
  ip_selection_strategy: STICKY_BY_HOST
  ip_failure_threshold: "5"
  ip_failure_window_seconds: "300"
  ip_cooldown_seconds: "1800"
  redis_key_prefix: crawler
  enable_p1_persistence: "true"
  object_storage_provider: oci
  oci_object_storage_bucket: "<bucket>"
  oci_object_storage_namespace: "<namespace>"
  oci_object_storage_region: "<region>"
  oci_object_storage_endpoint: "<endpoint>"
  oci_auth_mode: instance_principal
  content_compression: gzip
  kafka_bootstrap_servers: "<bootstrap-hosts>"
  kafka_security_protocol: SASL_SSL
  kafka_sasl_mechanism: SCRAM-SHA-512
  kafka_ssl_ca_location: /etc/pki/tls/certs/ca-bundle.crt
  kafka_topic_crawl_attempt: crawler.crawl-attempt.v1
  kafka_batch_size: "100"
  kafka_producer_retries: "3"
  kafka_request_timeout_ms: "30000"
  kafka_delivery_timeout_ms: "120000"
  kafka_flush_timeout_ms: "130000"
  prometheus_port: "9410"
  health_port: "9411"
  readiness_max_heartbeat_age_seconds: "30"
  log_level: INFO
  crawler_paused: "false"
  crawler_pause_poll_seconds: "5"
  crawler_debug_mode: "false"
  debug_fetch_queue_stream_template: crawl:tasks:debug:{node_name}
  debug_fetch_queue_group_template: crawler-executor-debug:{node_name}
  debug_fetch_queue_consumer_template: ${NODE_NAME}-${POD_NAME}-debug
  debug_attempt_tier: debug
```

## 禁止项

ConfigMap 不得包含：

- `FETCH_QUEUE_REDIS_URL`、`REDIS_URL` 或任何 Redis 密码。
- `KAFKA_USERNAME`、`KAFKA_PASSWORD` 或 Kafka token。
- OCI API 私钥、OCI config 文件内容、session token。
- `LOCAL_IP_POOL` 的生产固定列表，除非处于明确的 debug / 回退场景；生产默认应启动时扫描。

## 验证要求

T008 完成后，后续 T026 / manifest 阶段必须验证：

- ConfigMap 模板只包含本文档列出的非敏感 key。
- 所有数值类字段以字符串形式写入 ConfigMap，交由应用现有 env parser 转换。
- `FETCH_QUEUE_CONSUMER` 不来自静态 ConfigMap，而由 T009 的 node / pod 模板生成。
