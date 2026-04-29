# 功能规格：P2 第六类队列只读消费与多 worker 运行形态

**功能分支**：`003-p2-readonly-scheduler-queue`
**创建日期**：2026-04-29
**状态**：草稿
**输入来源**：`.specify/memory/product.md`、`.specify/memory/architecture.md`、`state/current.md`、`state/roadmap.md`、`state/decisions/0003-redis-write-side-belongs-to-scheduler.md`、`state/decisions/0007-fetch-command-identity-and-invalid-message-handling.md`

## 定位与边界检查

- **Roadmap 位置**：M2：第六类队列只读消费接入。
- **产品门禁**：符合第二类“执行 URL 抓取指令、可靠落盘原始字节、发布 `crawl_attempt`”的定位。
- **架构边界**：本 spec 只消费第六类下发的抓取指令，不选择 URL、不写 Redis URL 队列、不 enqueue outlinks、不维护去重过滤器。
- **相关 ADR**：ADR-0002、ADR-0003、ADR-0004、ADR-0005、ADR-0006、ADR-0007、ADR-0010。

## 背景

P0 已验证 Scrapy worker 的单节点多出口 IP 能力。P1 已验证 HTML 对象存储与单一 `crawl_attempt` producer。当前 crawler-executor 仍主要通过本地 seed 文件验证输入链路，尚未进入“第六类调度系统下发抓取指令，多个 worker 只读消费”的运行形态。

003 的目标是把输入侧从本地 seed 文件推进到 Redis Streams consumer group 队列消费，同时保持第二类执行系统边界：第六类负责 `XADD` 写入队列、优先级、去重与重抓决策；crawler-executor 只负责 `XREADGROUP` 消费指令、执行抓取、落盘、发布 `crawl_attempt`，并在终态事实发布成功后 `XACK`。

003 不引入 scrapy-redis 默认 scheduler / dupefilter。Scrapy spider 在启动入口运行有限阻塞的消费循环，空队列时以约 5 秒为单位挂起等待，避免永久阻塞影响 SIGTERM 退出。

003 同时补强 P1 收口后留下的关键缺口：连接级 fetch 失败需要形成 `crawl_attempt(fetch_result=failed)`，避免队列化运行后出现“取到指令但没有 attempt 事实”的盲区。

## 用户场景与测试

### 用户故事 1 - 消费第六类下发的抓取指令（优先级：P1）

作为第六类调度系统，我需要把 URL 抓取指令写入 Redis / Valkey 队列，由 crawler-executor worker 消费并完成抓取、对象存储和 `crawl_attempt` 发布。

**优先级理由**：这是从 P0/P1 本地验证进入真实执行系统运行形态的入口。

**独立测试**：向测试队列写入 3 条抓取指令，启动 worker，验证每条指令都产生一条 `crawl_attempt`。

**验收场景**：

1. **假设** Redis / Valkey 队列存在 3 条有效抓取指令，**当** worker 启动消费，**则** 每条指令最终产生一条 `crawl_attempt`。
2. **假设** 指令包含 `job_id`、`canonical_url`、`trace_id`、`host_id`、`site_id` 等字段，**当** worker 构造 request，**则**字段进入 request meta 并出现在 `crawl_attempt` 或日志上下文中。
3. **假设** 队列为空，**当** worker 运行，**则** worker 不退出，并暴露空队列状态或消费等待指标。

### 用户故事 2 - 保持 Redis 只读边界（优先级：P1）

作为架构负责人，我需要证明 crawler-executor 不向 Redis URL 队列写入新任务，不回灌 outlinks，不维护上游去重状态。

**优先级理由**：这是 ADR-0003 的核心约束，若失败会破坏第二类边界。

**独立测试**：抓取一个包含 outlinks 的 HTML 页面，检查 Redis 队列长度、相关 key 写入和日志，确认 executor 没有新增 URL 任务。

**验收场景**：

1. **假设** worker 抓取到含 outlinks 的 HTML 页面，**当** pipeline 统计 outlinks，**则** outlinks 只作为计数字段进入 `crawl_attempt`，不会写回 Redis。
2. **假设** worker 消费一条队列消息，**当** attempt 完成，**则** Redis 中只出现队列协议必需的 ack / pending / consumer 状态，不出现由 executor 写入的新 URL。
3. **假设** scrapy-redis 默认行为会写 dupefilter 或 scheduler 状态，**当**该行为违反只读边界，**则**不得作为 003 实现路径。

