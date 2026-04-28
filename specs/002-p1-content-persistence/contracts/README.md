# P1 契约

本目录定义 P1 对外消息契约。

## 当前交付

- `page-metadata.schema.json`：页面快照元数据消息。

## 后置

- `crawl-events` topic 暂不发布。当前没有消费方，P1 仅通过日志和指标记录非 HTML、失败和跳过原因。
- `dead-letter` topic 暂不发布。当前没有消费方，Kafka 发布失败只记录日志和指标。
- `parse-tasks` topic 暂不设计，下游解析服务后置。
- PostgreSQL 和 ClickHouse 物理表结构可基于本目录 schema 派生，但不在当前契约中强制。

## 语义

- Kafka 投递采用 at-least-once。
- 消费端必须按 message key 或 payload 中的幂等键去重。
- 所有消息必须携带 `schema_version`。
- `page-metadata` 只有在对象存储写入成功后才能发布。
