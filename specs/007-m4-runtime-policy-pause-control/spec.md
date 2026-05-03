# 功能规格：M4 运行时执行策略与停抓控制

**功能分支**：`007-m4-runtime-policy-pause-control`  
**创建日期**：2026-05-03  
**状态**：本地实现与验证完成；staging / production 复刻不在本 spec 范围
**Roadmap 位置**：M4：运行时执行策略与停抓控制。  
**输入来源**：`.specify/memory/constitution.md`、`.specify/memory/product.md`、`.specify/memory/architecture.md`、`state/current.md`、`state/roadmap.md`、`state/decisions/0003-redis-write-side-belongs-to-scheduler.md`、`state/decisions/0004-use-redis-streams-consumer-group-for-fetch-queue.md`、`state/decisions/0006-ack-fetch-command-after-crawl-attempt-published.md`、`state/decisions/0007-fetch-command-identity-and-invalid-message-handling.md`、`state/decisions/0008-kafka-publish-failure-not-in-max-deliveries-terminal-semantics.md`、`state/decisions/0009-graceful-shutdown-and-pel-handover.md`、`state/decisions/0010-system-group-class-2-positioning.md`、`state/decisions/0012-adaptive-politeness-and-egress-concurrency.md`、`state/decisions/0014-control-plane-policy-scope-and-streams-boundary.md`

## 定位与边界检查

- **章程门禁**：本 spec 先定义需求、契约、失败行为和可度量验收，再进入实现；标记为 `NEEDS CLARIFICATION` 的事项会阻塞实现计划。
- **产品门禁**：仍服务第二类抓取执行系统；不引入 URL 选择、业务优先级、重抓窗口、解析派发、事实层投影或内容质量判断。
- **架构门禁**：本 spec 只补齐执行层运行时策略应用、停抓控制、过期任务跳过、重试边界和严格停机；不改变“抓取指令进 → 原始字节落盘 + 单一 `crawl_attempt` 事件出”的终态边界。
- **决策门禁**：遵守 Redis Streams 只读消费、`crawl_attempt` 发布成功后 `XACK`、Kafka 发布失败不进入 fetch 最大投递次数终态、PEL 移交、第二类纯粹化、自适应 politeness 和控制平面策略作用域边界。

## 背景

M3 / M3a 已在 staging 等价镜像环境验证了 DaemonSet + `hostNetwork`、多出口 IP、host-aware sticky-pool、per-(host, egress identity) pacer、soft-ban feedback、Redis TTL 执行态、Kafka publish smoke 和 PEL 恢复能力。

当前生产稳定抓取仍缺少一组运行时控制能力：

- politeness / pause / timeout / retry 等执行参数仍主要来自 env / ConfigMap 静态值，变更需要滚动或重启。
- 上游控制平面尚未建成，但 executor 需要先定义与未来控制平面兼容的 effective policy 契约。
- Fetch Command 中的 `deadline_at`、`max_retries` 当前只解析和透传，未真正影响执行。
- 当前优雅停机只满足 PEL 不清空和可恢复底线；严格“SIGTERM 后立即停止读 / claim”尚未收口。
- M4 新增控制能力需要对应运行指标，否则后续生产看板无法解释策略源、pause、deadline 和 retry 行为。

M4 第一版采用本地文件 / ConfigMap provider 承载 effective policy，不等待完整控制平面。未来控制平面只要输出同形态 effective policy，executor 的策略应用逻辑应保持稳定。

## 已确认决策

