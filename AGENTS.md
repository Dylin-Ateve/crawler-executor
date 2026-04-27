# 自动化助手协作说明（AGENTS.md）

## 项目说明

本仓库用于推进基于 Scrapy 的分布式爬虫系统设计与落地。当前工作采用 spec-kit 风格组织需求、方案、研究、数据模型、契约和任务拆解。

核心输入文档：

- `scrapy-distributed-crawler-feature.md`：原始需求与总体方案说明。
- `specs/001-scrapy-distributed-crawler/spec.md`：功能规格说明。
- `specs/001-scrapy-distributed-crawler/plan.md`：技术实施计划。
- `specs/001-scrapy-distributed-crawler/tasks.md`：任务拆解。
- `specs/001-scrapy-distributed-crawler/p0-implementation.md`：P0 PoC 实施拆解。

## 沟通要求

- 仓库沟通与维护说明默认使用中文，涉及外部合作或多语言文档时另行标注。
- 与该项目协作的自动化助手需保持中文回应，确保团队交流一致。
- 代码评审、问题跟踪及每日同步事项均优先通过中文描述，特殊情况下再提供英文补充。

## 协作原则

- 先澄清需求，再进入详细设计；未明确的点应在规格文档中标注为 `NEEDS CLARIFICATION`。
- 方案变更应优先更新 `specs/001-scrapy-distributed-crawler/` 下的规格、计划或任务文档。
- P0 阶段聚焦单节点 Scrapy 多出口 IP PoC，不提前扩展到完整生产链路。
- Kafka、对象存储、PostgreSQL、ClickHouse、K8s、Terraform 等生产能力应在 P1/P2 阶段逐步纳入。
- 实施任务应保持可验证、可回滚、可独立验收。

## 文档维护规范

- 需求变更写入 `spec.md`。
- 技术方案和架构决策写入 `plan.md` 或 `research.md`。
- 数据结构、消息字段、存储模型写入 `data-model.md` 或 `contracts/`。
- 可执行步骤、验证命令、运行前置条件写入 `quickstart.md`。
- 开发任务和验收任务写入 `tasks.md`。

## 自动化助手工作约定

- 修改文件前先阅读相关上下文，避免覆盖团队已有内容。
- 优先使用仓库已有结构和 spec-kit 文档组织方式。
- 对不确定的基础设施、网络、合规和性能目标，应先提出澄清问题。
- 输出结论时应说明已修改的文件和下一步建议。
- 除非用户明确要求，不应执行破坏性操作或回滚他人改动。
