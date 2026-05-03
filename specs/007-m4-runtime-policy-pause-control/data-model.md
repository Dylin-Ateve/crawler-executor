# 数据模型：M4 运行时执行策略与停抓控制

本文档定义 007 内部运行时模型。除 `crawl_attempt` 可选字段扩展外，所有模型均属于 executor 本地运行态，不是第五类事实层。

## 1. EffectivePolicyDocument

策略文件根对象。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema_version` | string | 是 | 第一版为 `1.0`。 |
| `version` | string | 是 | 策略版本，供日志、指标和审计使用。 |
| `generated_at` | string | 是 | ISO-8601 UTC 时间。 |
| `default_policy` | object | 是 | 默认 effective policy。 |
| `scope_policies` | array | 否 | 作用域策略列表，可为空。 |

约束：

- `version` 不能是空字符串。
- `scope_policies` 中同一 `scope_type + scope_id` 不得重复。
- 文档不得包含凭据。

## 2. EffectivePolicy

可直接应用到 executor 的执行策略。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | boolean | `true` | 是否启用该策略。`false` 第一版等价于 paused。 |
| `paused` | boolean | `false` | 是否暂停匹配范围内的新请求。 |
| `pause_reason` | string | null | pause 原因，写入日志 / attempt error message。 |
| `egress_selection_strategy` | string | settings | `STICKY_POOL`、`STICKY_BY_HOST` 等现有策略名。 |
| `sticky_pool_size` | integer | settings | 每 host 候选出口身份数量。 |
| `host_ip_min_delay_ms` | integer | settings | `(host, egress_identity)` 最小请求启动间隔。 |
| `host_ip_jitter_ms` | integer | settings | pacing jitter。 |
| `download_timeout_seconds` | integer | settings | 下载超时。 |
| `max_retries` | integer | settings | fetch 层重试 / 投递上限。 |
| `max_local_delay_seconds` | integer | settings | 本地 delayed buffer 最大等待时间。 |

取值约束：

- `sticky_pool_size >= 1`。
- `host_ip_min_delay_ms >= 0`。
- `host_ip_jitter_ms >= 0`。
- `download_timeout_seconds > 0`。
- `max_retries >= 0`，并不得超过实现定义的安全上限。
- `max_local_delay_seconds >= 0`。

## 3. ScopePolicy

作用域策略 override。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `scope_type` | string | 是 | `policy_scope_id`、`politeness_key`、`host_id`、`site_id`、`tier`。 |
| `scope_id` | string | 是 | 与 Fetch Command 对应字段精确匹配。 |
| `policy` | object | 是 | EffectivePolicy 部分字段 override。 |

约束：

- 第一版只支持精确字符串匹配。
- 不支持 URL pattern、host glob、正则、标签表达式或成员关系查询。
- 同一 scope type + scope id 重复出现时，整个文档非法。

## 4. PolicyProviderState

策略 provider 的运行态。

| 字段 | 说明 |
|---|---|
| `source_type` | `file`、`configmap_file`、后续 `control_plane`。 |
| `source_path` | 本地策略文件路径。 |
| `reload_interval_seconds` | reload 周期。 |
| `last_checked_at` | 最近检查时间。 |
| `last_loaded_at` | 最近成功加载时间。 |
| `last_load_result` | `success`、`not_modified`、`read_error`、`validation_error`。 |
| `last_error` | 最近错误摘要，不包含完整策略内容。 |
| `current_version` | 当前生效策略版本。 |

## 5. PolicyCache

保存当前策略和 LKG。

| 字段 | 说明 |
|---|---|
| `current_document` | 当前生效 EffectivePolicyDocument。 |
| `last_known_good_document` | 最近一次成功校验并生效的策略。 |
| `bootstrap_document` | 由 env / settings 生成的默认策略。 |
| `lkg_active` | 当前是否因加载失败使用 LKG。 |
| `lkg_age_seconds` | LKG 距离加载成功的时间。 |

状态转换：

```text
bootstrap -> load_success -> current_and_lkg
current_and_lkg -> load_success(new_version) -> current_and_lkg
current_and_lkg -> load_failure -> lkg_active
lkg_active -> load_success(new_version) -> current_and_lkg
bootstrap -> load_failure(no_lkg) -> bootstrap
```

## 6. PolicyDecision

单条 Fetch Command 的策略匹配结果。

| 字段 | 说明 |
|---|---|
| `policy_version` | 生效策略版本。 |
| `matched_scope_type` | 命中的 scope type；默认策略时为 `default`。 |
| `matched_scope_id` | 命中的 scope id；默认策略时为空。 |
| `policy` | 合并后的 effective policy。 |
| `lkg_active` | 决策时是否处于 LKG。 |

匹配顺序：

```text
policy_scope_id -> politeness_key -> host_id -> site_id -> tier -> default_policy
```

## 7. TerminalSkipAttempt

因 pause 或 deadline 过期未发起 HTTP 请求，但仍需要发布的 `crawl_attempt`。

| 字段 | pause | deadline |
|---|---|---|
| `fetch_result` | `failed` | `failed` |
| `content_result` | `unknown` | `unknown` |
| `storage_result` | `skipped` | `skipped` |
| `error_type` | `paused` | `deadline_expired` |
| `status_code` | null | null |
| `content_type` | null | null |
| `bytes_downloaded` | 0 | 0 |

建议可选上下文字段：

- `policy_version`
- `matched_policy_scope_type`
- `matched_policy_scope_id`
- `pause_reason`

这些字段如进入 `crawl_attempt` schema，必须保持可选。

## 8. RetryBudget

Fetch Command 的重试预算。

| 字段 | 说明 |
|---|---|
| `source` | `command`、`policy`、`settings`。 |
| `max_retries` | 最大 fetch 重试 / 投递次数预算。 |
| `deliveries` | Redis Streams 当前投递次数。 |
| `remaining` | 剩余预算。 |

约束：

- Kafka publish failure 不消耗该预算。
- 非法 `max_retries` 在 parse 阶段视为无效 Fetch Command。

## 9. ShutdownState

严格优雅停机状态。

| 字段 | 说明 |
|---|---|
| `shutdown_requested` | 是否收到 SIGTERM / SIGINT 或等价停机信号。 |
| `requested_at` | 停机信号时间。 |
| `stop_reads_at` | 停止新 `XREADGROUP` 的时间。 |
| `stop_claims_at` | 停止新 `XAUTOCLAIM` 的时间。 |
| `in_flight_estimate` | 估算 in-flight 数。 |
| `delayed_buffer_size` | 停机时本地 delayed buffer 大小。 |
| `drain_deadline_at` | drain 截止时间。 |
| `drain_timed_out` | 是否超过 drain 时限。 |

约束：

- shutdown 后不得主动 ack 未发布成功 attempt 的消息。
- shutdown 后不得 claim 其他 worker 的 pending 消息。