1. **effective policy 而非原始策略**：executor 只消费已经解析好的 effective policy，不实现策略优先级、业务策略合并或成员关系解析。
2. **本地 provider 不是空实现**：第一版使用本地文件 / ConfigMap provider，必须能真实验证热加载、last-known-good、pause 和作用域覆盖。
3. **固定 fallback 是执行匹配规则，不是业务优先级**：当多种上下文字段存在时，第一版匹配顺序固定为 `policy_scope_id -> politeness_key -> host_id -> site_id -> tier -> default_policy`；同层多条匹配视为策略文件非法。
4. **deadline 语义**：`deadline_at` 表示 Fetch Command 最晚允许开始抓取的时间；executor 在发起 HTTP 请求前判断，过期则跳过并发布 terminal `crawl_attempt`。
5. **max retries 生效**：Fetch Command `max_retries` 必须覆盖默认 fetch 层最大重试 / 投递上限；Kafka publish failure 不进入该语义，仍遵守 ADR-0008。
6. **pause 不是业务调度**：全局 / 作用域 pause 只阻止 executor 发起新的 HTTP 请求；是否以后重抓、延后或重排仍由第六类决定。
7. **严格停机收口**：M4 必须比当前 T015c 更早设置 shutdown flag，SIGTERM 后停止新的 `XREADGROUP` 和 `XAUTOCLAIM`。
8. **后置能力不进入 M4**：production 复刻、Kafka outbox / 故障补偿、poison message / DLQ、完整 Grafana / 告警落地、JS 渲染均后置。

## 用户场景与测试

### 用户故事 1 - 运行时策略热加载不需要重启 worker（优先级：P1）

作为运维人员，我需要通过本地策略文件或 ConfigMap 更新执行参数，使 worker 不重启即可调整 pacing、timeout、retry 或 pause。

**独立测试**：启动 worker，使用策略文件设置默认 `host_ip_min_delay_ms=2000`；运行期间修改文件为 `5000`，等待 reload interval 后写入新 Fetch Command，验证新请求按新策略生效，进程未重启。

**验收场景**：

1. **假设**策略文件版本从 `policy-v1` 更新到 `policy-v2`，**当**reload interval 到达，**则**worker 加载并应用 `policy-v2`。
2. **假设**策略文件未改变，**当**reload interval 到达，**则**worker 不重复应用同一版本，不产生噪声日志。
3. **假设**策略文件变更只影响 `politeness_key=site:example`，**当**其他 scope 的请求到达，**则**仍使用原默认策略。

### 用户故事 2 - 策略源异常时使用 last-known-good（优先级：P1）

作为执行系统维护者，我需要控制平面或 ConfigMap 短暂异常时 worker 继续使用最近一次有效策略，而不是全局停摆或退回不可预期默认值。

**独立测试**：先加载有效策略，再把策略文件替换为非法 JSON 或非法字段；验证 worker 拒绝新策略、继续使用 LKG、暴露 LKG 指标和错误计数。

**验收场景**：

1. **假设**worker 已加载 `policy-v1`，**当**下一次 reload 读到非法 JSON，**则**继续使用 `policy-v1`。
2. **假设**策略文件 schema 合法但同层同 scope 出现重复策略，**当**reload，**则**拒绝该版本并继续使用 LKG。
3. **假设**worker 启动时没有有效策略文件，**当**读取失败，**则**使用 env / settings 构造的 bootstrap default policy，并暴露无 LKG 的启动状态。

### 用户故事 3 - 全局 / 作用域 pause 能阻止新请求启动（优先级：P1）

作为控制平面运营人员，我需要在源站异常、合规风险或运维窗口内快速停止全部或某个作用域的抓取。

**独立测试**：策略文件中设置 `default_policy.paused=true` 或某个 `policy_scope_id` 的 `paused=true`；写入匹配 Fetch Command，验证 executor 不发起 HTTP 请求，发布 terminal `crawl_attempt` 并 `XACK`。

**验收场景**：

1. **假设**全局 `paused=true`，**当**任意 Fetch Command 到达，**则**不发起 HTTP 请求，发布 `error_type=paused` 的 terminal attempt。
2. **假设**仅 `policy_scope_id=policy-paused-001` 暂停，**当**该 scope 的 Fetch Command 到达，**则**跳过；其他 scope 继续执行。
3. **假设**任务已进入 in-flight 下载，**当**pause 策略随后生效，**则**不主动伪造失败；pause 只阻止尚未开始的请求。

### 用户故事 4 - `deadline_at` 在发起请求前生效（优先级：P1）

作为第六类调度系统，我需要传递任务有效期，避免过期任务在 delayed buffer 或队列等待后仍对源站发起请求。

