# 研究记录：M4 运行时执行策略与停抓控制

## 1. 策略源形态

### 决策：第一版使用本地文件 / ConfigMap provider

原因：

- 上游控制平面尚未建设，不能阻塞 executor 的运行时控制能力。
- K8s ConfigMap volume 能覆盖 staging / production 等价操作习惯。
- 本地文件 provider 足以验证 reload、校验失败、last-known-good、pause 和指标。
- 后续控制平面 provider 可实现同一 `PolicyProvider` 接口，输出同形态 effective policy。

未采纳：

- **空实现**：无法验证热加载、pause、LKG 和指标，不符合章程“可度量验收”。
- **直接实现控制平面 API client**：当前缺少上游 API 契约，容易把策略设计绑死在未建系统上。
- **继续只用 env / ConfigMap env vars**：env 变更通常需要滚动，不满足 M4 runtime 目标。

## 2. 策略匹配与边界

### 决策：只匹配 effective policy，不实现策略优先级

executor 固定匹配顺序：

```text
policy_scope_id -> politeness_key -> host_id -> site_id -> tier -> default_policy
```

这个顺序只是执行层 fallback，不代表业务策略优先级。控制平面或第六类应提前解析复杂策略，并通过 `policy_scope_id` 或其他上下文字段把结果显式传给 executor。

未采纳：

- **executor 内部合并 tier / site / host 策略**：会引入控制平面心智，违反 ADR-0014。
- **允许多条 scope policy 叠加**：第一版难以审计，容易产生不确定运行行为。
- **按 URL / 正则匹配策略**：会让 executor 重新承担分组成员关系或调度语义。

## 3. Last-known-good

### 决策：LKG 属于执行安全能力

LKG 不代表 executor 做策略决策，只代表策略源异常时继续使用最近一次成功校验并生效的 effective policy。

约束：

- LKG 必须暴露 active 状态、age 和 policy version。
- LKG 可设置最大年龄告警阈值，但 M4 第一版不强制超过阈值自动停抓。
- 启动时没有 LKG 则使用 bootstrap default policy。

未采纳：

- **策略源失败时全局停抓**：过于激进，控制平面短暂抖动会导致全体 worker 停摆。
- **策略源失败时静默使用 env 默认值**：不可审计，且可能让运行参数突然回退。

## 4. `deadline_at`

### 决策：表示最晚允许开始抓取的时间

判断点：

- 从 Redis Stream 读到消息后、构造 Scrapy Request 前。
- delayed buffer 重新尝试发起前。
- pause 解除后准备发起前。

不在请求已经发起后用 `deadline_at` 主动取消下载；下载过程由 `download_timeout_seconds` / Scrapy timeout 控制。

未采纳：

- **deadline 表示必须完成抓取的时间**：executor 无法精确保证网络请求和 Kafka publish 在 deadline 前完成。
- **deadline 只由第六类处理**：delayed buffer 和本地 pacing 会让 executor 也需要判断过期。

## 5. `max_retries`

### 决策：覆盖 fetch 层重试 / 投递上限，不覆盖 Kafka failure

优先级：

```text
Fetch Command max_retries -> effective policy max_retries -> FETCH_QUEUE_MAX_DELIVERIES
```

Kafka publish failure 不进入该计数。原因沿用 ADR-0008：如果 Kafka 不可用，试图发布“Kafka 不可用终态事件”本身自相矛盾，除非引入 outbox。outbox 后置到 M5。

## 6. Pause terminal attempt

### 决策：pause 命中发布 terminal `crawl_attempt`

pause 是执行层明确决定“不开始本次 attempt”的事实。如果只 ack 丢弃，第三类 / 第五类 / 第六类无法审计停抓影响。

建议字段：

```json
{
  "fetch_result": "failed",
  "content_result": "unknown",
  "storage_result": "skipped",
  "error_type": "paused",
  "error_message": "Fetch command paused before request start"
}
```

后续如系统群统一引入 `fetch_result=skipped`，可通过 schema 版本迁移；M4 第一版先保持当前枚举兼容。

## 7. 严格优雅停机

### 决策：M4 收口停止新读 / claim

当前实现通过 Scrapy `spider_closed` / `engine_stopped` 信号进入停机，但目标节点验证显示 shutdown flag 触发偏晚。M4 应更早接入 SIGTERM / SIGINT 或 Scrapy engine 停止入口，使 consumer 立即停止：

- `XREADGROUP`
- `XAUTOCLAIM`
- delayed buffer drain 中新建 request

in-flight 处理第一版不强制做到 exactly-once；仍沿用 PEL 可恢复和 `attempt_id` 幂等，但必须减少退出期间继续 claim / 重复处理。

## 8. M4 指标

M4 指标应补 executor 当前缺失的运行时控制面：

- policy load result
- current policy version
- LKG active / age
- pause skip count
- deadline expired count
- max retries terminal count
- shutdown state / drain timeout

完整 Grafana dashboard 和告警规则后置到 M5a；M4 只提供指标和基础验证。
