# 契约增量：Fetch Command M4 行为

**状态**：草案  
**基础契约**：`specs/003-p2-readonly-scheduler-queue/contracts/redis-fetch-command.md`

M4 不改变 Redis Streams 下发载体，只收口既有字段的执行语义。

## 字段语义变化

| 字段 | M4 前行为 | M4 后行为 |
|---|---|---|
| `deadline_at` | 解析后进入 request meta，未真正影响执行 | 表示最晚允许开始抓取的时间；过期则不发起 HTTP 请求，发布 terminal attempt 后 `XACK` |
| `max_retries` | 解析后进入 request meta，未真正影响执行 | 覆盖 fetch 层重试 / Redis delivery 上限；Kafka publish failure 不受该字段影响 |
| `policy_scope_id` | 透传到 `crawl_attempt` | 作为 effective policy 第一优先级精确匹配字段 |
| `politeness_key` | 透传到 `crawl_attempt` | 作为 effective policy fallback 匹配字段 |
| `host_id` | 透传到 `crawl_attempt` | 作为 effective policy fallback 匹配字段 |
| `site_id` | 透传到 `crawl_attempt` | 作为 effective policy fallback 匹配字段 |
| `tier` | 透传到 `crawl_attempt` | 作为 effective policy fallback 匹配字段 |

## `deadline_at`

要求：

- ISO-8601 UTC 时间。
- 判断点是发起 HTTP 请求前。
- delayed buffer 重新尝试时必须再次判断。
- 请求已经发起后，不因 deadline 到达主动取消。

过期时建议发布：

```json
{
  "fetch_result": "failed",
  "content_result": "unknown",
  "storage_result": "skipped",
  "error_type": "deadline_expired",
  "error_message": "Fetch command deadline expired before request start"
}
```

非法 `deadline_at`：

- 按无效 Fetch Command 处理。
- 记录日志和指标。
- `XACK` 丢弃。
- 不发布 `crawl_attempt`。

## `max_retries`

优先级：

```text
command.max_retries -> matched_policy.max_retries -> FETCH_QUEUE_MAX_DELIVERIES
```

约束：

- `max_retries >= 0`。
- 非整数或负数按无效 Fetch Command 处理。
- `max_retries=0` 表示第一次 fetch 层可重试失败即转 terminal。
- Kafka publish failure 不消耗 retry budget，不进入 terminal retry exhausted。

## pause

pause 不通过 Fetch Command 字段表达，而由 matched effective policy 表达。

命中 pause 时建议发布：

```json
{
  "fetch_result": "failed",
  "content_result": "unknown",
  "storage_result": "skipped",
  "error_type": "paused",
  "error_message": "Fetch command paused before request start"
}
```