**独立测试**：写入 `deadline_at` 已过期的 Fetch Command，验证 executor 不请求目标 URL，发布 `error_type=deadline_expired` 的 terminal `crawl_attempt`，Kafka 发布成功后 `XACK`。

**验收场景**：

1. **假设**Fetch Command 到达时 `deadline_at` 已过期，**当**worker 准备构造 request，**则**直接发布 deadline expired attempt。
2. **假设**Fetch Command 初次读取时未过期，但因 pacer delayed 到过期后才可执行，**当**再次准备发起请求，**则**跳过并发布 deadline expired attempt。
3. **假设**请求已经发起，**当**执行过程中超过 `deadline_at`，**则**不由 deadline 取消；下载超时仍由 `download_timeout_seconds` 或 Scrapy timeout 控制。

### 用户故事 5 - `max_retries` 覆盖默认 fetch 重试上限（优先级：P1）

作为第六类调度系统，我需要按任务传递重试预算，使高价值和低价值任务可使用不同的 fetch 层重试上限。

**独立测试**：写入 `max_retries=0` 的 Fetch Command 并让目标返回 503，验证第一次失败后发布 terminal retry exhausted attempt；写入 `max_retries=2` 的 Fetch Command，验证可通过 PEL reclaim / fetch retry 继续尝试，直到达到上限。

**验收场景**：

1. **假设**Fetch Command `max_retries=0`，**当**发生可重试 fetch 失败，**则**不再等待下一次投递，发布 terminal attempt 后 `XACK`。
2. **假设**Fetch Command `max_retries=2`，**当**前两次 fetch 层失败，**则**消息不 `XACK`，仍可由 PEL reclaim。
3. **假设**Kafka publish failure，**当**消息被多次 claim，**则**不因 `max_retries` 转入 terminal attempt，继续遵守 ADR-0008。

### 用户故事 6 - 严格优雅停机停止新读和 claim（优先级：P1）

作为运维人员，我需要滚动更新或手动停机时 worker 快速摘流，避免退出期间继续读取新消息或 claim 其他 worker 的 pending 消息。

**独立测试**：启动 worker 并发送 SIGTERM；验证 SIGTERM 到达后不再调用 `XREADGROUP` / `XAUTOCLAIM`，in-flight 按 drain 策略结束或留 PEL，退出日志和指标记录 drain 状态。

**验收场景**：

1. **假设**worker 正在空队列阻塞读，**当**收到 SIGTERM，**则**最多等待当前 `FETCH_QUEUE_BLOCK_MS` 后退出读循环，不再发起新 `XREADGROUP`。
2. **假设**worker 收到 SIGTERM 时存在 delayed buffer 消息，**当**退出，**则**这些消息不 `XACK`，保留 PEL 供后续 reclaim。
3. **假设**worker 收到 SIGTERM 后还有其他 consumer 的 pending 消息，**当**本 worker 尚未退出，**则**不得再 `XAUTOCLAIM`。

### 用户故事 7 - M4 控制行为具备可观测性（优先级：P2）

作为运维人员，我需要通过 Prometheus 指标和结构化日志判断当前策略版本、LKG 状态、pause 命中、deadline 过期、retry terminal 和 shutdown drain 是否正常。

**独立测试**：触发策略加载成功、加载失败、LKG、pause、deadline expired、max retries terminal 和 SIGTERM drain，验证对应指标存在且 label 不包含完整 URL、响应 body 或凭据。

**验收场景**：

1. **假设**策略加载成功，**当**采集指标，**则**可以看到当前策略版本和 load success 计数。
2. **假设**策略加载失败并使用 LKG，**当**采集指标，**则**可以看到 LKG active 和 LKG age。
3. **假设**pause 或 deadline 跳过任务，**当**采集指标和 `crawl_attempt`，**则**能区分跳过原因。

## 功能需求

