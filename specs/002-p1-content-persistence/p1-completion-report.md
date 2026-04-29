# P1 完结报告：抓取内容可靠持久化与 `crawl_attempt` 投递

**日期**：2026-04-29
**状态**：P1 `crawl_attempt` producer 链路已通过目标节点 T055 验证
**范围**：Scrapy 抓取结果写入 OCI Object Storage，并发布单一 `crawl_attempt` Kafka producer 契约消息。

## 完结结论

P1 已完成最终目标：在 P0 Scrapy worker 基础上，补齐 HTML 内容持久化与 Kafka `crawl_attempt` 投递链路。当前实现遵守“成功快照先写对象存储，再发布 `storage_result=stored` 的 `crawl_attempt`”这一关键不变量，并对成功 HTML、非 HTML 跳过、对象存储失败和 Kafka 失败分别验证了预期行为。

基于 2026-04-29 的设计复盘，P1 已从第一版 `page-metadata` producer 收敛为单一 `crawl_attempt` producer。代码已将 producer topic、payload builder、成功/跳过/存储失败分支收敛为 `crawl_attempt`，并由消费端投影 `crawl_logs`、`page_snapshots` 和 `pages_latest`。

P1 不包含 PostgreSQL、ClickHouse、下游解析服务、本地 outbox、分布式调度、K8s 编排和对象生命周期清理。其中 PostgreSQL/ClickHouse 事实层归第五类，本仓库后续优先进入第六类队列只读消费与多 worker 运行形态。

## 已交付能力

| 能力 | 状态 | 说明 |
|------|------|------|
| HTML gzip 持久化 | 完成 | HTML 响应压缩为 `.html.gz` 对象并写入 OCI Object Storage。 |
| OCI SDK 接入 | 完成 | 支持 `api_key` 与 `instance_principal` 双模式，业务 pipeline 无感。 |
| Kafka `page-metadata` producer | 历史完成 | P1 第一版已验证，现作为兼容参考保留。 |
| Kafka `crawl_attempt` producer | 完成 | 默认 topic 调整为 `crawler.crawl-attempt.v1`，message key 使用 `attempt_id`，已通过目标节点 T055 验证。 |
| 消息契约 | 完成 | 保留 `page-metadata` 历史契约，新增并校验 `crawl_attempt` schema。 |
| canonical URL / `url_hash` | 完成 | canonical URL 契约已独立抽象，`url_hash` 基于 canonical URL。 |
| 存储 key | 完成 | 使用 `pages/v1/{yyyy}/{mm}/{dd}/{host_hash}/{url_hash}/{snapshot_id}.html.gz`。 |
| 非 HTML 跳过 | 完成 | 非 HTML 不写对象存储，但发布 `storage_result=skipped` 的 `crawl_attempt`。 |
| outlink 统计 | 完成 | 记录总 outlink 数和站外 outlink 数，完整列表后置。 |
| 指标 | 完成 | 增加对象存储上传、Kafka 发布和内容跳过指标。 |
| 失败路径 | 完成 | 对象存储失败发布 `storage_result=failed` 的 `crawl_attempt`；Kafka 失败保留对象并记录发布失败。 |

## 真实验证结果

| 验证项 | 结果 | 证据 |
|--------|------|------|
| Kafka `crawl_attempt` smoke | 通过 | `p1_kafka_smoke_ok`，topic=`crawler.crawl-attempt.v1`，key=`77d1ac3bdf379bdf4b24601e6bc6c63d0d99c7adeeabc770f040f1106ea4d6dd:attempt:1777452706598`。 |
| Object Storage smoke | 通过 | 写入、读取、gzip 解压校验通过，bucket=`clawer_content_staging`，key=`smoke/p1/object-storage-smoke-20260429T085147Z.txt.gz`。 |
| 成功 HTML 端到端抓取 | 通过 | `https://www.wikipedia.org/` 发布 `storage_result=stored`，`storage_key` 可读取并 gzip 解压，`verified_uncompressed_size=92443`。 |
| 非 HTML 跳过 | 通过 | `https://www.wikipedia.org/static/favicon/wikipedia.ico` 发布 `storage_result=skipped`，reason=`non_html_content`。 |
| 对象存储失败保护 | 通过 | 不存在 bucket 场景出现 `p1_storage_upload_failed`，并发布 `storage_result=failed` 的 `crawl_attempt`。 |
| Kafka 失败记录 | 通过 | broker=`127.0.0.1:1` 场景出现 `p1_kafka_publish_failed`，对象已写入且可读取。 |

说明：上表验证结果来自 2026-04-29 目标节点 T055 重验与 skipped 补充验证。验证时未配置 `REDIS_URL`，因此 P0 的 `LocalIpRotationMiddleware` 与 `IpHealthCheckMiddleware` 被禁用；该结果证明 P1 对象存储与 `crawl_attempt` producer 链路通过，不等同于 P0+P1 组合链路压测。

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
- T055 未覆盖连接级 fetch 失败；当前代码已支持 `fetch_result` 字段和 schema 枚举，但 downloader 连接失败转 `crawl_attempt(fetch_result=failed)` 的 errback 链路仍需后续补强。
- 未实现 scrapy-redis 分布式调度、URL 去重和跨节点队列。
- PostgreSQL 抓取记录保存与最新快照索引归第五类消费端投影，不在本仓库实现。
- ClickHouse Host profile 归第五类，不在本仓库实现。
- 未发布 `crawl-events`、`parse-tasks` 和 dead-letter topic。
- 未实现对象存储生命周期策略和旧快照清理。
- 未进行 24 小时稳定性压测和目标吞吐验证。

## 后续建议

P1 可以收口。下一阶段建议新开 `003` spec，聚焦“第六类队列只读消费与多 worker 运行形态”：

1. 回补 ADR-0003：Redis 队列写入侧归第六类，本系统只读消费。
2. 定义第六类下发抓取指令的最小消息格式。
3. 接入 Redis / scrapy-redis 形态的只读消费。
4. 补强连接级 fetch 失败到 `crawl_attempt(fetch_result=failed)` 的事件化路径。
5. 验证本系统不写 Redis 队列、不 enqueue outlinks、不维护上游去重语义。
6. 暂不纳入 PostgreSQL/ClickHouse 消费端投影、K8s DaemonSet 和控制平面策略运行时覆盖。
