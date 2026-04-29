# 功能规格：P1 抓取内容可靠持久化与 crawl_attempt 投递

**功能分支**：`002-p1-content-persistence`
**创建日期**：2026-04-27
**状态**：P1 已通过目标节点 T055 验证
**输入来源**：`.specify/memory/product.md`、`.specify/memory/architecture.md`、`specs/001-scrapy-distributed-crawler/p0-validation-report.md`

## 背景

P0 已验证 Scrapy worker 可以在真实 Linux 节点上通过本地辅助 IP 出口抓取，并能通过 Valkey 维护 Host/IP 黑名单 TTL。P1 进入 producer 链路：一次 URL 抓取 attempt 完成后，向 Kafka 发布可重放、可幂等消费的 `crawl_attempt` 事件；如果该 attempt 成功产出 HTML 正文，则先将正文写入对象存储，再在同一事件中携带快照字段。

P1 不再验证多出口 IP 基础通路；该能力作为已存在的 worker 能力复用。P1 只交付 Scrapy worker 到对象存储和 Kafka 的 producer 链路与契约，不包含 PostgreSQL、ClickHouse 消费者，也不设计下游解析服务。

说明：P1 第一版已经验证 `page-metadata` producer。基于后续设计讨论，P1 已调整为单一 `crawl_attempt` 事件；`crawl_logs`、`page_snapshots` 和 `pages_latest` 作为消费端数据库投影，不作为 producer 侧多个并列事件。

## 用户场景与测试

### 用户故事 1 - 记录一次完整抓取 attempt（优先级：P1）

作为数据平台负责人，我需要每一次 URL 抓取尝试都能形成一条完整的 `crawl_attempt` 事件，记录 fetch、content 和 storage 三个阶段的结果，供下游保存抓取记录与页面快照。

**优先级理由**：这是 P1 的核心可靠性门槛，直接决定抓取过程是否可追溯，以及成功页面是否可恢复、可重放。

**独立测试**：抓取一个受控 HTML URL，验证对象存储中存在压缩内容对象，并且 Kafka `crawl_attempt` 消息中的 `fetch_result`、`content_result`、`storage_result`、`storage_key`、`storage_etag`、`content_sha256` 与对象内容一致。

**验收场景**：

1. **假设** worker 成功收到 HTTP 200 HTML 响应，**当** pipeline 处理该响应，**则** 先写入 Oracle Cloud Object Storage，再发布 `crawl_attempt` Kafka 消息，且 `storage_result=stored`。
2. **假设** 对象存储上传失败，**当** pipeline 处理响应，**则** 发布 `crawl_attempt` Kafka 消息，且 `storage_result=failed`、快照字段为空，并记录结构化错误日志和指标供排查。
3. **假设** 响应不是可保存 HTML 快照，**当** pipeline 处理响应，**则** 发布 `crawl_attempt` Kafka 消息，且 `content_result=non_snapshot`、`storage_result=skipped`。
4. **假设** Kafka 发布失败，**当** attempt 已完成，**则** worker 按 producer retry 策略重试，并记录结构化错误和指标；P1 不维护本地 outbox。

### 用户故事 2 - 保持消费端幂等契约（优先级：P1）

作为下游消费者开发者，我需要 Kafka 消息中包含稳定的 attempt 级业务键，以便 PostgreSQL 或后续消费者按 at-least-once 语义幂等写入一次抓取意图。

**优先级理由**：P1 已确认 Kafka 接受 at-least-once 投递，若消息缺少幂等键，重放会产生重复或覆盖错误。

**独立测试**：重复发布同一个 canonical URL 的多次抓取消息，验证 `url_hash` 表示同一个逻辑页面，而每次新的抓取意图都有不同 `attempt_id`；同一 `attempt_id` 被 Kafka 重试或重复投递时，消费端可用 `attempt_id` 幂等去重。

**验收场景**：

1. **假设** 同一个 canonical URL 被两次独立抓取，**当** 发布两条 `crawl_attempt`，**则** 两条消息的 `url_hash` 相同，但 `attempt_id` 不同。
2. **假设** Scrapy 对同一次抓取意图执行内部 retry，**当** 最终发布 `crawl_attempt`，**则** retry 过程归属于同一个 `attempt_id`，不生成新的 attempt。
3. **假设** Kafka producer 发生重试，**当** 同一消息被重复投递，**则** 消费端可以用 `attempt_id` 去重；成功快照投影可以用 `snapshot_id` 去重。

## 边界场景

