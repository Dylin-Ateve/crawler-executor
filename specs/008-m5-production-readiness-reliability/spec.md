# 功能规格：M5 生产就绪与可靠性补偿

**功能分支**：`008-m5-production-readiness-reliability`  
**创建日期**：2026-05-04  
**状态**：规格启动  
**Roadmap 位置**：M5：生产就绪与可靠性补偿。  
**输入来源**：`.specify/memory/constitution.md`、`.specify/memory/product.md`、`.specify/memory/architecture.md`、`state/current.md`、`state/roadmap.md`、`state/decisions/0003-redis-write-side-belongs-to-scheduler.md`、`state/decisions/0004-use-redis-streams-consumer-group-for-fetch-queue.md`、`state/decisions/0006-ack-fetch-command-after-crawl-attempt-published.md`、`state/decisions/0008-kafka-publish-failure-not-in-max-deliveries-terminal-semantics.md`、`state/decisions/0009-graceful-shutdown-and-pel-handover.md`、`state/decisions/0010-system-group-class-2-positioning.md`、`state/decisions/0012-adaptive-politeness-and-egress-concurrency.md`、`state/decisions/0013-k8s-daemonset-uses-rolling-update.md`、`state/decisions/0014-control-plane-policy-scope-and-streams-boundary.md`

## 定位与边界检查

- **章程门禁**：M5 先定义 production 复刻、停机专项、故障补偿和可度量验收，再进入实现；不以口头 SOP 替代可执行验证。
- **产品门禁**：仍服务第二类抓取执行系统，不引入 URL 选择、业务优先级、重抓窗口、解析派发、事实层投影或内容质量判断。
- **架构门禁**：保持“抓取指令进 → 原始字节落盘 + 单一 `crawl_attempt` 事件出”；M5 只补齐 production 复刻、可靠性补偿和发布治理。
- **决策门禁**：遵守 Redis Streams 只读消费、`crawl_attempt` 发布成功后 `XACK`、Kafka failure 不进入 fetch retry terminal、PEL 移交、第二类纯粹化、自适应 politeness、RollingUpdate 和 M4 policy scope 边界。

## 背景

M3 / M3a / M4 已在 staging 等价镜像环境验证 DaemonSet + `hostNetwork`、多出口 IP、sticky-pool、pacer、soft-ban feedback、delayed buffer、Redis Streams PEL、Object Storage、Kafka smoke、runtime policy、pause、deadline、max retries 和 SIGTERM shutdown 入口。

当前离正式 production 仍有四类缺口：

- staging 证据尚未按同一流程复刻到 production。
- 007 的 SIGTERM 验证覆盖了空闲 / 无 in-flight 场景，但带 in-flight 下载和 delayed buffer 的专项停机风险仍未单独证明。
- Kafka 长时间不可用时，当前只有“Kafka publish failure 不 `XACK`，对象保留”的底线，没有本地持久 outbox / 重放 / 高水位告警。
- 生产发布、回滚、Secret / ACL / OCI policy 审计和最小 smoke SOP 尚未形成可执行闭环。

M5 的第一版不处理完整 Grafana、DLQ、队列反压治理和 24 小时大规模压测；这些后置到 M5a 或 M5 后续批次，避免阻塞最小 production 复刻窗口。

## 已确认决策

1. **production 复刻优先于新能力扩张**：先验证 staging 已有能力能在 production 按同一流程成立，再引入大规模流量。
2. **专项停机是 production 前置门槛**：in-flight 下载和 delayed buffer 场景必须证明未完成消息不会被错误 `XACK`，且后续 worker 可接管。
3. **最小 production smoke 先于压测**：M5 第一阶段只做 10-50 条受控任务，不承诺 30-50 pages/sec 或 24 小时稳定性。
4. **故障补偿先设计再实现**：Kafka outbox / 重放路径需要先明确本地持久化模型、水位、幂等和恢复 SOP，再进入代码实现。
5. **运维辅助脚本归 `ops/`**：面向跳板机的投递、观测、审计和 smoke 辅助工具不继续混入 `deploy/`；`deploy/` 保持镜像、K8s 渲染和发布职责。
6. **M5a 不并入 M5 第一刀**：Grafana 看板、告警、DLQ、poison message 和队列反压契约保持后置。

## 用户场景与测试

### 用户故事 1 - production 能按 staging 同一流程复刻验证（优先级：P1）

作为运维人员，我需要在 production 通过与 staging 一致的跳板机流程完成配置审计、DaemonSet 更新、最小抓取 smoke 和恢复验证。

**独立测试**：加载 `deploy/environments/production.env`，渲染 ConfigMap / DaemonSet，执行 dry-run / apply，rollout 完成后使用 debug stream 投递 10 条 Fetch Command，验证 `crawl_attempt`、Object Storage、PEL、policy metrics 和 worker 日志。

**验收场景**：

