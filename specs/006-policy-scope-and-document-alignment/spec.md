# 功能规格：策略作用域与文档 / 命名校准

**创建日期**：2026-05-03  
**状态**：已完成  
**Roadmap 位置**：M4 前置校准。  
**关联 ADR**：ADR-0014。  
**文档层级**：增量层 / 短期校准 spec。

## 背景

004 / 005 已在 staging 等价镜像环境完成验证。准备推进 M4 前，团队复核发现北极星文档仍残留 `HostGroup`、`scrapy-redis` 和 P1 第一版 `page_metadata` 等历史概念。这些概念与当前代码事实和已接受 ADR 不完全一致，可能误导 M4 设计。

当前代码事实是：

- 输入侧采用 Redis / Valkey Streams consumer group。
- 不使用 scrapy-redis 默认 scheduler / dupefilter。
- 事件侧收敛为单一 `crawl_attempt`。
- Fetch Command 已支持 `tier`、`site_id`、`host_id`、`politeness_key` 等执行上下文。

本 spec 只做边界和命名校准，不实现完整控制平面策略热加载。

## 目标

1. 新增 ADR-0014，明确控制平面策略作用域和 Redis Streams 边界。
2. 修正北极星层中 `HostGroup`、`scrapy-redis` 和过期阶段性非目标描述。
3. 修正 roadmap 中 M4 的目标表述。
4. 清理当前代码主路径中已经无用的 `page_metadata` 兼容入口和 P0 包名。
5. 让 `crawl_attempt` 透传已有 Fetch Command 执行上下文字段。

## 非目标

- 不实现 M4 控制平面策略源。
- 不实现策略热加载、last-known-good 或作用域 pause。
- 不改变 Redis Streams ack / PEL / reclaim 语义。
- 不删除历史 spec 中用于追溯的 P1 第一版 `page-metadata` 契约记录。
- 不引入 scrapy-redis。

## 范围

### 文档范围

- `.specify/memory/product.md`
- `.specify/memory/architecture.md`
- `state/roadmap.md`
- `state/current.md`
- `state/changelog.md`
- `state/decisions/README.md`
- `README.md`

### 代码范围

- `src/crawler/crawler/pipelines.py`
- `src/crawler/crawler/schemas.py`
- `src/crawler/crawler/publisher.py`
- `src/crawler/crawler/settings.py`
- `specs/002-p1-content-persistence/contracts/crawl-attempt.schema.json`
- `pyproject.toml`
- `setup.py`
- `deploy/examples/p1.env.example`

## 验收标准

1. 北极星层不再把 `HostGroup` 写作 crawler-executor 一等概念。
2. 北极星层不再把 `scrapy-redis` 写作未来运行形态或下发接口。
3. M4 目标使用 `tier / site_id / host_id / politeness_key / policy_scope_id` 等策略作用域。
4. 当前代码主路径不再暴露 `build_page_metadata_publisher`、`PageMetadataPublisher` 或 `KAFKA_TOPIC_PAGE_METADATA`。
5. Python package metadata 使用 `crawler-executor`。
6. `crawl_attempt` payload 和 schema 支持上游执行上下文字段透传。
7. 单元测试通过。
