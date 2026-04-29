# ADR-0007: 抓取指令标识与无效消息处理

**状态**：已接受
**日期**：2026-04-29

## 背景

003 使用 Redis Streams consumer group 消费第六类下发的 Fetch Command。为了应对第六类或队列层的抖动重发，crawler-executor 需要稳定的 attempt 级幂等规则，避免同一个上游任务反复生成不同 `attempt_id`。

同时，Fetch Command 需要承载第六类已经掌握的 Host / Site 上下文，并明确无效消息、DLQ 的归属边界。

## 决策

第六类不提供 `attempt_id`。`attempt_id` 由 crawler-executor 生成。

003 阶段的 `attempt_id` 生成规则为：

```text
attempt_id = deterministic_hash(job_id + canonical_url)
```

也就是说，同一个 `job_id` 下同一个 canonical URL 被上游抖动重发时，应生成同一个 `attempt_id`，以便队列消费、Kafka 发布和下游投影具备 attempt 级幂等基础。

Fetch Command 契约调整：

- 第六类必须提供 `job_id`。
- 第六类必须提供 `canonical_url`。
- 第六类应提供 `host_id` / `site_id` 字段；当前阶段允许为空，暂不作为必填项。
- 原始 URL 仍保留为 `url`，用于抓取发起和追溯。

无效消息处理：

- 无效 Fetch Command 直接丢弃。
- crawler-executor 记录结构化日志和指标。
- 003 不规划 DLQ。
- 若未来需要 DLQ，DLQ 归第六类所有；crawler-executor 只按第六类契约接入，不自行定义错误队列事实。

## 备选方案

- 第六类直接提供 `attempt_id`：不采纳。attempt 是第二类执行层的一次抓取意图，应由执行层按稳定规则生成。
- 使用 `url_hash + attempted_at` 生成 attempt_id：不采纳于 003 队列消费场景。该规则会让上游抖动重发产生不同 attempt，削弱幂等性。
- 无效消息写入本系统 DLQ：不采纳。DLQ 属于队列治理与调度控制边界，应归第六类。
- Host ID / Site ID 当前强制必填：暂不采纳。终态应由第六类提供，但当前阶段允许空值，避免阻塞 003。

## 后果

- 好处：同一 `job_id + canonical_url` 在重发场景下保持 attempt 级幂等。
- 好处：Host / Site 字段进入契约，后续可平滑升级为强校验。
- 好处：无效消息处理不扩大第二类职责，不引入本系统自管 DLQ。
- 代价：`job_id` 和 `canonical_url` 成为有效 Fetch Command 的关键字段。
- 代价：同一 job 下同一 canonical URL 的多次真实重抓需要由第六类使用新的 `job_id` 或后续扩展 attempt seed 表达。

## 关联

- ADR-0002
- ADR-0003
- ADR-0004
- ADR-0006
- `specs/003-p2-readonly-scheduler-queue/`