- **FR-001**：系统必须新增 effective policy 数据结构，包含 schema version、policy version、generated_at、default policy 和可选 scope policies。
- **FR-002**：系统必须实现本地文件 / ConfigMap policy provider，支持周期 reload，reload interval 可配置。
- **FR-003**：policy provider 必须校验 JSON schema、字段类型、取值范围、重复 scope 和未知危险字段；校验失败不得应用新策略。
- **FR-004**：系统必须实现 last-known-good；成功加载的最近策略在后续加载失败时继续生效。
- **FR-005**：无有效策略文件且无 LKG 时，系统必须从现有 env / settings 生成 bootstrap default policy，保证向后兼容启动。
- **FR-006**：系统必须按固定顺序匹配 effective policy：`policy_scope_id -> politeness_key -> host_id -> site_id -> tier -> default_policy`。
- **FR-007**：同一 scope type + scope id 只能有一条策略；重复匹配必须视为策略非法，拒绝加载。
- **FR-008**：effective policy 必须至少支持：`enabled`、`paused`、`pause_reason`、`egress_selection_strategy`、`sticky_pool_size`、`host_ip_min_delay_ms`、`host_ip_jitter_ms`、`download_timeout_seconds`、`max_retries`、`max_local_delay_seconds`。
- **FR-009**：系统必须在构造 Scrapy Request 前检查 pause；命中 pause 的 Fetch Command 不得发起 HTTP 请求。
- **FR-010**：pause 命中必须发布 terminal `crawl_attempt`，建议 `fetch_result=failed`、`content_result=unknown`、`storage_result=skipped`、`error_type=paused`，Kafka 发布成功后 `XACK`。
- **FR-011**：系统必须在构造 Scrapy Request 前检查 `deadline_at`；过期任务不得发起 HTTP 请求。
- **FR-012**：deadline 过期必须发布 terminal `crawl_attempt`，建议 `error_type=deadline_expired`，Kafka 发布成功后 `XACK`。
- **FR-013**：`deadline_at` 格式非法的 Fetch Command 必须按无效消息处理；当前阶段沿用 ADR-0007，记录日志和指标后 `XACK` 丢弃，不发布 `crawl_attempt`。
- **FR-014**：Fetch Command `max_retries` 必须覆盖默认 fetch 层最大重试 / 投递上限；缺失时使用 effective policy `max_retries`；再缺失时使用现有 `FETCH_QUEUE_MAX_DELIVERIES`。
- **FR-015**：Kafka publish failure 不得计入 `max_retries`，不得因 `max_retries` 达到上限而 `XACK` 丢弃。
- **FR-016**：严格优雅停机必须确保 shutdown flag 在 SIGTERM / SIGINT 到达后尽早设置，使消费循环停止新的 `XREADGROUP` 和 `XAUTOCLAIM`。
- **FR-017**：停机期间未完成、未执行、未发布成功的 Fetch Command 不得 `XACK`，必须保留 PEL 供后续 reclaim。
- **FR-018**：系统必须暴露 M4 指标：policy load result、current policy version、LKG active、LKG age、pause skips、deadline expired、max retries terminal、shutdown drain。
- **FR-019**：`crawl_attempt` schema 必须支持表达 M4 跳过语义所需的错误类型；若需新增字段记录 policy version，应保持可选和向后兼容。
- **FR-020**：系统必须提供本地验证脚本，覆盖 policy reload、LKG、pause、deadline、max retries 和 graceful shutdown。

## 非功能需求

- **NFR-001**：policy reload 不得阻塞 Scrapy 下载主循环；策略读取和校验失败必须 fail-safe 到 LKG 或 bootstrap default。
- **NFR-002**：策略文件不得包含 Redis / Kafka / OCI 凭据；日志和指标不得输出完整策略文件内容。
- **NFR-003**：策略匹配不得使用完整 URL 作为指标 label；host、policy scope 和 egress identity 指标应优先使用 hash 或低基数字段。
- **NFR-004**：M4 不得增加 Redis URL 队列写入，不得写 priority / dupefilter / outlink queue。
- **NFR-005**：pause、deadline 和 retry terminal 都必须遵守 `crawl_attempt` 发布成功后再 `XACK`。
- **NFR-006**：M4 不要求达到 30-50 pages/sec 压测目标，但不得显著破坏 M3a 的单 worker 正常抓取路径。

## 关键实体

