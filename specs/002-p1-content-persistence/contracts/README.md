# P1 契约

本目录定义 P1 对外消息契约。

## 当前交付

- `page-metadata.schema.json`：P1 第一版已验证的页面快照元数据消息，保留为历史兼容契约。

## 调整后目标

- `crawl-attempt.schema.json`：P1 调整后的目标消息契约。该事件描述一次 URL 抓取尝试从发起到内容处理结束的完整事实。

## 后置

- `crawl-events` topic 暂不发布。P1 调整方向是使用单一 `crawl_attempt` 事件，而不是分别发布 `crawl_logs` 与 `page_snapshots` 两类事件。
- `dead-letter` topic 暂不发布。当前没有消费方，Kafka 发布失败只记录日志和指标。
- `parse-tasks` topic 暂不设计，下游解析服务后置。
- PostgreSQL 和 ClickHouse 物理表结构可基于本目录 schema 派生，但不在当前契约中强制。

## 语义

- Kafka 投递采用 at-least-once。
- 消费端必须按 message key 或 payload 中的幂等键去重。
- 所有消息必须携带 `schema_version`。
- `crawl_attempt` 总是描述一次 attempt 的最终状态；若正文对象存储成功，则携带 `snapshot_id`、`storage_key` 等快照字段。
- `attempt_id` 表示一次抓取意图，不是 canonical URL 的唯一标识；同一 `url_hash` 可以对应多个 `attempt_id`。
- Scrapy 内部 retry 归属于同一个 `attempt_id`。
- `page-metadata` 只有在对象存储写入成功后才能发布；该语义保留为第一版兼容事实，不再作为调整后的目标事件模型。

## 消费端投影方向

消费端基于 `crawl_attempt` 事件投影：

- `crawl_logs`：每个 `attempt_id` 一行，总是写入。
- `page_snapshots`：仅当 `storage_result=stored` 时写入。
- `pages_latest`：仅从成功快照更新。

这样可以避免多个事件乱序到达导致的投影一致性问题。
