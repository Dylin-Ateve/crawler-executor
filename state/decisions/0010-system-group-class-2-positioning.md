# ADR-0010: crawler-executor 锁定为系统群第二类的纯粹实现

**状态**：已接受
**日期**：2026-04-29

## 背景

2026-04-29 的架构边界调整依据《企业级内容生产系统群设计》第八章、第九章、第十章和第十一章，将 crawler-executor 明确锁定为系统群第二类：抓取执行系统。

调整前，文档中混有终态架构、当前状态、下游投影、PG/ClickHouse 计划、parse-tasks 派发和 Redis 写入侧等语义，容易造成“现状 vs 终态”混淆，也容易把第三类、第五类、第六类职责重新并入执行层。

## 决策

crawler-executor 的终态边界收敛为：

> 抓取指令进 → 原始字节落盘 + 单一 `crawl_attempt` 事件出。

本系统不持有 PostgreSQL / ClickHouse 事实层，不派发 parse-tasks，不自动 follow 链接，不向 Redis URL 队列写入任务，不做结构化抽取和内容质量评估。

文档体系同步拆分为：

- `.specify/memory/product.md`：产品定位和非目标。
- `.specify/memory/architecture.md`：终态架构和硬边界。
- `state/current.md`：当前真实状态。
- `state/roadmap.md`：能力路线图和债务。
- `state/changelog.md`：已交付能力。
- `state/decisions/`：跨 feature 决策记录。
- `specs/00X-PX-*/`：增量实施细则。

## 备选方案

- 继续保留单一 feature 文档承载所有语义。不采纳。终态、现状、路线图和决策追溯混写，门禁检查无法区分约束与坐标。
- 把 PG / ClickHouse 投影继续作为本仓库后续阶段。不采纳。事实层和画像归第五类，放在本仓库会破坏第二类边界。
- 保留 parse-tasks 派发。不采纳。第三类应直接订阅原始抓取事件，本系统不持有“谁该解析什么”的派发语义。

## 后果

- 好处：架构门禁和决策门禁变得明确，后续 plan 阶段能直接检查是否违反终态边界或已接受 ADR。
- 好处：现状层只描述当前真实形态，不再与终态规格争夺权威。
- 好处：新增 spec 可以更清楚地定位自己在 roadmap 中的位置。
- 代价：旧文档引用需要迁移。
- 代价：历史散落决策需要逐步 lazy-fill 为 ADR。

## 关联

- `.specify/memory/product.md`
- `.specify/memory/architecture.md`
- `state/current.md`
- `state/roadmap.md`
- `state/changelog.md`
- ADR-0001
- ADR-0002
