# 任务：M5 生产就绪与可靠性补偿

**输入**：`spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/`  
**前置条件**：M4 staging 等价镜像环境验证通过；staging 已恢复正常配置；production 复刻窗口待团队确认。  
**当前状态**：规格启动。

## 阶段 1：规格与契约

- [x] T001 创建 008 M5 规格，明确范围、非目标、成功标准和后置能力。
- [x] T002 创建实施计划，完成章程 / 产品 / 架构 / ADR / 路线图门禁检查。
- [x] T003 创建 research，记录 production 复刻、专项停机和 outbox 设计取舍。
- [x] T004 创建 data-model，定义 ProductionReplica、SmokeBatch、ShutdownScenario、OutboxRecord 等实体。
- [x] T005 创建 production 复刻契约。
- [x] T006 创建 Kafka outbox / 故障补偿契约。
- [x] T007 创建 quickstart，定义 M5 第一阶段验证入口。

## 阶段 2：production 复刻材料

- [ ] T008 创建 `ops/production-replica-runbook.md`，记录跳板机执行流程和证据模板。
- [ ] T009 创建 `ops/scripts/run-production-config-audit.sh`，审计 production Secret key、ConfigMap、DaemonSet、node label、image ref、runtime policy 和 debug mode。
- [ ] T010 创建 `ops/scripts/run-production-smoke.sh`，封装 debug stream 选择、Fetch Command 生成 / 校验 / 投递、PEL 和指标检查。
- [ ] T011 在 staging 以 production-like 参数 dry-run 上述 audit / smoke 脚本，确认不会输出 Secret。

## 阶段 3：专项停机验证

- [ ] T012 创建 `ops/scripts/run-shutdown-inflight-validation.sh`，制造慢响应 in-flight 场景并发送 SIGTERM。
- [ ] T013 验证 in-flight SIGTERM 后不再 `XREADGROUP` / `XAUTOCLAIM`。
- [ ] T014 验证 in-flight 未完成消息保留 PEL，后续 worker reclaim 并完成 publish / ack。
- [ ] T015 创建 `ops/scripts/run-shutdown-delayed-buffer-validation.sh`，制造 delayed buffer 非空场景并发送 SIGTERM。
- [ ] T016 验证 delayed buffer 消息不错误 `XACK`，后续按 reclaim / deadline 语义完成。
- [ ] T017 将专项停机结果记录到 `specs/008-m5-production-readiness-reliability/staging-shutdown-validation-report.md`。

## 阶段 4：production 最小 smoke

- [ ] T018 在 production 发布窗口前执行 config audit。
- [ ] T019 production DaemonSet dry-run 通过后记录 image ref、policy version 和 generation。
- [ ] T020 production rollout 后执行 10-50 条 debug stream smoke。
- [ ] T021 验证 `crawl_attempt`、Object Storage、PEL、M4 policy metrics 和 shutdown metrics。
- [ ] T022 验证结束后恢复 `CRAWLER_DEBUG_MODE=false` 和 production runtime policy。
- [ ] T023 将 production 复刻证据记录到 `specs/008-m5-production-readiness-reliability/production-validation-report.md`。

## 阶段 5：Kafka outbox / 故障补偿设计

- [ ] T024 基于 `contracts/kafka-outbox.md` 完成设计评审，选择 outbox 存储方案。
- [ ] T025 明确 ack 策略：保持 publish-first ack，或新增 ADR 后采用 persist-first ack。
- [ ] T026 定义 outbox 指标、容量上限、清理策略和人工 replay SOP。
- [ ] T027 若评审决定本批实现，新增实现任务和测试任务；否则记录后置条件。

## 阶段 6：对象与事件一致性抽样

- [ ] T028 定义 `crawl_attempt` 与 Object Storage 存在性抽样方法。
- [ ] T029 创建对象读取 / gzip / hash 抽样辅助脚本或 runbook。
- [ ] T030 在 production smoke 后执行最小抽样，记录结果。

## 阶段 7：发布 / 回滚 SOP

- [ ] T031 创建发布前检查清单：image、policy、Secret key、node label、Redis / Kafka / OCI 连通性。
- [ ] T032 创建回滚 SOP：恢复上一 image ref 与上一 policy 配置。
- [ ] T033 在 staging 或 production dry-run 中验证回滚步骤。

## 阶段 8：现状层收口

- [ ] T034 更新 `state/current.md`，记录 008 进展和 production 复刻状态。
- [ ] T035 更新 `state/roadmap.md`，按结果调整 M5 / M5a 边界。
- [ ] T036 更新 `state/changelog.md`，记录 008 启动与后续验证结果。
- [ ] T037 更新 README 文档入口。
- [ ] T038 若 outbox 或 ack 语义发生变化，先新增 ADR；否则明确无需新增 ADR。

## 依赖与执行顺序

- 阶段 1 是所有任务前置。
- 阶段 2 / 3 可并行，但 production smoke 前必须先完成 config audit。
- 阶段 3 必须先在 staging 跑通，再进入 production 复刻窗口。
- 阶段 5 可以与阶段 2 / 3 并行，但实现 outbox 前必须完成设计评审。
- 阶段 8 是每次阶段性验证后的收尾。
