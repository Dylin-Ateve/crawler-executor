# 契约草案：第六类抓取指令

**状态**：草案  
**适用 spec**：`003-p2-readonly-scheduler-queue`  
**生产者**：第六类调度与决策  
**消费者**：crawler-executor

## 队列协议

003 使用 Redis Streams consumer group。

默认命名：

- 主任务流：`crawl:tasks`
- 可选 DLQ：`crawl:tasks:dlq`
- consumer group：`crawler-executor`
- consumer name：由 worker 实例标识生成

第六类通过 `XADD crawl:tasks ...` 写入 Fetch Command。crawler-executor 通过 `XREADGROUP` 消费，通过 `XACK` 确认已形成终态 attempt 事实的消息，并通过 `XAUTOCLAIM` 或等价机制接管超时未确认消息。

## 消息示例

```json
{
  "url": "https://www.wikipedia.org/",
  "canonical_url": "https://www.wikipedia.org/",
  "command_id": "cmd_20260429_000001",
  "job_id": "job_20260429_seed_batch",
  "trace_id": "trace_abc123",
  "host_id": "host_wikipedia_org",
  "site_id": "site_wikipedia",
  "tier": "default",
  "politeness_key": "site:wikipedia",
  "deadline_at": "2026-04-29T09:30:00Z",
  "max_retries": 2
}
```

## 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `url` | string | 是 | 待抓取 URL。 |
| `canonical_url` | string | 是 | 第六类按系统群 canonical URL 规则给出的规范化 URL。 |
| `command_id` | string | 否 | 第六类生成的指令 ID。 |
| `job_id` | string | 是 | 上游任务或批次；与 `canonical_url` 一起作为本系统生成 `attempt_id` 的幂等输入。 |
| `trace_id` | string | 否 | 跨系统追踪 ID。 |
| `host_id` | string | 否 | Host ID；终态应由第六类提供，当前阶段允许为空。 |
| `site_id` | string | 否 | Site ID；终态应由第六类提供，当前阶段允许为空。 |
| `tier` | string | 否 | 调度 tier。 |
| `politeness_key` | string | 否 | 策略 key。 |
| `deadline_at` | string | 否 | ISO-8601 时间。 |
| `max_retries` | integer | 否 | 最大重试建议。 |

## 消费语义

- crawler-executor 只消费消息，不向 URL 队列写入新消息。
- `crawl_attempt` 发布成功后按队列协议 `XACK`。
- 可重试失败不 `XACK`，消息留在 PEL。
- 超过最大投递次数后，发布终态失败 `crawl_attempt`，然后 `XACK`。
- 消息格式非法或缺少 `url` / `job_id` / `canonical_url` 时直接丢弃，记录结构化日志和指标，不发布成功抓取 attempt。
- 第六类不提供 `attempt_id`；crawler-executor 基于 `job_id + canonical_url` 生成确定性 `attempt_id`。
- URL 可解析但 fetch 失败时发布 `crawl_attempt(fetch_result=failed)`。
- 页面 outlinks 不回写队列。
- SIGTERM 后不清空 PEL；未完成消息交给后续 `XAUTOCLAIM`。

## 当前不规划

- 003 不启用 DLQ。
- 如果未来启用 DLQ，DLQ 归第六类定义和消费，本系统只按第六类契约接入。