### 用户故事 3 - 多 worker 并发消费（优先级：P1）

作为运维人员，我需要多个 worker 同时消费同一队列，正常 ack 路径下同一抓取指令不会被多个 worker 重复处理。

**优先级理由**：多 worker 运行形态是后续 K8s DaemonSet 和规模化部署的前置。

**独立测试**：启动两个 worker，同时消费同一测试队列，验证每条消息只有一个 worker 处理并 ack。

**验收场景**：

1. **假设** 队列中有 10 条有效指令，**当**两个 worker 同时运行，**则**最终产生 10 条 `crawl_attempt`，且正常 ack 路径下无重复 attempt。
2. **假设** worker 在处理过程中异常退出，**当**队列协议支持 pending / reclaim，**则**后续 worker 可按约定重取未 ack 消息；若队列协议不支持，则在 research 中说明限制。

### 用户故事 4 - fetch 失败也形成 attempt 事实（优先级：P1）

作为下游消费者，我需要连接超时、DNS 失败、TCP 拒绝等 fetch 失败也发布 `crawl_attempt(fetch_result=failed)`，以便第五类形成完整抓取事实。

**优先级理由**：P1 已覆盖 stored / skipped / storage failed / Kafka failed，但连接级 fetch failed 未被 T055 覆盖；队列化运行后这是 attempt 完整性的关键缺口。

**独立测试**：队列中写入不可达域名或拒绝连接 URL，验证 worker 发布 `fetch_result=failed`、`storage_result=skipped` 的 `crawl_attempt`。

**验收场景**：

1. **假设** DNS 解析失败，**当** worker 处理该指令，**则**发布 `crawl_attempt`，`fetch_result=failed`，并包含错误类型和错误消息。
2. **假设** TCP 连接被拒绝或超时，**当** worker 处理该指令，**则**发布 `crawl_attempt`，`storage_result=skipped`，且不写对象存储。
3. **假设** Kafka 发布失败，**当** fetch failed attempt 需要发布，**则**记录结构化错误和指标，P2 仍不实现本地 outbox。

## 边界场景

- 队列消息 JSON 格式非法。
- 队列消息缺少 URL、`job_id` 或 `canonical_url`。
- URL schema 不支持或 canonical URL 构造失败。
- Redis / Valkey 连接失败。
- 队列为空。
- 多 worker 同时消费同一队列。
- worker 处理消息中途退出。
- DNS 失败、连接拒绝、下载超时。
- HTML 成功、非 HTML 跳过、对象存储失败、Kafka 失败均需继续沿用 P1 语义。

## 需求

### 功能需求

- **FR-001**：系统必须支持从 Redis / Valkey 队列读取第六类抓取指令。
- **FR-002**：抓取指令必须包含 `url`、`job_id`、`canonical_url` 字段。
- **FR-003**：抓取指令可选包含 `command_id`、`trace_id`、`host_id`、`site_id`、`tier`、`politeness_key`、`deadline_at`、`max_retries`。
- **FR-004**：队列协议使用 Redis Streams consumer group。
- **FR-005**：本系统不得向 URL 队列写入新任务。
- **FR-006**：本系统不得将 outlinks 写回 Redis / Valkey。
- **FR-007**：本系统不得维护第六类 URL 去重过滤器。
- **FR-008**：第六类不提供 `attempt_id`；本系统必须基于 `job_id + canonical_url` 生成确定性 `attempt_id`，并用于 `crawl_attempt.attempt_id`。
- **FR-009**：成功 HTML 必须沿用 P1 `storage_result=stored` 语义。
- **FR-010**：非 HTML / 非 200 必须沿用 P1 `storage_result=skipped` 语义。
- **FR-011**：对象存储失败必须沿用 P1 `storage_result=failed` 语义。
- **FR-012**：连接级 fetch 失败必须发布 `fetch_result=failed`、`storage_result=skipped` 的 `crawl_attempt`。
- **FR-013**：无效队列消息不得导致 worker 崩溃；本系统直接丢弃无效消息，并记录结构化日志和指标。
- **FR-014**：队列为空时 worker 应保持运行，并暴露队列空转或等待状态。
- **FR-015**：worker 必须在 `crawl_attempt` 发布成功后再 `XACK`。
- **FR-016**：可重试失败不得 `XACK`，消息留在 PEL，后续由 `XAUTOCLAIM` 或等价机制接管。
- **FR-017**：超过最大投递次数后，必须发布终态失败 `crawl_attempt`，然后 `XACK`。
- **FR-018**：多个 worker 消费同一队列时，正常 ack 路径下同一消息不得被重复确认处理。
- **FR-019**：`host_id` / `site_id` 应由第六类提供，但当前阶段允许为空，不作为必填项。
- **FR-020**：003 不规划 DLQ；若未来启用 DLQ，其归属为第六类。
- **FR-021**：003 不实现 PostgreSQL / ClickHouse consumer，不实现第五类事实投影。

