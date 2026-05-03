# 指标契约：M3a 自适应 Politeness 与出口并发控制

本文档定义 005 新增 Prometheus 指标。指标属于执行层运营指标，不是第五类事实层。

## Label 约束

推荐 label：

- `host_hash`
- `egress_identity_hash`
- `egress_identity_type`
- `signal_type`
- `reason`
- `strategy`
- `dimension`
- `asn` / `cidr_hash`（可选）

禁止 label：

- Redis / Kafka / OCI 凭据。
- 完整 URL。
- 完整响应 body。
- 高基数 trace id 作为常驻指标 label。

## Runtime 监控维度总览

spec005 关闭时，runtime 自适应防封禁监控已经覆盖以下维度：

| 维度 | 主要指标 | 说明 |
|---|---|---|
| host + egress IP 请求结果 | `crawler_requests_total{host,status,egress_ip}` | 观察某 host 在某出口 IP 上的 2xx / 429 / 5xx / timeout / download failed 分布。 |
| host + egress IP 响应耗时 | `crawler_response_duration_seconds{host,egress_ip}` | 判断目标 host 与出口 IP 组合是否存在延迟异常。 |
| 本地 IP 池规模 | `crawler_ip_active_count` | 当前 worker 可用本地出口 IP 数。 |
| 短窗口黑名单规模 | `crawler_ip_blacklist_count` | 当前旧 IP health 逻辑下黑名单 host/IP 对数量。 |
| 出口身份选择 | `crawler_egress_identity_selected_total{strategy,egress_identity_type}` | 观察 sticky-pool 下出口身份被选中的次数。 |
| sticky-pool 分配 | `crawler_sticky_pool_assignments_total{strategy}`、`crawler_sticky_pool_size{strategy}` | 观察候选池生成频率和实际 K 值。 |
| 出口身份不可用 | `crawler_egress_identity_unavailable_total{reason}` | 观察 IP cooldown 等原因导致候选不可用的次数。 |
| pacer 延迟 | `crawler_pacer_delay_seconds{reason}` | 观察 `(host, egress_identity)` pacing 导致的等待时间。 |
| delayed buffer 状态 | `crawler_delayed_buffer_size{consumer}`、`crawler_delayed_buffer_oldest_age_seconds{consumer}`、`crawler_delayed_buffer_full_total{consumer}`、`crawler_xreadgroup_suppressed_total{reason}` | 观察本地有界延迟和反压是否触发。 |
| 反馈信号 | `crawler_feedback_signal_total{signal_type,dimension}` | 观察 429、challenge、反爬 200、timeout、连接失败、5xx 等信号及其作用维度。 |
| `(host, ip)` backoff | `crawler_host_ip_backoff_active{reason}`、`crawler_host_ip_backoff_seconds{reason}` | 观察某 host + 出口身份组合的短窗口退避。 |
| IP cooldown | `crawler_ip_cooldown_active{reason}`、`crawler_ip_cooldown_total{reason}` | 观察某出口身份跨 host challenge 等触发的 cooldown。 |
| host slowdown | `crawler_host_slowdown_active{reason}`、`crawler_host_slowdown_total{reason}` | 观察某 host 跨多个出口身份集中 challenge 后的整体降速。 |
| host + ASN soft limit | `crawler_host_asn_soft_limit_total{asn,reason}` | 可选 ASN 维度软限制观测。 |
| Redis 执行态读写 | `crawler_execution_state_write_total{state_type,result}`、`crawler_execution_state_read_total{state_type,result}`、`crawler_execution_state_ttl_seconds{state_type}` | 观察短窗口执行安全状态的读写、失败和 TTL。 |
| Redis 边界审计 | `crawler_execution_state_forbidden_key_detected_total{pattern}` | 发现禁止 key pattern 时计数；正常运行不应增加。 |
| 依赖健康 | `crawler_dependency_health_status{dependency}`、`crawler_dependency_health_events_total{dependency,result}` | 辅助判断 Redis / Kafka / OCI 是否影响 ack 和反馈闭环。 |

典型排障口径：

