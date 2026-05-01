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