### 非功能需求

- **NFR-001**：003 不得降低 P0 出口 IP 选择和黑名单能力。
- **NFR-002**：003 不得降低 P1 对象存储和 `crawl_attempt` producer 能力。
- **NFR-003**：队列消费、ack、消息无效、fetch failed、Redis 连接失败必须有日志和 Prometheus 指标。
- **NFR-004**：敏感配置通过环境变量或 secret 注入，文档不得提交真实凭据。
- **NFR-005**：实现必须支持本地或测试环境下的可重复验证。

### 关键实体

- **Fetch Command**：第六类写入队列的抓取指令，至少包含 URL，并可携带调度上下文。
- **Queue Consumer State**：队列协议层面的消费状态，例如 consumer group、pending、ack 或等价机制。
- **Crawl Attempt Event**：P1 已定义的一次 URL 抓取尝试完整事实，003 扩展 fetch failed 场景。

## 成功标准

- **SC-001**：向测试队列写入 3 条有效指令后，worker 发布 3 条 `crawl_attempt`。
- **SC-002**：两个 worker 同时消费 10 条指令，正常 ack 路径下不重复处理同一消息。
- **SC-003**：抓取含 outlinks 的 HTML 页面后，Redis 队列中不出现由 executor 写入的新 URL。
- **SC-004**：不可达 URL 会发布 `fetch_result=failed`、`storage_result=skipped` 的 `crawl_attempt`。
- **SC-005**：无效消息被记录并计数，不导致 worker 进程崩溃。
- **SC-006**：成功 HTML、非 HTML、对象存储失败和 Kafka 失败仍保持 P1 语义。
- **SC-007**：同一 `job_id + canonical_url` 被重复投递时生成相同 `attempt_id`。

## 假设

- P2 继续复用 P0 Scrapy worker、IP middleware 与 P1 `crawl_attempt` pipeline。
- Redis / Valkey 是第六类下发抓取指令的运行时载体。
- 第六类负责 URL 选择、优先级、重抓窗口和队列写入。
- 第五类负责 `crawl_attempt` 事实投影，本仓库不实现消费端数据库。

## 澄清记录

- 2026-04-29：确认 003 不做第五类 PostgreSQL / ClickHouse 投影。
- 2026-04-29：确认 003 需回补 ADR-0003，明确 Redis 队列写入侧归第六类，本系统只读消费。
- 2026-04-29：确认 003 需要补强连接级 fetch failed 到 `crawl_attempt` 的事件化路径。
- 2026-04-29：确认 003 使用 Redis Streams consumer group，不引入 scrapy-redis 默认 scheduler / dupefilter。
- 2026-04-29：确认 `crawl_attempt` 发布成功后再 `XACK`；可重试失败留在 PEL，超过投递上限后发布终态失败再 ack。
- 2026-04-29：确认第六类不提供 `attempt_id`，本系统基于 `job_id + canonical_url` 生成确定性 `attempt_id`。
- 2026-04-29：确认 Fetch Command 必须增加 `canonical_url`；`host_id` / `site_id` 当前允许为空；无效消息直接丢弃并记录日志；DLQ 暂不规划且归第六类。