- HTTP 响应成功，但对象存储上传失败。
- 对象存储上传成功，但 Kafka 发布失败。
- Kafka 发布结果未知，producer 重试导致重复消息。
- Scrapy 内部 retry 属于同一个 `attempt_id`，最终发布一条 `crawl_attempt`。
- Kafka 持续不可用时，P1 不提供本地 outbox；attempt 事件未发布的补偿依赖后续重抓或 P2 reconciliation。
- 当前不发布独立 `crawl-events` topic；P1 使用 `crawl_attempt` 作为唯一 producer 事件。
- 同一个 URL 定期重爬，页面存储只保留最新快照。
- 页面内容很大，需要压缩、限制单对象大小并记录实际字节数。
- 响应不是 HTML，例如 PDF、图片、字体、JavaScript、CSS 或二进制内容。
- 页面发现站外链接，站外链接只记录不入抓取队列。
- canonical URL 规则后续被其他系统依赖，P1 必须复用 `contracts/canonical_url.py`。
- OCI Object Storage 使用双认证模式：开发环境 API Key，生产环境 Instance Principal；业务代码必须完全无感。

## 需求

### 功能需求

- **FR-001**：P1 必须发布单一 `crawl_attempt` Kafka 消息，描述一次 URL 抓取 attempt 的 fetch、content 和 storage 阶段结果。
- **FR-002**：对象存储 bucket 使用 `clawer_content_staging`，namespace 使用 `axfwvgxlpupm`，region 使用 `us-phoenix-1`，endpoint 使用 `https://objectstorage.us-phoenix-1.oraclecloud.com`。
- **FR-002a**：对象存储接入必须使用 OCI SDK，不使用 S3-compatible 客户端作为 P1 实现路径。
- **FR-002b**：对象存储认证必须支持 `OCI_AUTH_MODE` 双模式切换：开发使用 `api_key`，生产使用 `instance_principal`；pipeline 业务代码只依赖统一 storage client，不感知认证模式。
- **FR-003**：写入对象存储的内容必须压缩，并记录压缩前后字节数。
- **FR-004**：对象存储 key 必须可由 `url_hash`、抓取日期和 `snapshot_id` 定位，避免单目录过热。
- **FR-005**：P1 必须基于 canonical URL 计算 `url_hash`，并复用 P0 已抽象的 canonical URL 契约。
- **FR-006**：P1 必须发布 `crawl_attempt` Kafka 消息，包含 `attempt_id`、`url_hash`、canonical URL、原始 URL、状态、content metadata、storage metadata、outlinks 统计和抓取时间。
- **FR-007**：P1 不发布独立 `crawl-events` Kafka 消息；抓取行为、内容分类和存储结果统一进入 `crawl_attempt`。
- **FR-008**：Kafka 投递语义为 at-least-once；消息必须包含幂等键，供消费者去重或 upsert。
- **FR-008a**：`attempt_id` 表示一次抓取意图，不表示 canonical URL。相同 `url_hash` 可以对应多个不同 `attempt_id`。
- **FR-008b**：Scrapy 内部 retry 必须归属于同一个 `attempt_id`；Kafka 消费端按 `attempt_id` 对同一次 attempt 的重复消息去重。
- **FR-009**：对象存储上传失败时仍必须发布 `crawl_attempt`，但 `storage_result` 必须为 `failed`，且不得携带可用 `snapshot_id/storage_key` 快照语义。
- **FR-010**：Kafka 发布失败时，worker 必须记录结构化错误和指标；P1 不实现本地 outbox，不承诺进程退出后的本地持久补偿。
- **FR-011**：站外链接允许发现并记录在 metadata 中，但不得加入抓取队列。
- **FR-012**：P1 暂不实现下游解析服务和 `parse-tasks` topic。
- **FR-013**：页面存储策略为保留最新快照；旧快照清理策略暂不在 P1 强制实现。
- **FR-014**：P1 必须提供本地或测试环境下的端到端验证命令。
- **FR-015**：P1 只存储 HTML 或 text/html 类响应；字体、JavaScript、CSS、图片、PDF 和其他资源文件不写入对象存储，但仍应发布 `crawl_attempt` 并标记 `storage_result=skipped`。
- **FR-016**：P1 的 `crawl_attempt` 只记录 outlink 数量和站外 outlink 数量；完整 outlink 列表后置到 P2。
- **FR-017**：P1 不主动删除旧对象；对象存储历史对象清理交由 P2。
- **FR-018**：`crawl_logs`、`page_snapshots`、`pages_latest` 是消费端数据库投影，不作为 producer 侧多个并列事件发布。

### 非功能需求

- **NFR-001**：P1 不得降低 P0 已验证的出口 IP 选择和健康检查能力。
- **NFR-002**：对象存储上传和 Kafka 发布必须有结构化日志和 Prometheus 指标。
- **NFR-003**：Kafka producer 必须启用可靠发布配置，至少包含 ack、重试、超时和幂等相关参数的显式配置。
- **NFR-004**：消息 schema 必须版本化，消费者可通过 `schema_version` 识别兼容性。
- **NFR-005**：敏感配置通过环境变量或 secret 注入，文档不得提交真实凭据。

### 关键实体

