# 数据模型：P1 抓取内容可靠持久化与 crawl_attempt 投递

## 实体

### Page Content Object

- `storage_provider`
- `bucket`
- `storage_key`
- `storage_etag`
- `content_sha256`
- `compression`
- `uncompressed_size`
- `compressed_size`
- `created_at`

说明：

- 对象内容为 gzip 压缩后的 HTML HTTP response body。
- `content_sha256` 基于未压缩 body 计算，便于校验原始内容。
- `storage_key` 不直接使用原始 URL，避免特殊字符和目录过热。
- P1 不写入字体、JavaScript、CSS、图片、PDF 或其他非 HTML 资源。

### Crawl Attempt Event

- `schema_version`
- `attempt_id`
- `snapshot_id`
- `url_hash`
- `canonical_url`
- `original_url`
- `host`
- `attempted_at`
- `finished_at`
- `fetch_result`
- `status_code`
- `content_type`
- `response_headers`
- `response_time_ms`
- `bytes_downloaded`
- `error_type`
- `error_message`
- `content_result`
- `outlinks_count`
- `outlinks_external_count`
- `storage_result`
- `storage_provider`
- `bucket`
- `storage_key`
- `storage_etag`
- `compression`
- `content_sha256`
- `uncompressed_size`
- `compressed_size`
- `egress_local_ip`
- `observed_egress_ip`

说明：

- `attempt_id` 是 Kafka message key，表示一次抓取意图；Scrapy 内部 retry 归属于同一个 `attempt_id`。
- `url_hash` 基于 canonical URL，复用 P0 canonical URL 契约；同一个 `url_hash` 可以对应多次抓取意图和多个 `attempt_id`。
- `fetch_result`、`content_result`、`storage_result` 是正交字段，避免用单个 `result` 混合 HTTP 抓取、内容分类和 OSS 存储状态。
- `snapshot_id/storage_key/content_sha256` 等快照字段仅在 `storage_result=stored` 时有业务意义。

### Page Snapshot Metadata 投影

- `schema_version`
- `snapshot_id`
- `attempt_id`
- `url_hash`
- `canonical_url`
- `original_url`
- `host`
- `fetched_at`
- `status_code`
- `content_type`
- `response_headers`
- `content_sha256`
- `storage_provider`
- `bucket`
- `storage_key`
- `storage_etag`
- `uncompressed_size`
- `compressed_size`
- `outlinks_count`
- `outlinks_external_count`
- `egress_local_ip`
- `observed_egress_ip`

说明：

- 该实体由消费端从 `crawl_attempt` 投影得到，不作为 producer 侧独立事件发布。
- `snapshot_id` 表示本次抓取快照，采用 `{url_hash}:{fetched_at_ms}`，不使用 UUID。
- 只保留最新快照时，消费者可按 `url_hash` upsert `pages_latest`。

### Outlink Record

- `source_url_hash`
- `source_snapshot_id`
- `link_url`
- `canonical_link_url`
- `link_host`
- `is_external`
- `anchor_text`

说明：

- P1 的 `crawl_attempt` 只包含 `outlinks_count` 和 `outlinks_external_count`。
- 完整 outlink 列表后置到 P2。
- 站外链接只记录，不进入抓取队列。
- 站内链接是否入队仍由后续调度策略决定。

## Key 设计

建议对象存储 key：

```text
pages/v1/{yyyy}/{mm}/{dd}/{host_hash}/{url_hash}/{snapshot_id}.html.gz
```

P1 不删除旧对象。metadata/DB 层后续按 `url_hash` 保留最新快照；Object Storage 旧对象清理由 P2 处理。

Kafka message key：

| topic | key |
|-------|-----|
| `crawler.crawl-attempt.v1` | `attempt_id` |
| `crawler.page-metadata.v1` | `snapshot_id`，P1 第一版已验证 topic，保留为兼容参考 |

P1 调整后不发布独立 `crawl-events`，也不分别发布 `crawl_logs` 和 `page_snapshots` 事件。抓取行为、内容分类和对象存储结果统一进入 `crawl_attempt`。

## 枚举设计

建议枚举：

| 字段 | 建议值 | 说明 |
|------|--------|------|
| `fetch_result` | `succeeded` / `failed` | 只描述 HTTP fetch 行为是否完成。 |
| `content_result` | `html_snapshot_candidate` / `non_snapshot` / `unknown` | 描述响应内容是否符合页面快照条件。 |
| `storage_result` | `stored` / `failed` / `skipped` | 描述 OSS 对象保存结果。 |

说明：

- `attempt_id` 是一次抓取意图的唯一标识，不是 canonical URL 的唯一标识。
- `crawl_logs` 与 `page_snapshots` 都来源于同一条 `crawl_attempt` 事件。
- `crawl_logs` 总是写入；`page_snapshots` 仅在 `storage_result=stored` 且 `snapshot_id/storage_key` 存在时写入。
- `storage_failed` 不应作为 `crawl_logs.result` 这类单字段枚举；它应是 `storage_result=failed`，避免把 fetch 结果、内容分类和存储结果混在一起。

### PostgreSQL 投影

#### crawl_logs

每次 attempt 一行，记录抓取过程与阶段结果：

- `attempt_id`
- `url_hash`
- `canonical_url`
- `original_url`
- `host`
- `attempted_at`
- `finished_at`
- `fetch_result`
- `status_code`
- `content_type`
- `response_time_ms`
- `bytes_downloaded`
- `error_type`
- `error_message`
- `content_result`
- `storage_result`
- `storage_key`
- `snapshot_id`
- `egress_local_ip`
- `observed_egress_ip`

#### page_snapshots

只记录已成功保存正文对象的页面快照：

- `snapshot_id`
- `attempt_id`
- `url_hash`
- `canonical_url`
- `host`
- `fetched_at`
- `status_code`
- `content_type`
- `content_sha256`
- `storage_provider`
- `bucket`
- `storage_key`
- `storage_etag`
- `compression`
- `uncompressed_size`
- `compressed_size`
- `outlinks_count`
- `outlinks_external_count`

#### pages_latest

每个 `url_hash` 一行，指向最新可读取快照：

- `url_hash`
- `canonical_url`
- `latest_snapshot_id`
- `latest_attempt_id`
- `latest_fetched_at`
- `latest_status_code`
- `latest_storage_key`
- `updated_at`

`pages_latest` 只从成功的 `page_snapshots` 更新；失败 attempt、非 HTML attempt 和存储失败 attempt 不覆盖最新可用快照。
