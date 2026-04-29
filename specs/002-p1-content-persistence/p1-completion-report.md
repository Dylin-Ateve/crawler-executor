# P1 完结报告：抓取内容可靠持久化与元数据投递

**日期**：2026-04-29
**状态**：P1 第一版 producer 链路完成；`crawl_attempt` 调整已实现，待目标节点重跑验证
**范围**：Scrapy HTML 抓取结果写入 OCI Object Storage，并发布 Kafka producer 契约消息。

## 完结结论

P1 第一版已完成原定目标：在 P0 Scrapy worker 基础上，补齐 HTML 内容持久化与 Kafka `page-metadata` 投递链路。当前实现遵守“对象存储先写入，Kafka metadata 后发布”的关键不变量，并对对象存储失败和 Kafka 失败分别验证了预期行为。

基于 2026-04-29 的设计复盘，P1 最终目标调整为单一 `crawl_attempt` producer。代码已将 producer topic、payload builder、成功/跳过/存储失败分支收敛为 `crawl_attempt`，并由消费端投影 `crawl_logs`、`page_snapshots` 和 `pages_latest`；真实节点仍需重跑验证。

P1 不包含 PostgreSQL、ClickHouse、下游解析服务、本地 outbox、分布式调度、K8s 编排和对象生命周期清理。其中 PostgreSQL 抓取记录保存建议进入下一阶段；ClickHouse 分析能力、Terraform/cloud-init 自动化和下游解析服务后置。

## 已交付能力

| 能力 | 状态 | 说明 |
|------|------|------|
| HTML gzip 持久化 | 完成 | HTML 响应压缩为 `.html.gz` 对象并写入 OCI Object Storage。 |
| OCI SDK 接入 | 完成 | 支持 `api_key` 与 `instance_principal` 双模式，业务 pipeline 无感。 |
| Kafka `page-metadata` producer | 完成 | 使用 `confluent-kafka`，启用 idempotence、ack、retry、timeout 和 bounded flush。 |
| Kafka `crawl_attempt` producer | 已实现，待重验 | 默认 topic 调整为 `crawler.crawl-attempt.v1`，message key 使用 `attempt_id`。 |
| 消息契约 | 完成 | 保留 `page-metadata` 历史契约，新增并校验 `crawl_attempt` schema。 |
| canonical URL / `url_hash` | 完成 | canonical URL 契约已独立抽象，`url_hash` 基于 canonical URL。 |
| 存储 key | 完成 | 使用 `pages/v1/{yyyy}/{mm}/{dd}/{host_hash}/{url_hash}/{snapshot_id}.html.gz`。 |
| 非 HTML 跳过 | 已调整 | 非 HTML 不写对象存储，但发布 `storage_result=skipped` 的 `crawl_attempt`。 |
| outlink 统计 | 完成 | 记录总 outlink 数和站外 outlink 数，完整列表后置。 |
| 指标 | 完成 | 增加对象存储上传、Kafka 发布和内容跳过指标。 |
| 失败路径 | 已调整 | 对象存储失败发布 `storage_result=failed` 的 `crawl_attempt`；Kafka 失败保留对象并记录发布失败。 |

## 真实验证结果

| 验证项 | 结果 | 证据 |
|--------|------|------|
| Kafka smoke | 通过 | `p1_kafka_smoke_ok`，topic=`crawler.page-metadata.v1`。 |
| Object Storage smoke | 通过 | 写入、读取、gzip 解压校验通过，bucket=`clawer_content_staging`。 |
| 端到端抓取 | 通过 | `https://www.wikipedia.org/` 抓取、对象写入、metadata 发布成功。 |
| 对象存储失败保护 | 通过 | 不存在 bucket 场景出现 `p1_storage_upload_failed`，未发布 metadata。 |
| Kafka 失败记录 | 通过 | broker=`127.0.0.1:1` 场景出现 `p1_kafka_publish_failed`，对象已写入。 |

说明：上表验证结果为 2026-04-28 的 P1 第一版真实节点记录。`crawl_attempt` 调整已经完成本地语法验证和核心函数手动验证，仍需执行 T055 目标节点重验。

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
- 未实现 PostgreSQL 抓取记录保存与最新快照索引。
- ClickHouse Host profile 暂不进入近期规划。
- 未发布 `crawl-events`、`parse-tasks` 和 dead-letter topic。
- 未实现对象存储生命周期策略和旧快照清理。
- 未进行 24 小时稳定性压测和目标吞吐验证。

## 后续建议

P1 第一版可以收口，`crawl_attempt` producer 调整也已完成代码落地。下一步先执行目标节点重验，再进入抓取记录保存与最新快照索引：

1. 重新验证成功 HTML、非 HTML/非 200、对象存储失败和 Kafka 失败分支。
2. 确认 Kafka smoke 输出 `topic=crawler.crawl-attempt.v1`，key 为 `attempt_id`。
3. 确认端到端脚本可读取 `crawl_attempt.storage_key` 指向的 gzip 对象。
4. 后续再实现 PostgreSQL `crawl_logs/page_snapshots/pages_latest` 投影。

ClickHouse、Terraform/cloud-init 和大规模 K8s 编排暂不作为下一阶段入口。