- `crawler_egress_identity_selected_total` 增长，但 `crawler_requests_total` 不增长：优先检查 downloader / bindaddress / 出网路径。
- `crawler_requests_total` 有 204，但 `crawler_kafka_publishes_total{result="success"}` 不增长且 PEL 不清：优先检查 Kafka producer、topic、ACL 或 CA。
- `crawler_pacer_delay_seconds` 和 `crawler_delayed_buffer_size` 同时增长：说明 pacing 正在压制读取或执行，需要看 host/IP 是否过热。
- `crawler_feedback_signal_total`、cooldown / slowdown 指标持续增长：说明目标 host 或出口身份正在触发防封闭环，应降低相关策略参数或检查目标站点响应。

## Sticky-pool

| 指标 | 类型 | label | 说明 |
|---|---|---|---|
| `crawler_sticky_pool_assignments_total` | counter | `strategy` | sticky-pool 生成次数。 |
| `crawler_sticky_pool_size` | histogram | `strategy` | 实际候选池大小。 |
| `crawler_egress_identity_selected_total` | counter | `strategy`, `egress_identity_type` | 出口身份选择次数。 |
| `crawler_egress_identity_unavailable_total` | counter | `reason` | 候选身份不可用次数。 |

## Pacer 与 delayed buffer

| 指标 | 类型 | label | 说明 |
|---|---|---|---|
| `crawler_pacer_delay_seconds` | histogram | `reason` | 请求因 pacer / cooldown / slowdown 延迟的秒数。 |
| `crawler_delayed_buffer_size` | gauge | `consumer` | 本地 delayed buffer 当前长度。 |
| `crawler_delayed_buffer_oldest_age_seconds` | gauge | `consumer` | 最老 delayed 消息年龄。 |
| `crawler_delayed_buffer_full_total` | counter | `consumer` | buffer 满导致停止读取的次数。 |
| `crawler_delayed_message_expired_total` | counter | `reason` | 超过 `MAX_LOCAL_DELAY_SECONDS` 的 delayed 消息数。 |
| `crawler_xreadgroup_suppressed_total` | counter | `reason` | 因 buffer 满或 pause 而跳过 `XREADGROUP` 的次数。 |

## Soft-ban 与退避

| 指标 | 类型 | label | 说明 |
|---|---|---|---|
| `crawler_feedback_signal_total` | counter | `signal_type`, `dimension` | 归一化反馈信号数量。 |
| `crawler_host_ip_backoff_active` | gauge | `reason` | 活跃 `(host, ip)` backoff 数。 |
| `crawler_host_ip_backoff_seconds` | histogram | `reason` | backoff 时长。 |
| `crawler_ip_cooldown_active` | gauge | `reason` | 活跃 IP cooldown 数。 |
| `crawler_ip_cooldown_total` | counter | `reason` | IP cooldown 触发次数。 |
| `crawler_host_slowdown_active` | gauge | `reason` | 活跃 host slowdown 数。 |
| `crawler_host_slowdown_total` | counter | `reason` | host slowdown 触发次数。 |
| `crawler_host_asn_soft_limit_total` | counter | `asn`, `reason` | ASN soft limit 触发次数，可选。 |

## Redis 执行态

| 指标 | 类型 | label | 说明 |
|---|---|---|---|
| `crawler_execution_state_write_total` | counter | `state_type`, `result` | Redis 执行态写入结果。 |
| `crawler_execution_state_read_total` | counter | `state_type`, `result` | Redis 执行态读取结果。 |
| `crawler_execution_state_ttl_seconds` | histogram | `state_type` | 写入 key 的 TTL。 |
| `crawler_execution_state_forbidden_key_detected_total` | counter | `pattern` | 审计脚本发现禁止 key。运行时代码一般不应触发。 |

## 验证要求

005 验证脚本至少检查：

- sticky-pool 请求后 `crawler_egress_identity_selected_total` 增加。
- pacer 延迟后 `crawler_pacer_delay_seconds` 有观测值。
- delayed buffer 满后 `crawler_delayed_buffer_full_total` 和 `crawler_xreadgroup_suppressed_total` 增加。
- 429 / challenge 后 `crawler_feedback_signal_total`、backoff / cooldown / slowdown 指标增加。
- Redis 执行态写入失败时 `crawler_execution_state_write_total{result="failed"}` 增加。
