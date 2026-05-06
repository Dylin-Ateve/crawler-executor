# 契约：Kafka outbox / 故障补偿

## 目标

当 HTML 对象已写入 Object Storage，但 Kafka `crawl_attempt` 发布失败或长时间不可用时，executor 必须具备可审计的本地持久补偿和重放路径。

## 边界

- outbox 只保存待发布 `crawl_attempt`。
- outbox 不保存 URL 调度状态。
- outbox 不写入 Redis URL 队列。
- outbox 不改变 `attempt_id` 幂等语义。
- Kafka publish failure 仍不消耗 Fetch Command `max_retries`。

## 状态机

```text
pending -> publishing -> published
pending -> publishing -> failed -> pending
```

状态语义：

- `pending`：记录已持久化，等待发布。
- `publishing`：当前进程正在尝试发布。
- `published`：Kafka ack 成功，记录可保留短期审计后清理。
- `failed`：最近一次发布失败，等待退避后重试。

## 必需字段

- `outbox_id`
- `attempt_id`
- `stream`
- `stream_message_id`
- `payload_json`
- `storage_key`
- `status`
- `created_at`
- `updated_at`
- `publish_attempts`
- `last_error`

## ack 语义

M5 设计评审必须明确两种策略二选一：

1. **publish-first ack**：只有 Kafka publish 成功后才 `XACK`，outbox 仅用于本地重放同一事件。
2. **persist-first ack**：outbox 持久化成功即可 `XACK`，后续由 outbox replay 保证事件发布。

默认倾向保持 **publish-first ack**，避免第一版改变 ADR-0006 的语义。若采用 persist-first ack，必须新增 ADR。

## 指标

- `crawler_kafka_outbox_records{status}`
- `crawler_kafka_outbox_oldest_age_seconds`
- `crawler_kafka_outbox_replay_total{result}`
- `crawler_kafka_outbox_write_total{result}`
- `crawler_kafka_outbox_disk_bytes`

## 容量约束

- 必须配置最大 records 数或最大磁盘占用。
- 达到高水位必须停止读取新 Fetch Command 或进入明确保护模式。
- 清理 `published` 记录必须有保留窗口，便于审计。
