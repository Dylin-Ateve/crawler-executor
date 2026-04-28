# 研究记录：P1 抓取内容可靠持久化与元数据投递

## 待研究决策

- OCI Object Storage compartment 是否需要显式配置。
- Kafka producer 依赖选型：`confluent-kafka` 或 `kafka-python`。

## 决策记录

| 主题 | 决策 | 理由 | 替代方案 |
|------|------|------|----------|
| 写入顺序 | 先对象存储，后 Kafka metadata | 保证下游看到消息时内容已可读取 | 先发 Kafka 再补上传会产生悬空 metadata |
| 投递语义 | Kafka at-least-once + 消费端幂等 | 与已确认口径一致，复杂度可控 | exactly-once 会引入过多基础设施约束 |
| Canonical URL | 复用 P0 `canonical_url.py` 契约 | 保持 `url_hash` 与去重语义一致 | P1 重新实现会导致跨模块 key 不一致 |
| 页面版本 | P1 只保留最新快照语义 | 用户已确认定期重爬只保留最新快照 | 多版本快照增加存储和查询复杂度 |
| 解析任务 | `parse-tasks` 后置 | 用户确认暂不考虑下游解析服务 | P1 同时设计解析服务会偏离当前目标 |
| P1 边界 | 只交付 producer 链路和契约，不包含 PostgreSQL/ClickHouse 消费者 | 用户确认 P1 先聚焦 worker 到对象存储与 Kafka | 同时实现消费者会扩大范围 |
| 本地 outbox | P1 不实现本地 outbox | 用户确认不需要本地 outbox | SQLite/JSONL outbox 可作为 P2 或后续增强 |
| 内容范围 | 只存储 HTML | 用户确认字体、JS、图片等资源不需要 | 全资源抓取会显著增加存储和过滤复杂度 |
| 压缩格式 | gzip | 用户确认，且 Python 标准库可直接支持 | zstd 压缩率更好但增加依赖 |
| Outlink 详情 | P1 只记录数量，完整列表后置 P2 | 控制 Kafka metadata 消息大小 | 完整列表可能导致消息过大 |
| 对象存储接入 | 使用 OCI SDK | 用户已确认，且目标存储为 Oracle Cloud Object Storage | S3-compatible 客户端不作为 P1 路径 |
| OCI endpoint | `https://objectstorage.us-phoenix-1.oraclecloud.com` | 用户确认，region 为 `us-phoenix-1` | 运行时自动推导 endpoint 不利于排查 |
| OCI 认证模式 | `OCI_AUTH_MODE=api_key` 用于开发，`OCI_AUTH_MODE=instance_principal` 用于生产 | 用户确认双模式，并要求业务代码无感 | 单一认证模式无法同时覆盖本地开发和生产节点 |

## 需用户补充

- OCI compartment 是否需要显式配置，或只依赖 bucket/namespace 权限
