# 指标契约：M4 运行时执行策略与停抓控制

**状态**：草案  
**适用 spec**：`007-m4-runtime-policy-pause-control`

## 原则

- 不输出完整 URL、响应 body、凭据、完整策略文件。
- policy version 可作为 label，但必须限制长度并避免高基数频繁生成。
- scope label 优先使用 `scope_type`，`scope_id` 如需暴露应使用 hash 或受控低基数字段。

## 指标

| 指标 | 类型 | Labels | 说明 |
|---|---|---|---|
| `crawler_policy_load_total` | Counter | `result` | 策略加载次数，result 为 `success`、`read_error`、`validation_error`、`not_modified`。 |
| `crawler_policy_current_version` | Gauge | `version` | 当前生效策略版本，值为 1。版本切换时旧 label 应置 0 或由进程重启自然消失。 |
| `crawler_policy_lkg_active` | Gauge | 无 | 当前是否使用 last-known-good。 |
| `crawler_policy_lkg_age_seconds` | Gauge | 无 | LKG 距离最近成功加载的年龄。 |
| `crawler_policy_decision_total` | Counter | `matched_scope_type` | policy decision 次数。 |
| `crawler_fetch_paused_total` | Counter | `matched_scope_type`, `reason` | pause 命中导致的 terminal skip。 |
| `crawler_fetch_deadline_expired_total` | Counter | `matched_scope_type` | deadline 过期 terminal skip。 |
| `crawler_fetch_retry_terminal_total` | Counter | `reason` | fetch 层达到 retry budget 的 terminal attempt。 |
| `crawler_shutdown_events_total` | Counter | `event` | shutdown requested、read_stopped、claim_stopped、drain_timeout 等。 |
| `crawler_shutdown_in_flight` | Gauge | 无 | 停机时估算 in-flight。 |

## 验证要求

- policy load success / failure 场景必须能看到计数变化。
- LKG 场景必须能看到 `crawler_policy_lkg_active=1`。
- pause / deadline 场景必须能看到对应 terminal skip 计数。
- SIGTERM 验证必须能看到 shutdown 事件计数。