1. **假设**production Secret / ConfigMap / node label 已准备，**当**执行 production audit，**则**所有必需 key、env、volume、probe 和 image ref 校验通过。
2. **假设**DaemonSet rollout 完成，**当**投递 debug stream smoke，**则**每条任务发布 `crawl_attempt` 后 `XACK`，debug PEL 最终为 0。
3. **假设**验证结束，**当**恢复生产运行配置，**则**`CRAWLER_DEBUG_MODE=false`，runtime policy 回到 production bootstrap 或目标版本。

### 用户故事 2 - in-flight 下载期间 SIGTERM 不破坏 PEL 语义（优先级：P1）

作为执行系统维护者，我需要确认 worker 在下载中收到 SIGTERM 时不会继续领取新任务，也不会错误 ack 未完成消息。

**独立测试**：投递一个指向慢响应测试端点的 Fetch Command，确认请求进入 in-flight 后向 Pod PID 1 发送 SIGTERM，验证退出日志、PEL、后续 worker reclaim 和最终 `crawl_attempt`。

**验收场景**：

1. **假设**请求已开始但尚未完成，**当**worker 收到 SIGTERM，**则**shutdown flag 立即生效，不再 `XREADGROUP` / `XAUTOCLAIM`。
2. **假设**in-flight 未在 drain 窗口内发布成功，**当**容器退出，**则**该消息留在 PEL。
3. **假设**新 worker 启动并达到 claim idle 时间，**当**执行 reclaim，**则**消息可重新处理，最终发布后 `XACK`。

### 用户故事 3 - delayed buffer 非空时 SIGTERM 可恢复（优先级：P1）

作为运维人员，我需要确认本地 delayed buffer 中尚未执行的任务在滚动更新时不会丢失。

**独立测试**：通过 policy / pacer 构造 delayed buffer 非空，发送 SIGTERM，验证 delayed buffer 消息不 `XACK`，并在重启后由 PEL reclaim。

**验收场景**：

1. **假设**worker 已读取消息并放入 delayed buffer，**当**SIGTERM 到达，**则**不再等待该任务到期后发起 HTTP 请求。
2. **假设**delayed buffer 消息未发布 `crawl_attempt`，**当**worker 退出，**则**消息仍在 PEL。
3. **假设**后续 worker reclaim，**当**任务仍未过 `deadline_at`，**则**正常抓取；若已过期，则发布 `deadline_expired` terminal attempt。

### 用户故事 4 - Kafka 长时间不可用时有补偿设计（优先级：P2）

作为系统维护者，我需要在对象已写入但 Kafka 长时间不可用时有可审计的本地持久补偿和重放路径。

**独立测试**：关闭 Kafka 或指向不可达 broker，执行成功 HTML 抓取，验证对象写入后事件进入本地 outbox，恢复 Kafka 后按 `attempt_id` 幂等发布并 ack 原 Fetch Command。

**验收场景**：

1. **假设**Object Storage 上传成功但 Kafka publish 失败，**当**outbox 启用，**则**事件 payload 与 storage 引用持久化到本地 outbox。
2. **假设**Kafka 恢复，**当**outbox replay 执行，**则**按原 `attempt_id` 发布，成功后标记 outbox record done。
3. **假设**outbox 水位超过阈值，**当**采集指标，**则**暴露高水位和最老事件年龄。

### 用户故事 5 - 发布 / 回滚 SOP 可执行（优先级：P2）

作为运维人员，我需要在 production 发布失败时快速回滚到上一镜像和上一份策略配置。

**独立测试**：记录当前 image ref 和 ConfigMap policy version，更新到新镜像后触发 smoke；模拟 smoke 失败并执行回滚，验证 old image / old policy 恢复且 DaemonSet ready。

**验收场景**：

1. **假设**发布前记录了 image ref 和 ConfigMap 摘要，**当**rollout 失败，**则**可以按 SOP 恢复上一版本。
2. **假设**回滚完成，**当**执行 health / metrics / policy audit，**则**恢复到已知稳定版本。
3. **假设**回滚期间存在 PEL，**当**worker 恢复，**则**PEL 可按既有 reclaim 语义处理。

## 功能需求

- **FR-001**：必须提供 production 复刻 runbook，覆盖跳板机执行习惯、环境变量加载、镜像 ref、ConfigMap / Secret 审计、DaemonSet dry-run / apply、rollout、smoke、恢复和证据记录。
- **FR-002**：必须提供 production 配置审计脚本或 checklist，至少覆盖 Redis、Kafka、Object Storage、runtime policy、debug mode、node label、hostNetwork、probe、image ref 和敏感配置不入库。
- **FR-003**：必须提供 production 最小 smoke 流程，使用 debug stream 投递 10-50 条 Fetch Command，验证 `crawl_attempt`、Object Storage、PEL、M4 policy metrics 和 worker 日志。
- **FR-004**：必须提供 in-flight SIGTERM 专项验证脚本，证明停止新读 / claim、未完成消息留 PEL、后续 reclaim 可恢复。
- **FR-005**：必须提供 delayed buffer SIGTERM 专项验证脚本，证明 buffered 消息不被错误 `XACK`，后续按 reclaim / deadline 语义处理。
- **FR-006**：必须定义 Kafka outbox / 故障补偿的数据模型、状态机、指标、水位阈值、重放方式和幂等边界。
- **FR-007**：若实现 outbox，必须确保 `crawl_attempt` payload 与对象存储引用在本地持久化；Kafka 发布成功后才能标记 done，并不得破坏原 Fetch Command ack 语义。
- **FR-008**：必须定义孤儿对象巡检和 `crawl_attempt` / Object Storage 存在性抽样校验方法。
- **FR-009**：必须提供发布 / 回滚 SOP，包含上一 image ref、上一 ConfigMap 摘要、rollout 状态、smoke 结果和恢复验证。
- **FR-010**：M5 相关运维辅助脚本必须放在 `ops/`；K8s 渲染和部署模板仍放在 `deploy/`。

