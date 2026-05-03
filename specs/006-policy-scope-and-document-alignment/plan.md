# 实施计划：策略作用域与文档 / 命名校准

## 技术上下文

**语言 / 框架**：Python 3.11、Scrapy、Redis client、confluent-kafka  
**约束**：保持第二类执行器边界；不引入控制平面实现；不改变 Redis Streams 消费确认语义  
**关联决策**：ADR-0014

## 实施步骤

1. 新增 ADR-0014，裁定策略作用域词汇、Redis Streams 边界和历史命名清理方向。
2. 更新北极星层：
   - `HostGroup` 改为中性策略作用域。
   - `scrapy-redis` 从终态运行形态中移除。
   - 过期阶段性非目标改为现状 / roadmap 口径。
3. 更新现状层：
   - M4 目标改写为控制平面执行策略热加载。
   - 记录 006 的交付与剩余 M4 工作。
4. 清理代码主路径：
   - 删除 `page_metadata` publisher alias / builder。
   - 删除未使用的 `KAFKA_TOPIC_PAGE_METADATA` 设置。
   - 删除未使用的 `validate_page_metadata` 代码。
   - 包名从 P0 PoC 调整为 `crawler-executor`。
5. 扩展 `crawl_attempt`：
   - payload 增加 `command_id`、`trace_id`、`job_id`、`host_id`、`site_id`、`tier`、`politeness_key`、`policy_scope_id`。
   - schema 增加上述可选字段。
6. 运行测试和关键文本审计。

## 风险与控制

- 删除历史兼容代码可能影响外部直接 import：当前仓库内无引用；如果外部仍依赖，应通过版本发布说明处理。
- `crawl_attempt` 增加字段会改变 schema：字段均为可选，保持向后兼容。
- 历史 spec 不做大规模改写：仅修正会继续误导后续工作的文字。

