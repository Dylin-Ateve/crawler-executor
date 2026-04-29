# 实施计划：P1 抓取内容可靠持久化与 crawl_attempt 投递

**分支**：`002-p1-content-persistence`
**日期**：2026-04-27
**规格文档**：`specs/002-p1-content-persistence/spec.md`

## 摘要

P1 在 P0 Scrapy worker 基础上补齐 producer 数据链路：一次 URL 抓取 attempt 完成后发布 Kafka `crawl_attempt` 事件；若该 attempt 成功产出 HTML 正文，则先写入 Oracle Cloud Object Storage，再在同一事件中携带快照字段。P1 的重点不是扩容，也不是事件分析，而是建立可恢复、可重放、可幂等消费的抓取尝试契约。

## 技术上下文

**语言/版本**：Python 3.9+，目标节点已验证 Python 3.9.25
**主要依赖**：Scrapy、redis-py、Kafka producer、OCI SDK、prometheus-client
**存储**：Oracle Cloud Object Storage bucket `clawer_content_staging`
**测试**：pytest 单元测试、pipeline 集成测试、对象存储/Kafka 端到端 smoke test
**目标平台**：真实 Linux 爬虫节点，后续可迁移到 Kubernetes
**项目类型**：数据采集管道
**性能目标**：不降低 P0 小规模验证吞吐；正式吞吐目标待 Step 9/10 和 P1 数据链路压测确认
**约束**：成功快照中的 HTML 必须先于 `crawl_attempt` 可见；Kafka 使用 at-least-once；消费者必须幂等；不做本地 outbox；解析服务后置
**规模/范围**：单节点 P1 可靠性切片，先覆盖受控 URL 集和小规模真实目标

## 章程检查

- 规格先行：通过，P1 先定义对象存储、Kafka `crawl_attempt` 契约和失败语义。
- 运维安全：通过，沿用 P0 politeness、并发上限和批准目标范围。
- 数据可靠性：通过，明确成功快照先写对象存储、再发布 `crawl_attempt`；Kafka 失败仅记录日志和指标，不做本地 outbox。
- 增量交付：通过，先做 producer 与契约，再推进消费者或分析链路。
- 可度量验收：通过，定义了对象可读取、hash 校验、失败不发布和重试恢复。

## P1 架构

```text
Scrapy response
        |
        v
Content pipeline
  - canonical URL / url_hash
  - content hash
  - gzip compression
  - object storage key
        |
        v
Oracle Cloud Object Storage
        |
        v
Kafka publisher
  - crawl_attempt
```

## 实施策略

1. 固化消息契约：`crawl_attempt`。
2. 在 Scrapy item pipeline 中生成 `attempt_id`、canonical URL、`url_hash`，并按分支生成 fetch/content/storage 三类结果。
3. 对 200 HTML 响应生成 `snapshot_id`、内容 hash 和对象存储 key。
4. 实现对象存储客户端抽象，使用 OCI SDK 接入 Oracle Cloud Object Storage，并提供 fake client 测试。
5. 实现 Kafka publisher 抽象和可靠 producer 配置。
6. 增加指标和日志：上传成功/失败、发布成功/失败、消息延迟。
7. 增加端到端 smoke test：抓取受控 HTML，验证对象存储内容和 Kafka `crawl_attempt` 消息一致。

## P1 运行参数

