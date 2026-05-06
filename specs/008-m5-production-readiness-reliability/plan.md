# 实施计划：M5 生产就绪与可靠性补偿

**分支**：`008-m5-production-readiness-reliability`  
**日期**：2026-05-04  
**规格文档**：`specs/008-m5-production-readiness-reliability/spec.md`

## 摘要

008 在 M3 / M3a / M4 staging 验证完成的基础上，推进 production 前的最小闭环：production 复刻验证、in-flight / delayed buffer 停机专项、最小 production smoke、发布 / 回滚 SOP，以及 Kafka outbox / 故障补偿设计。

第一阶段不做完整 Grafana / 告警、DLQ、队列反压治理、24 小时压测或 JS 渲染。

## 技术上下文

**语言/版本**：Python 3.9+、Bash  
**主要依赖**：Scrapy、Redis / Valkey client、Kafka client、OCI SDK、Prometheus client、kubectl  
**输入协议**：Redis / Valkey Streams Fetch Command  
**输出协议**：单一 `crawl_attempt` Kafka 事件  
**目标环境**：production OKE / crawler node pool；操作入口默认跳板机  
**辅助目录**：运行期脚本放 `ops/`，K8s 渲染和部署模板放 `deploy/`  
**测试**：本地 pytest、staging 专项脚本、production dry-run / debug stream smoke  
**约束**：不写 URL 队列；不实现业务调度；生产 smoke 首批不超过 50 条；敏感配置不入库

## 门禁检查

| 门禁 | 来源 | 结果 | 说明 |
|---|---|---|---|
| 章程门禁 | `.specify/memory/constitution.md` | 通过 | 先定义可度量验证和失败行为，再进入实现。 |
| 产品门禁 | `.specify/memory/product.md` | 通过 | 只补生产化、可靠性和运维安全，不回流 URL 选择或事实层。 |
| 架构门禁 | `.specify/memory/architecture.md` | 通过 | 符合 DaemonSet / hostNetwork、事件总线本地缓冲、staging-production 等价性和跳板机发布约束。 |
| 决策门禁 | `state/decisions/` | 通过 | 遵守 ADR-0003/0004/0006/0008/0009/0010/0012/0013/0014。 |
| 路线图对齐 | `state/roadmap.md` | 通过 | 对应 M5；M5a 观测与队列治理保持后置。 |

## 项目结构

```text
specs/008-m5-production-readiness-reliability/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── production-replica.md
│   └── kafka-outbox.md
└── tasks.md

ops/
├── production-replica-runbook.md       # 后续任务创建
└── scripts/
    ├── run-production-config-audit.sh  # 后续任务创建
    ├── run-production-smoke.sh         # 后续任务创建
    ├── run-shutdown-inflight-validation.sh
    └── run-shutdown-delayed-buffer-validation.sh
```

## 关键设计约束

### 1. production 复刻

- production 与 staging 的操作流程应保持一致：跳板机加载环境、渲染 ConfigMap / DaemonSet、apply、rollout、smoke、恢复。
- production 差异只能来自 endpoint、Secret、kube context、node 数量、网卡名、IP 池规模和环境级 prefix / salt。
- production 首次 smoke 使用 debug stream 或明确受控 stream，默认不进入大规模主流量。

### 2. 专项停机

- in-flight 场景验证请求已发起但未完成时的 SIGTERM 行为。
- delayed buffer 场景验证消息已读入 PEL 但尚未发起请求时的 SIGTERM 行为。
- 两类场景都必须证明停止新读 / claim、未完成消息留 PEL、后续 worker reclaim 可恢复。

### 3. Kafka outbox

- outbox 只补偿 `crawl_attempt` 发布失败，不承担 URL 队列、优先级或重抓逻辑。
- outbox record 必须可由 `attempt_id` 幂等重放。
- outbox 必须有容量上限、高水位指标、最老记录年龄和人工恢复 SOP。
- 是否在 M5 第一批实现由设计评审决定；规格阶段先定义契约。

### 4. 发布与回滚

- 发布前必须记录当前 image ref、ConfigMap policy version / 摘要和 DaemonSet generation。
- 回滚必须恢复 image ref 和 policy 配置，并通过 health / metrics / smoke 验证。
- 所有 production 证据记录不得包含 Secret 内容。

## 复杂度跟踪

| 例外项 | 必要原因 | 未采纳更简单方案的原因 |
|---|---|---|
| production 复刻 runbook | staging 不是 production，必须证明同流程可迁移 | 直接上线主流量无法定位配置、网络或权限差异 |
| in-flight / delayed buffer 专项脚本 | 007 已验证 SIGTERM 入口，但未覆盖最危险的本地状态 | 仅看空闲停机日志不足以证明 PEL 不丢失 |
| Kafka outbox 设计 | 终态要求事件总线短暂不可用时具备本地缓冲 | 继续只依赖 PEL 会留下对象已写但事件长期不可见的恢复缺口 |
| ops 目录 | 运维辅助与部署模板职责不同 | 继续混在 deploy 会模糊“发布”和“运行期操作”边界 |

## 实施阶段

1. 规格启动：创建 spec、plan、research、data model、contracts、quickstart、tasks。
2. production 复刻材料：创建 production runbook、配置审计 checklist / 脚本和证据模板。
3. 专项停机验证：实现 in-flight 与 delayed buffer 两个 staging 验证脚本，先在 staging 跑通。
4. production 最小 smoke：复用 `ops/scripts` 生成 / 校验 / 投递命令，补 production smoke 包装脚本。
5. Kafka outbox 设计：定义数据模型、状态机、重放策略、指标和容量边界；评审后决定是否实现。
6. 发布 / 回滚 SOP：记录 image / ConfigMap 回滚路径，并在 staging 或 production dry-run 验证。
7. 现状层收口：更新 current、roadmap、changelog 和 README。

## 后续计划约束

- 若 outbox 实现需要改变 `crawl_attempt` schema 或 Fetch Command ack 语义，必须先新增 ADR。
- 若 production 复刻暴露 staging-production 环境等价性缺口，优先修补环境契约和 runbook，不直接绕过验证。
- 若需要定义 DLQ、poison message 或队列反压，应启动 M5a，不并入 008 第一阶段。