## 非功能需求

- **NFR-001**：production smoke 首批任务规模必须受控，默认不超过 50 条。
- **NFR-002**：所有 production runbook 必须默认在跳板机执行，不假设本地具备 kube context、registry 或内网连通性。
- **NFR-003**：脚本和日志不得输出 Redis / Kafka / OCI 凭据、完整 Secret、响应 body 或敏感 URL 列表。
- **NFR-004**：M5 不得新增 Redis URL 队列写入，不得实现 URL 重排、优先级、去重或 outlinks enqueue。
- **NFR-005**：停机专项验证不得依赖破坏性集群操作；优先使用 debug stream、单 Pod SIGTERM 和受控测试端点。
- **NFR-006**：outbox 设计必须有本地容量上限、高水位指标和人工恢复路径，不能无限制占用节点磁盘。

## 关键实体

- **ProductionReplicaRunbook**：production 复刻 staging 功能验证的操作文档和证据模板。
- **ProductionAudit**：production Secret、ConfigMap、DaemonSet、node label、image、policy 和指标端口的审计结果。
- **SmokeBatch**：用于 production 最小验证的一小批 Fetch Command。
- **ShutdownScenario**：in-flight 或 delayed buffer 状态下的 SIGTERM 验证场景。
- **OutboxRecord**：Kafka publish failure 后持久化的待发布 `crawl_attempt` 事件。
- **OutboxReplay**：Kafka 恢复后的重放流程和状态推进。
- **ObjectEventAudit**：对象存储快照与 `crawl_attempt` 事件的一致性抽样记录。

## 边界场景

- production Secret key 存在但内容不可用。
- production node label / taint 与 staging 不一致。
- DaemonSet image ref 未显式替换或误用旧 tag。
- debug stream 可写但 worker 未切换到目标 node stream。
- in-flight 请求在 drain 窗口内完成、超时或被容器强杀。
- delayed buffer 消息在停机期间过 `deadline_at`。
- Kafka 不可用但 Object Storage 上传成功。
- outbox 记录已写但 replay 期间 worker 再次退出。
- 对象存在但 `crawl_attempt` 长时间未发布。
- 回滚后旧策略文件被 ConfigMap volume 延迟传播。

## 成功标准

- **SC-001**：production 复刻 runbook 可在跳板机按步骤执行，并产出可审计证据。
- **SC-002**：production 最小 smoke 中 Fetch Command 发布 `crawl_attempt` 后 `XACK`，PEL 最终清空。
- **SC-003**：in-flight SIGTERM 场景证明未完成消息留 PEL，后续 worker 可 reclaim 并完成。
- **SC-004**：delayed buffer SIGTERM 场景证明 buffered 消息不丢失，不错误 ack，后续按正常或 deadline terminal 语义处理。
- **SC-005**：Kafka outbox / 补偿设计通过评审，明确是否进入 M5 实现批次。
- **SC-006**：发布 / 回滚 SOP 可恢复上一 image ref 和上一 policy 配置，并能通过 health / metrics / smoke 验证。
- **SC-007**：M5 不引入 URL 调度、事实层投影、解析派发、DLQ 完整协议或 Grafana 完整落地。

## 不在 008 第一阶段范围

- 不做 24 小时稳定性压测和 30-50 pages/sec 单节点目标收口。
- 不落地完整 Grafana 看板、Prometheus alert rules 和 on-call SOP。
- 不定义 poison message / DLQ 完整协议。
- 不定义第六类队列分片、反压和重排协议。
- 不实现 JS 渲染、浏览器抓取、TLS 指纹或动态 UA 策略。
- 不实现 URL 选择、业务优先级、重抓窗口或 outlinks enqueue。
- 不迁移 `crawl_attempt` schema 到外部契约仓库。

## 澄清记录

- 2026-05-04：M5 第一阶段优先 production 复刻、专项停机验证和可靠性补偿设计；M5a 的观测与队列治理不混入第一刀。
- 2026-05-04：面向跳板机的运行期辅助脚本统一进入 `ops/`，不继续堆在 `deploy/scripts/`。