| 参数 | 暂定值 | 说明 |
|------|--------|------|
| `OBJECT_STORAGE_PROVIDER` | `oci` | P1 默认 OCI |
| `OCI_OBJECT_STORAGE_BUCKET` | `clawer_content_staging` | 用户确认的 bucket |
| `OCI_OBJECT_STORAGE_NAMESPACE` | `axfwvgxlpupm` | OCI namespace |
| `OCI_OBJECT_STORAGE_REGION` | `us-phoenix-1` | OCI region |
| `OCI_OBJECT_STORAGE_ENDPOINT` | `https://objectstorage.us-phoenix-1.oraclecloud.com` | OCI Object Storage endpoint |
| `OCI_AUTH_MODE` | `api_key` 或 `instance_principal` | 开发用 API Key，生产用 Instance Principal |
| `OCI_CONFIG_FILE` | `~/.oci/config` | 允许使用 OCI SDK 配置文件 |
| `OCI_PROFILE` | `DEFAULT` | OCI SDK 配置 profile |
| `CONTENT_COMPRESSION` | `gzip` | 用户确认 |
| `KAFKA_BOOTSTRAP_SERVERS` | `bootstrap-clstr-hcpqnx0ycdc2ds5o.kafka.us-phoenix-1.oci.oraclecloud.com:9092` | Kafka broker |
| `KAFKA_SECURITY_PROTOCOL` | `SASL_SSL` | Kafka 安全协议 |
| `KAFKA_SASL_MECHANISM` | `SCRAM-SHA-512` | Kafka SASL 机制 |
| `KAFKA_USERNAME` | 环境变量注入 | 不提交真实值 |
| `KAFKA_PASSWORD` | 环境变量注入 | 不提交真实值 |
| `KAFKA_SSL_CA_LOCATION` | `/etc/pki/tls/certs/ca-bundle.crt` | CA 路径 |
| `KAFKA_BATCH_SIZE` | `100` | 用户提供配置 |
| `KAFKA_TOPIC_CRAWL_ATTEMPT` | `crawler.crawl-attempt.v1` | P1 调整后目标 topic |
| `KAFKA_TOPIC_PAGE_METADATA` | `crawler.page-metadata.v1` | P1 第一版已验证 topic，保留为兼容参考 |
| `KAFKA_FLUSH_TIMEOUT_MS` | `130000` | Kafka producer 单次 publish flush 上限；失败验证脚本会临时缩短 |

## 项目结构

### 文档

```text
specs/002-p1-content-persistence/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
└── tasks.md
```

### 源码预期

```text
src/crawler/crawler/
├── pipelines.py
├── storage.py
├── publisher.py
├── schemas.py
└── contracts/
tests/
├── unit/
└── integration/
deploy/
├── examples/
└── scripts/
```

**结构决策**：P1 继续在现有 Scrapy 项目内增量扩展，避免在网络出口链路尚未进入 K8s 前拆成多个服务。对象存储和 Kafka 通过接口隔离，方便后续替换实现或迁移到独立 worker。

## 复杂度跟踪

| 例外项 | 必要原因 | 未采纳更简单方案的原因 |
|--------|----------|------------------------------|
| 消息 schema 版本化 | 支持下游消费者兼容演进 | 无版本字段会让后续 schema 调整风险过高 |
| 对象存储客户端抽象 | 需要通过 `OCI_AUTH_MODE` 支持 API Key 与 Instance Principal 双模式 | 直接在业务 pipeline 中写认证分支会污染业务逻辑并降低可测试性 |

## P1 调整计划：从 page-metadata 到 crawl_attempt

P1 第一版已验证 `page-metadata` producer。按最新结论，P1 需要调整为单一 `crawl_attempt` producer：

```text
fetch_result + content_result + storage_result -> crawl_attempt
```

消费端基于 `crawl_attempt` 投影：

| 投影表 | 写入条件 |
|--------|----------|
| `crawl_logs` | 每个 `attempt_id` 总是写入 |
| `page_snapshots` | 仅当 `storage_result=stored` 且 `snapshot_id/storage_key` 存在 |
| `pages_latest` | 仅从成功 `page_snapshots` 更新 |

### 待调整实现点

1. 新增 `attempt_id` 生成逻辑。
2. 将 payload builder 从 `page-metadata` 扩展为 `crawl_attempt`。
3. 非 HTML、非 200、fetch failure、storage failure 均发布 `crawl_attempt`，但不写对象存储快照。
4. storage success 时发布 `storage_result=stored`，并携带 `snapshot_id/storage_key/content_sha256`。
5. Kafka topic 默认改为 `crawler.crawl-attempt.v1`。
6. 更新验证脚本，验证成功 HTML、非 HTML、storage failure、Kafka failure 四类分支。
