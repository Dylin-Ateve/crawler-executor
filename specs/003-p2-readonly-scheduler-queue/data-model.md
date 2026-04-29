# 数据模型：P2 第六类队列只读消费与多 worker 运行形态

## 1. Fetch Command

第六类写入队列的抓取指令。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `url` | string | 是 | 待抓取 URL。 |
| `canonical_url` | string | 是 | 第六类给出的 canonical URL。 |
| `command_id` | string | 否 | 第六类指令 ID，用于追踪队列消息。 |
| `job_id` | string | 是 | 上游批次或任务 ID；与 `canonical_url` 一起作为 `attempt_id` 幂等输入。 |
| `trace_id` | string | 否 | 跨系统追踪 ID。 |
| `host_id` | string | 否 | 上游 Host ID；终态应由第六类提供，当前阶段允许为空。 |
| `site_id` | string | 否 | 上游 Site ID；终态应由第六类提供，当前阶段允许为空。 |
| `tier` | string | 否 | 调度层级，用于读取运行参数，不由本系统解释优先级。 |
| `politeness_key` | string | 否 | 控制平面策略 key。 |
| `deadline_at` | string | 否 | ISO-8601 截止时间。 |
| `max_retries` | integer | 否 | 上游建议的最大重试次数；具体映射需 plan 阶段确认。 |

## 2. Queue Consumer State

队列协议相关运行态，不表达 URL 选择或调度决策。

Redis Streams consumer group 形态下包含：

- stream key
- consumer group
- consumer name
- message id
- pending count
- last delivered id
- ack result
- delivery count
- min idle time

这些状态只用于消费确认和故障恢复，不属于事实层，不上升为业务事实。

## 2.1 Delivery Result

每条 Fetch Command 的处理结果分为三类：

| 结果 | ack 行为 | 说明 |
|---|---|---|
| 成功抓取 | 发布 `crawl_attempt` 成功后 `XACK` | 包括 HTML stored、非 HTML skipped、404 / 410 等终态 skipped。 |
| 可重试失败 | 不 `XACK` | 消息留在 PEL，后续由 `XAUTOCLAIM` 接管。 |
| 永久失败 | 发布终态失败 `crawl_attempt` 后 `XACK` | 包括无效 URL、不支持 scheme、投递次数超限等。 |
 
最大投递次数由 `FETCH_QUEUE_MAX_DELIVERIES` 控制，超过上限后可重试失败转为永久失败。

## 3. Request Meta Mapping

Fetch Command 进入 Scrapy request 后，应映射到 request meta：

| Fetch Command | Request meta | 说明 |
|---|---|---|
| `url` | request url | 抓取目标。 |
| `canonical_url` | `canonical_url` | 作为 `url_hash` 和 `attempt_id` 的输入。 |
| `command_id` | `command_id` | 用于日志和追踪。 |
| `job_id` | `job_id` | 透传。 |
| `trace_id` | `trace_id` | 透传。 |
| `host_id` | `host_id` | 透传。 |
| `site_id` | `site_id` | 透传。 |
| `tier` | `tier` | 透传，不在本系统重新排序。 |
| `politeness_key` | `politeness_key` | 后续控制平面策略使用。 |
| generated from `job_id + canonical_url` | `attempt_id` | attempt 级幂等键。 |
| generated | `attempted_at_dt` | attempt 起始时间。 |

## 4. Crawl Attempt 扩展点

003 复用 P1 `crawl_attempt` schema，并重点补强 fetch failed 场景。

fetch failed attempt 应至少包含：

- `attempt_id`
- `url_hash`
- `canonical_url`
- `original_url`
- `host`
- `attempted_at`
- `finished_at`
- `fetch_result=failed`
- `content_result=unknown`
- `storage_result=skipped`
- `error_type`
- `error_message`

## 4.1 Attempt ID

003 的 `attempt_id` 由 crawler-executor 生成，不由第六类提供。

生成维度：

```text
attempt_id = deterministic_hash(job_id + canonical_url)
```

同一个 `job_id + canonical_url` 重复投递时，必须得到同一个 `attempt_id`。如果第六类希望对同一 canonical URL 发起新的真实重抓，应使用新的 `job_id`。

## 5. 不建模内容

003 不建模：

- PostgreSQL `crawl_logs`
- PostgreSQL `page_snapshots`
- PostgreSQL `pages_latest`
- ClickHouse Host profile
- parse-tasks
- URL 去重过滤器
- DLQ（当前不规划；未来若启用，归第六类）
