# ADR-0001: 放弃 Heritrix，从 Scrapy 起步独立演进

**状态**：已接受
**日期**：2026-04-29

## 背景

crawler-executor 需要作为系统群第二类抓取执行系统长期演进。既有 Heritrix 链路包含自动 follow、抓取决策和链路内职责渗透等历史行为，不符合“执行层尽量哑”的目标。

团队需要选择是继承 Heritrix 资产继续改造，还是以 Scrapy 技术栈重新建立第二类执行系统。

## 决策

crawler-executor 从 Scrapy 技术栈起步，独立规划和演进；不继承 Heritrix 抓取链路，也不复用 Heritrix 的自动 follow、任务决策或解析派发行为。

Scrapy 是本系统的基线抓取框架。未来 JS 渲染、现代反爬等能力也应在第二类内部围绕该执行系统演进，而不是新建平行系统。

## 备选方案

- 继续改造 Heritrix：不采纳。历史链路职责边界不清，容易把抓取决策、链接发现和解析派发继续留在执行层。
- 使用 Colly（Go）：不采纳。团队和下游解析生态以 Python 为主，语言栈不一致带来的长期成本高于当前性能收益。
- 使用 Crawlee + Playwright 作为主框架：不采纳。浏览器渲染适合强反爬场景，但当前基线需求是高吞吐原始字节抓取。
- 自研抓取框架：不采纳。重复造轮，长期维护成本高，且不符合快速验证和可横向扩展目标。

## 后果

- 好处：执行链路更轻，Python 生态一致，便于快速验证多出口 IP、对象存储和事件 producer。
- 好处：Heritrix 历史职责渗透不会自动进入新系统。
- 代价：旧 Heritrix 数据迁移、对比验证和最终下线需要后续单独规划。
- 代价：强反爬和浏览器渲染能力需要后续在 Scrapy 基线旁补齐。

## 关联

- `.specify/memory/product.md`
- `.specify/memory/architecture.md`
- `specs/001-scrapy-distributed-crawler/`
