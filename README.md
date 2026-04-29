# crawler-executor

crawler-executor 是企业级内容生产系统群中的 **第二类：抓取执行系统（Fetching & Rendering）** 的实现仓库。

系统边界是：**抓取指令进 → 原始字节落盘 + 单一 `crawl_attempt` 事件出**。

## 文档入口

建议按以下顺序阅读：

1. `.specify/memory/constitution.md`：项目章程。
2. `.specify/memory/product.md`：系统定位、目标和非目标。
3. `.specify/memory/architecture.md`：终态架构、边界、事件模型和系统级验收。
4. `state/current.md`：当前真实形态和完成度。
5. `state/roadmap.md`：后续能力路线图和跨阶段债务。
6. `state/decisions/README.md`：ADR 索引与模板。
7. `specs/001-scrapy-distributed-crawler/`：P0 单节点 Scrapy 多出口 IP PoC。
8. `specs/002-p1-content-persistence/`：P1 内容可靠持久化与 `crawl_attempt` producer。

## 文档分层

| 层级 | 位置 | 职责 |
|---|---|---|
| 北极星层 | `.specify/memory/` | 少变约束：产品定位、终态架构、明确不做、系统级验收 |
| 现状层 | `state/` | 活文档：当前状态、路线图、交付记录、ADR |
| 增量层 | `specs/00X-PX-*/` | 单个 P 阶段的需求、计划、契约、任务和验证步骤 |

## 工作流

启动新 spec 时：

- 读取 `.specify/memory/product.md` 和 `.specify/memory/architecture.md`，确认定位和边界。
- 读取 `state/current.md` 和 `state/roadmap.md`，确认当前能力与里程碑位置。
- 读取 `state/decisions/`，确认已有已接受 ADR。
- 在 `specs/00X-PX-*/` 下创建增量规格。

技术规划时：

- 检查是否违反 architecture 的“明确不做”清单。
- 检查是否违反已接受的 ADR。
- 如需改变终态边界，先新增 ADR，再修改北极星层和现状层差距说明。

实施完成后：

- 更新 `state/current.md`。
- 更新 `state/changelog.md`。
- 更新 `state/roadmap.md`。
- 如产生跨 feature 决策，补充 `state/decisions/NNNN-*.md`。

## 当前状态

P0 单节点 Scrapy 多出口 IP PoC 已验证。P1 `crawl_attempt` producer 已通过目标节点 T055 验证，下一阶段准备规划第六类队列只读消费与多 worker 运行形态。
