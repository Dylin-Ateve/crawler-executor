# 规格驱动开发工作区

本目录按 Spec Kit 风格组织规格驱动开发材料，用于沉淀项目章程、产品定位、终态架构、功能规格、技术计划、研究结论、数据模型、契约和任务拆解。

## 工作流程

启动新 spec 前：

1. 阅读 `.specify/memory/constitution.md`，确认章程原则。
2. 阅读 `.specify/memory/product.md`，确认系统定位、目标和非目标。
3. 阅读 `.specify/memory/architecture.md`，确认终态边界和明确不做。
4. 阅读 `state/current.md`，确认当前真实形态。
5. 阅读 `state/roadmap.md`，确认本阶段在路线图中的位置。
6. 阅读 `state/decisions/`，确认已接受的 ADR。

创建或更新 spec 时：

1. 在 `specs/00X-PX-*/spec.md` 中维护本阶段需求。
2. 在 `plan.md` 中执行章程 / 产品 / 架构 / 决策门禁检查。
3. 在 `research.md`、`data-model.md`、`contracts/` 和 `quickstart.md` 中补充阶段性实施细节。
4. 只有在规格和设计材料稳定后，才生成或更新 `tasks.md`。

实施完成后：

1. 更新 `state/current.md`。
2. 更新 `state/changelog.md`。
3. 更新 `state/roadmap.md`。
4. 如产生跨 feature 决策，补充 `state/decisions/NNNN-*.md`。
