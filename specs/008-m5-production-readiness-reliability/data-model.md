# 数据模型：M5 生产就绪与可靠性补偿

## ProductionReplicaRunbook

| 字段 | 类型 | 说明 |
|---|---|---|
| `environment` | string | 固定为 `production`。 |
| `operator_host` | string | 执行跳板机标识，不记录个人凭据。 |
| `image_ref` | string | 待发布镜像完整引用。 |
| `previous_image_ref` | string | 发布前 DaemonSet 当前镜像。 |
| `policy_version` | string | 目标 runtime policy version。 |
| `previous_policy_version` | string | 发布前 runtime policy version。 |
| `started_at` | datetime | 验证开始时间。 |
| `completed_at` | datetime | 验证完成时间。 |
| `result` | enum | `passed`、`failed`、`rolled_back`。 |

## ProductionAuditResult

| 字段 | 类型 | 说明 |
|---|---|---|
| `namespace` | string | K8s namespace。 |
| `daemonset` | string | DaemonSet 名称。 |
| `configmap` | string | ConfigMap 名称。 |
| `secrets_checked` | list[string] | 已检查的 Secret key 名称，不包含值。 |
| `node_label_status` | enum | `ok`、`missing`、`unexpected`。 |
| `image_status` | enum | `ok`、`missing`、`old_tag`、`latest_forbidden`。 |
| `policy_status` | enum | `ok`、`missing`、`invalid`。 |
| `result` | enum | `passed`、`failed`。 |

## SmokeBatch

| 字段 | 类型 | 说明 |
|---|---|---|
| `job_id` | string | production smoke 批次 ID。 |
| `stream` | string | 目标 Redis stream，优先 debug stream。 |
| `group` | string | consumer group。 |
| `command_count` | integer | 默认 10-50。 |
| `expected_policy_version` | string | 期望 runtime policy version。 |
| `started_at` | datetime | 投递时间。 |
| `result` | enum | `passed`、`failed`。 |

## ShutdownScenario

| 字段 | 类型 | 说明 |
|---|---|---|
| `scenario_type` | enum | `in_flight`、`delayed_buffer`。 |
| `pod` | string | 目标 Pod。 |
| `node` | string | 目标 node。 |
| `stream_message_id` | string | 被验证的 Redis stream message id。 |
| `job_id` | string | Fetch Command job id。 |
| `signal` | string | 默认 `SIGTERM`。 |
| `pel_before` | object | 停机前 PEL 状态。 |
| `pel_after_exit` | object | 退出后 PEL 状态。 |
| `pel_after_reclaim` | object | reclaim 后 PEL 状态。 |
| `result` | enum | `passed`、`failed`。 |

## OutboxRecord

| 字段 | 类型 | 说明 |
|---|---|---|
| `outbox_id` | string | 本地 outbox 记录 ID。 |
| `attempt_id` | string | `crawl_attempt` 幂等键。 |
| `stream` | string | 原 Fetch Command stream。 |
| `stream_message_id` | string | 原 Redis message id。 |
| `payload_json` | object | 待发布 `crawl_attempt` payload。 |
| `storage_key` | string | 若已写对象，记录对象 key。 |
| `status` | enum | `pending`、`publishing`、`published`、`failed`。 |
| `created_at` | datetime | 创建时间。 |
| `updated_at` | datetime | 更新时间。 |
| `last_error` | string | 最近 publish error 摘要。 |
| `publish_attempts` | integer | outbox replay 次数。 |

## ObjectEventAudit

| 字段 | 类型 | 说明 |
|---|---|---|
| `attempt_id` | string | 抽样 attempt。 |
| `storage_key` | string | 事件中的对象 key。 |
| `object_exists` | boolean | 对象是否存在。 |
| `event_seen` | boolean | 是否观察到 `crawl_attempt`。 |
| `content_sha256_match` | boolean | 快照 hash 是否匹配。 |
| `checked_at` | datetime | 抽样时间。 |
| `result` | enum | `passed`、`failed`。 |