- **Page Content Object**：对象存储中的 gzip 压缩 HTML 内容，包含 storage key、etag、content sha256、压缩算法和字节数。
- **Crawl Attempt Event**：一次 URL 抓取尝试的完整事件，包含 fetch、content 和 storage 三类正交结果。
- **Page Snapshot Metadata**：从 `crawl_attempt` 投影出的页面快照元数据，只在 `storage_result=stored` 时成立。
- **Outlink Record**：页面中发现的链接，区分站内和站外，站外仅记录。

## 成功标准

- **SC-001**：抓取一个受控 HTML 页面后，能在对象存储读取到压缩内容，并能根据 Kafka `crawl_attempt` 校验内容 hash。
- **SC-002**：对象存储上传失败时，`crawl_attempt` 仍会被发布，且 `storage_result=failed`，消费端不会投影出 `page_snapshots`。
- **SC-003**：Kafka 短暂不可用时，worker 记录发布失败日志和指标；不要求本地 outbox 恢复发布。
- **SC-004**：重复投递同一消息时，消费者可以基于幂等键去重。
- **SC-005**：站外链接被记录，但不会进入待抓取队列。
- **SC-006**：非 HTML 资源不会写入对象存储，但会发布 `crawl_attempt`，且 `content_result=non_snapshot`、`storage_result=skipped`。

## 假设

- P1 继续复用 P0 Scrapy worker 和 IP middleware。
- 对象存储使用 Oracle Cloud Object Storage，bucket 名称为 `clawer_content_staging`。
- OCI Object Storage namespace 为 `axfwvgxlpupm`，region 为 `us-phoenix-1`。
- OCI Object Storage endpoint 为 `https://objectstorage.us-phoenix-1.oraclecloud.com`。
- OCI Object Storage 认证通过 `OCI_AUTH_MODE` 切换：`api_key` 使用 OCI SDK 配置文件，`instance_principal` 使用实例主体；业务代码必须完全无感。
- 对象存储接入方式使用 OCI SDK。
- Kafka 使用真实集群，broker 为 `bootstrap-clstr-hcpqnx0ycdc2ds5o.kafka.us-phoenix-1.oci.oraclecloud.com:9092`。
- Kafka security protocol 为 `SASL_SSL`，SASL 机制为 `SCRAM-SHA-512`，CA 路径为 `/etc/pki/tls/certs/ca-bundle.crt`，用户名和密码通过环境变量注入。
- Kafka topic 允许自动创建，topic 名称使用 P1 默认值。
- PostgreSQL 和 ClickHouse 消费者不纳入 P1。

## 澄清记录

- 2026-04-27：P0 核心出口链路验证完成，P1 从可靠持久化与元数据投递开始。
- 2026-04-27：对象存储 bucket 使用 `clawer_content_staging`。
- 2026-04-27：Kafka 接受 at-least-once 投递语义，消费端必须幂等。
- 2026-04-27：下游解析服务暂不纳入当前阶段。
- 2026-04-27：确认 P1 只做 producer 链路和契约，不包含 PostgreSQL/ClickHouse 消费者。
- 2026-04-27：确认 OCI namespace 为 `axfwvgxlpupm`，region 为 `us-phoenix-1`，允许使用 OCI SDK 配置文件。
- 2026-04-27：确认 Kafka 使用 SASL_SSL + SCRAM-SHA-512，broker 为 OCI Streaming/Kafka endpoint，topic 可自动创建并使用默认名称。
- 2026-04-27：确认 P1 不需要本地 outbox；Kafka 发布失败只记录日志和指标，不做本地持久补偿。
- 2026-04-27：确认 P1 只存储 HTML，使用 gzip，不删除旧对象，完整 outlink 列表后置到 P2。
- 2026-04-27：确认当前不消费 `crawl-events`，P1 不发布抓取事件到 Kafka，只发布已持久化 HTML 的 `page-metadata`。
- 2026-04-28：确认对象存储使用 OCI SDK 接入。
- 2026-04-28：确认 OCI Object Storage endpoint 为 `https://objectstorage.us-phoenix-1.oraclecloud.com`，认证使用 `OCI_AUTH_MODE` 双模式：开发 API Key，生产 Instance Principal。
- 2026-04-29：确认后续阶段事件模型建议收敛为单一 `crawl_attempt` 事件；`crawl_logs`、`page_snapshots`、`pages_latest` 作为消费端数据库投影，不设计为 producer 侧多个并列事件。
- 2026-04-29：确认 002 规格需要按该结论调整计划，P1 调整目标从 `page-metadata` producer 收敛为 `crawl_attempt` producer。
- 2026-04-29：T055 目标节点验证通过，覆盖 Kafka `crawl_attempt` smoke、对象存储 smoke、成功 HTML、非 HTML skipped、对象存储失败和 Kafka 失败记录。
