# 自动化助手协作说明（AGENTS.md）

## 项目说明

本仓库用于推进 crawler-executor（企业级内容生产系统群中的第二类：抓取执行系统）的设计与落地。当前工作采用 spec-kit 风格组织北极星约束、现状追踪、架构决策和增量实施细则。

**文档体系治理**：本仓库规格性文档分为“北极星层 / 现状层 / 增量层”三层。修改任何规格文档前必须先确认目标内容属于哪一层，避免把终态约束、当前状态和短期实施细节混写。

核心输入文档：

- `.specify/memory/constitution.md`：项目章程，定义 spec-kit 基本治理原则。
- `.specify/memory/product.md`：**北极星层**，定义系统定位、服务对象、核心目标、永久非目标和阶段性非目标。
- `.specify/memory/architecture.md`：**北极星层**，定义第二类终态架构、系统边界、明确不做、事件模型纲领和系统级验收标准。
- `state/current.md`：**现状层**，记录当前真实形态、模块完成度、技术债和与终态的差距。
- `state/roadmap.md`：**现状层**，记录能力里程碑、跨阶段债务、后置清单和下一阶段建议。
- `state/changelog.md`：**现状层**，记录已交付能力、spec 合并摘要和关键 ADR 链接。
- `state/decisions/`：**现状层 / ADR**，记录跨 feature 持续生效的架构决策。
- `specs/001-scrapy-distributed-crawler/`：**增量层**，P0 单节点 Scrapy 多出口 IP PoC。
- `specs/002-p1-content-persistence/`：**增量层**，P1 抓取内容可靠持久化与 `crawl_attempt` 投递。

## 沟通要求

- 仓库沟通与维护说明默认使用中文，涉及外部合作或多语言文档时另行标注。
- 与该项目协作的自动化助手需保持中文回应，确保团队交流一致。
- 代码评审、问题跟踪及每日同步事项均优先通过中文描述，特殊情况下再提供英文补充。

## 协作原则

- 先澄清需求，再进入详细设计；未明确的点应在规格文档中标注为 `NEEDS CLARIFICATION`。
- 新 spec 创建前必须阅读 `.specify/memory/product.md`、`.specify/memory/architecture.md`、`state/current.md`、`state/roadmap.md` 和 `state/decisions/`。
- plan 阶段必须检查是否违反 `.specify/memory/architecture.md` 的明确不做清单，或违反任何“已接受”的 ADR。
- 如某个 spec 必须改变终态边界，必须先新增 ADR，再更新 `.specify/memory/architecture.md` 与现状层差距说明。
- P0/P1 的实施细节优先更新对应 `specs/00X-PX-*/` 目录，不把 SDK、字段表、YAML、settings 配置写回北极星层。
- 实施任务应保持可验证、可回滚、可独立验收。

## 文档维护规范

- 产品定位、系统价值、永久非目标写入 `.specify/memory/product.md`。
- 终态架构、系统边界、明确不做、跨系统契约纲领写入 `.specify/memory/architecture.md`。
- 当前真实形态、模块完成度、运行状态写入 `state/current.md`。
- 路线图、跨阶段债务、后置能力写入 `state/roadmap.md`。
- 已交付能力和合并摘要写入 `state/changelog.md`。
- 跨 feature 架构决策写入 `state/decisions/NNNN-*.md`。
- 单个 P 阶段的需求变更写入对应 `specs/00X-PX-*/spec.md`。
- 技术方案和阶段性架构设计写入对应 `plan.md` 或 `research.md`。
- 数据结构、消息字段、存储模型写入对应 `data-model.md` 或 `contracts/`。
- 可执行步骤、验证命令、运行前置条件写入对应 `quickstart.md`。
- 开发任务和验收任务写入对应 `tasks.md`。

## 门禁检查

| 门禁 | 来源 | 触发位置 |
|---|---|---|
| 章程门禁 | `.specify/memory/constitution.md` | spec 创建时 |
| 产品门禁 | `.specify/memory/product.md` | spec 创建时 |
| 架构门禁 | `.specify/memory/architecture.md` | plan 阶段 |
| 决策门禁 | `state/decisions/` | plan 阶段 |
| 路线图对齐 | `state/roadmap.md` | spec 创建时参考 |

前四项是约束，路线图对齐是坐标。不能用当前路线图状态覆盖北极星层约束。

## 自动化助手工作约定

- 修改文件前先阅读相关上下文，避免覆盖团队已有内容。
- 优先使用仓库已有结构和 spec-kit 文档组织方式。
- 对不确定的基础设施、网络、合规和性能目标，应先提出澄清问题。
- 输出结论时应说明已修改的文件和下一步建议。
- 除非用户明确要求，不应执行破坏性操作或回滚他人改动。