- **EffectivePolicyDocument**：策略文件根对象，包含版本、生成时间、默认策略和作用域策略列表。
- **EffectivePolicy**：已解析可应用的执行策略，不包含业务优先级和成员关系。
- **ScopePolicy**：绑定到 `policy_scope_id`、`politeness_key`、`host_id`、`site_id` 或 `tier` 的策略 override。
- **PolicyProvider**：本地文件 / ConfigMap 策略源，负责读取、校验、版本检测和 reload。
- **PolicyCache**：保存当前策略、last-known-good、加载状态和错误信息。
- **PolicyDecision**：对单条 Fetch Command 的策略匹配结果，包括应用策略、匹配 scope、policy version。
- **TerminalSkipAttempt**：因 pause 或 deadline 过期未发起 HTTP 请求但仍发布的终态 `crawl_attempt`。
- **ShutdownState**：严格优雅停机状态，控制 `XREADGROUP`、`XAUTOCLAIM`、delayed buffer 和 in-flight drain。

## 边界场景

- 策略文件不存在、权限错误、非法 JSON、schema version 不支持。
- 策略文件合法但 scope 重复、字段越界或包含未知危险字段。
- worker 启动时没有策略文件，也没有 LKG。
- Fetch Command 同时命中多个不同层级 scope。
- Fetch Command `deadline_at` 格式非法、已过期或 delayed 后过期。
- Fetch Command `max_retries` 为 0、负数、非整数或大于配置上限。
- pause 与 deadline 同时命中。
- pause 生效时已有 in-flight request。
- SIGTERM 到达时正在 Redis 阻塞读、正在 reclaim、持有 delayed buffer 或正在 Kafka publish。
- Kafka publish failure 发生在 pause / deadline terminal attempt 发布阶段。

## 成功标准

- **SC-001**：策略文件更新后，worker 不重启即可在约定 reload interval 内应用新策略。
- **SC-002**：非法策略不会覆盖当前策略；LKG 指标和日志能解释当前使用的策略版本。
- **SC-003**：全局 / 作用域 pause 命中的 Fetch Command 不发起 HTTP 请求，发布 terminal `crawl_attempt` 后 `XACK`。
- **SC-004**：`deadline_at` 过期任务不发起 HTTP 请求，发布 `deadline_expired` terminal attempt 后 `XACK`。
- **SC-005**：`max_retries` 能覆盖默认 fetch 层重试 / 投递上限，Kafka publish failure 不受该上限影响。
- **SC-006**：SIGTERM / SIGINT 后 worker 不再发起新的 `XREADGROUP` / `XAUTOCLAIM`；未完成消息保留 PEL。
- **SC-007**：Prometheus 指标能解释 policy load、LKG、pause、deadline、retry terminal 和 shutdown drain 行为。
- **SC-008**：M4 实现不引入 URL 调度、策略成员管理、业务优先级或 Redis URL 队列写入。

## 不在 007 范围

- 不实现真实控制平面 API server、数据库或策略编辑 UI。
- 不实现策略优先级、业务策略合并、Host/Site 成员关系解析。
- 不改变第六类 URL 选择、业务优先级、重抓窗口和队列写入职责。
- 不实现 production 复刻验证或正式 production 部署。
- 不实现 Kafka outbox / 本地持久化故障补偿。
- 不实现 poison message / DLQ 协议。
- 不落地完整 Grafana 看板、告警和 on-call SOP。
- 不实现 JS 渲染、浏览器抓取、TLS 指纹或复杂 UA 策略。

## 澄清记录

- 2026-05-03：M4 第一版采用本地文件 / ConfigMap provider，契约与未来控制平面输出保持同形态；不是空实现。
- 2026-05-03：`deadline_at` 定义为“最晚允许开始抓取的时间”，不是“必须完成抓取的时间”。
- 2026-05-03：固定 scope fallback 是 executor 的执行匹配规则，不代表业务策略优先级。
- 2026-05-03：production 复刻验证、Kafka outbox、DLQ、完整生产观测后置到 M5 / M5a。
- 2026-05-03：007 已完成本地实现、单元测试和 M4 验证脚本；未执行 staging / production 环境验证。
