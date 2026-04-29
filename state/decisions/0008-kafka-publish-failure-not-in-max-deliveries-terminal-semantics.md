# ADR-0008: Kafka 发布失败不进入最大投递次数终态语义

**状态**：已接受
**日期**：2026-04-29

## 背景

ADR-0006 与 spec 003 FR-016 / FR-017 规定：可重试失败不 `XACK`，消息留在 PEL；超过最大投递次数后必须发布终态失败 `crawl_attempt`，然后 `XACK`。

在 003 阶段对实现侧（`pipelines.py`、`spiders/fetch_queue.py`、`queues.py`）的对齐过程中发现：

- **fetch 层失败**（DNS、TCP、超时、可重试 5xx 等）已具备完整的"达到上限发布终态 attempt 后 ack"的代码路径，由 spider 的 errback 与 `_should_retry_request` 判定承载，符合 FR-016 / FR-017。
- **Kafka 发布失败**没有进入任何投递次数计数；当前行为是 `pipelines.py` 在 `PublishError` 分支下既不 ack、也不递增 delivery 计数、也不会改走终态发布。

如果硬要把 Kafka 失败也接入"达到上限发终态 attempt 后 ack"，会撞上一个**自相矛盾的语义**：终态失败的事实仍然必须以 `crawl_attempt` 形式发布到 Kafka，而触发条件正是"无法发布到 Kafka"。

唯一让该语义自洽的工程路径是引入本地 outbox 或磁盘缓冲，由 outbox 在 Kafka 恢复后异步补发。该能力在 `state/roadmap.md` 已显式标记为后置项，不在 003 范围内。

## 决策

003 范围内 **Kafka 发布失败不进入最大投递次数终态语义**：

1. Kafka 发布失败时，crawler-executor 仍遵守 ADR-0006 / spec FR-015：**不 `XACK`**，消息留在 PEL。
2. Kafka 发布失败 **不递增 attempt 级 retry 计数**，**不会**通过 `FETCH_QUEUE_MAX_DELIVERIES` 转入"发布终态失败 attempt 后 ack"的分支。
3. 该消息可以通过 `XAUTOCLAIM` 被另一个 consumer 接管。Kafka 恢复前的多次接管不视为"投递耗尽"。
4. Kafka 长时间不可用属于"不可推进的下游故障"，由运维侧通过 Kafka 健康度告警 + 紧急停抓 SOP 处理；本仓库不在 003 引入丢弃 + ack 的退化路径，也不引入本地 outbox。

spec 003 FR-017 中"超过最大投递次数后发布终态失败 attempt 然后 ack"的语义，**仅适用于 fetch 层失败**（DNS / TCP / 超时 / 可重试 HTTP 状态码 / 主动判定不可继续重试的请求）。Kafka 层失败不在 FR-017 适用范围内。

P2 退出报告必须显式声明此边界，并把"Kafka 长时间故障下 PEL 增长"作为已识别风险列出。

## 备选方案

- **Kafka 失败也累计 retry 计数 + 达到上限发终态 attempt**：不采纳。终态事实仍需经由 Kafka 发布，与触发条件冲突；除非引入本地 outbox 才能闭环，而 outbox 已在 roadmap 后置。
- **Kafka 失败累计 retry + 达到上限直接 ack 并写本地落盘事实**：不采纳。违反 ADR-0006 / FR-015"`crawl_attempt` 发布成功后再 `XACK`"的不变量；引入本仓库自管的"失败事实落盘"也与 ADR-0010"crawler-executor 锁定为第二类纯粹实现"冲突。
- **Kafka 失败立即 ack + 仅记录失败指标**：不采纳。会让"已 ack 但无 attempt 事实"的窗口重新出现，违反 ADR-0006 的核心动机。
- **现在就实现本地 outbox 以闭合 FR-017 在 Kafka 失败下的语义**：不采纳。outbox 是 roadmap M3+ 的能力，强行前置会扩大 003 范围，破坏增量交付原则。

## 后果

- **好处**：保持"已 `XACK` 的指令必有 `crawl_attempt` 事实"这一不变量。
- **好处**：003 不引入与 ADR-0010 第二类边界冲突的本地落盘事实。
- **好处**：003 完成后的实现行为与 spec / ADR 语义对齐，避免在退出评审时出现 spec/code 差距。
- **代价**：Kafka 长时间故障期间 PEL 持续增长；需要在运维侧用 Kafka 可用性告警和紧急停抓 SOP 兜底。
- **代价**：消息可被多次 reclaim，依赖 attempt-id 幂等（ADR-0007 已保证）和 OCI 对象覆盖语义（同 storage_key 重传幂等）。
- **后续**：当本地 outbox / Kafka 故障补偿队列被规划时，必须显式重新审视本 ADR；若引入 outbox，本 ADR 会被新 ADR 替代或修订。

## 关联

- ADR-0002
- ADR-0003
- ADR-0006
- ADR-0010
- `specs/003-p2-readonly-scheduler-queue/spec.md` FR-015 / FR-016 / FR-017
- `state/roadmap.md` "本地出站事件缓冲和 Kafka 故障补偿"
