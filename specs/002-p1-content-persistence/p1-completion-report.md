# P1 完结报告：抓取内容可靠持久化与元数据投递

**日期**：2026-04-28  
**状态**：P1 producer 链路完成  
**范围**：Scrapy HTML 抓取结果写入 OCI Object Storage，并发布 Kafka `page-metadata` 契约消息。

## 完结结论

P1 已完成原定目标：在 P0 Scrapy worker 基础上，补齐 HTML 内容持久化与 Kafka 元数据投递链路。当前实现遵守“对象存储先写入，Kafka metadata 后发布”的关键不变量，并对对象存储失败和 Kafka 失败分别验证了预期行为。

P1 不包含 PostgreSQL、ClickHouse、下游解析服务、本地 outbox、分布式调度、K8s 编排和对象生命周期清理。这些能力继续保留到后续阶段。

## 已交付能力

| 能力 | 状态 | 说明 |
|------|------|------|
| HTML gzip 持久化 | 完成 | HTML 响应压缩为 `.html.gz` 对象并写入 OCI Object Storage。 |
| OCI SDK 接入 | 完成 | 支持 `api_key` 与 `instance_principal` 双模式，业务 pipeline 无感。 |
| Kafka `page-metadata` producer | 完成 | 使用 `confluent-kafka`，启用 idempotence、ack、retry、timeout 和 bounded flush。 |
| 消息契约 | 完成 | 定义并校验 `page-metadata` schema，message key 使用 `snapshot_id`。 |
| canonical URL / `url_hash` | 完成 | canonical URL 契约已独立抽象，`url_hash` 基于 canonical URL。 |
| 存储 key | 完成 | 使用 `pages/v1/{yyyy}/{mm}/{dd}/{host_hash}/{url_hash}/{snapshot_id}.html.gz`。 |
| 非 HTML 跳过 | 完成 | 非 HTML 不写对象存储，不发布 Kafka，仅记录日志与指标。 |
| outlink 统计 | 完成 | 记录总 outlink 数和站外 outlink 数，完整列表后置。 |
| 指标 | 完成 | 增加对象存储上传、Kafka 发布和内容跳过指标。 |
| 失败路径 | 完成 | 对象存储失败不发布 metadata；Kafka 失败保留对象并记录发布失败。 |

## 真实验证结果

| 验证项 | 结果 | 证据 |
|--------|------|------|
| Kafka smoke | 通过 | `p1_kafka_smoke_ok`，topic=`crawler.page-metadata.v1`。 |
| Object Storage smoke | 通过 | 写入、读取、gzip 解压校验通过，bucket=`clawer_content_staging`。 |
| 端到端抓取 | 通过 | `https://www.wikipedia.org/` 抓取、对象写入、metadata 发布成功。 |
| 对象存储失败保护 | 通过 | 不存在 bucket 场景出现 `p1_storage_upload_failed`，未发布 metadata。 |
| Kafka 失败记录 | 通过 | broker=`127.0.0.1:1` 场景出现 `p1_kafka_publish_failed`，对象已写入。 |

## 重要实现决策

### gzip 存储语义

P1 将 HTML 内容压缩为 gzip 字节并以 `.html.gz` 归档对象保存。上传时不设置 HTTP `Content-Encoding: gzip`，避免 OCI SDK 或 HTTP 客户端读取时自动解压，导致下游无法稳定判断对象字节格式。

压缩格式通过对象 metadata `compression=gzip` 和 Kafka `compression=gzip` 字段表达。

### Kafka 失败处理

P1 不实现本地 outbox。Kafka 发布失败时：

- 已上传对象保留在 Object Storage。
- pipeline 记录 `p1_kafka_publish_failed`。
- 指标记录 Kafka publish failure。
- 下游依赖 at-least-once 和消费端幂等，完整补偿重放机制后置。

### 网络前置条件

Kafka bootstrap 解析为私网地址 `10.0.4.155`。目标爬虫节点 `10.0.12.196` 需要 Kafka 子网 / NSG / Security List 放通 `10.0.12.0/24` 或更精确的 `/32` 到 `TCP 9092` 的 ingress。

## 已知限制

- 本次 P1 端到端验证未启用 `REDIS_URL`，因此未同时验证 P0 出口 IP 轮换与 P1 持久化组合链路。
- 未实现 scrapy-redis 分布式调度、URL 去重和跨节点队列。
- 未实现 PostgreSQL/ClickHouse 消费者。
- 未发布 `crawl-events`、`parse-tasks` 和 dead-letter topic。
- 未实现对象存储生命周期策略和旧快照清理。
- 未进行 24 小时稳定性压测和目标吞吐验证。

## 后续建议

P1 可以正式收口。下一阶段建议二选一：

1. 优先做消费者与最新快照索引：PostgreSQL pages 表、Kafka consumer、metadata 层只保留最新快照。
2. 优先做编排部署：K8s DaemonSet、hostNetwork、节点环境变量和实例主体认证落地。

若按原始 feature 文档的依赖关系推进，建议先补消费者与 metadata 落库，再进入大规模 K8s 编排。
