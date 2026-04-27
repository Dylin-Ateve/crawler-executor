# 契约

需求澄清后，本目录用于存放对外契约。

预期契约包括：

- Canonical URL 契约：见 `canonical-url.md`。
- `page-metadata` 的 Kafka 消息 schema。
- `crawl-events` 的 Kafka 消息 schema。
- `parse-tasks` 的 Kafka 消息 schema。下游解析服务设计暂不纳入当前阶段，因此该契约后置。
- 存储或发布失败时使用的死信消息 schema。
- 可选的运维 API 契约，例如 health 和 readiness endpoint。

## 已确认消息语义

- Kafka 接受 at-least-once 投递语义。
- 消费端必须按业务主键实现幂等写入。
- 下游解析服务暂不设计，`parse-tasks` 不作为当前阶段交付内容。
