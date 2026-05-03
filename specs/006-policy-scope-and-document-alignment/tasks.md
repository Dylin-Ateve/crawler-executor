# 任务：策略作用域与文档 / 命名校准

## 阶段 1：决策与文档

- [x] T001 新增 ADR-0014，明确不使用 `HostGroup` 作为 executor 一等概念。
- [x] T002 新增 ADR-0014，明确 Redis / Valkey Streams consumer group 是当前已接受下发载体。
- [x] T003 更新北极星层，移除 `scrapy-redis` 未来运行形态表述。
- [x] T004 更新 roadmap，重写 M4 目标。
- [x] T005 更新现状层和 changelog，记录本次校准。

## 阶段 2：代码命名清理

- [x] T006 删除当前代码主路径的 `page_metadata` publisher 兼容入口。
- [x] T007 删除未使用的 `KAFKA_TOPIC_PAGE_METADATA` 设置。
- [x] T008 删除未使用的 `validate_page_metadata` 代码。
- [x] T009 将 Python package metadata 从 P0 PoC 名称改为 `crawler-executor`。

## 阶段 3：事件上下文透传

- [x] T010 扩展 `crawl_attempt` payload，透传 Fetch Command 执行上下文。
- [x] T011 扩展 `crawl_attempt` JSON schema。
- [x] T012 增加 / 调整单元测试。

## 阶段 4：验证

- [x] T013 运行单元测试。
- [x] T014 运行文本审计，确认北极星层无旧分组概念和未来外置 scheduler 目标残留。
