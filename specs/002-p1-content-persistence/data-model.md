# 数据模型：P1 抓取内容可靠持久化与元数据投递

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

### Page Snapshot Metadata

- `schema_version`
- `snapshot_id`
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

- `url_hash` 基于 canonical URL，复用 P0 canonical URL 契约。
- `snapshot_id` 表示本次抓取快照，采用 `{url_hash}:{fetched_at_ms}`，不使用 UUID。
- 只保留最新快照时，消费者可按 `url_hash` upsert。

### Outlink Record

- `source_url_hash`
- `source_snapshot_id`
- `link_url`
- `canonical_link_url`
- `link_host`
- `is_external`
- `anchor_text`

说明：

- P1 的 Kafka metadata 只包含 `outlinks_count` 和 `outlinks_external_count`。
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
| `crawler.page-metadata.v1` | `snapshot_id` |

P1 不发布 `crawl-events`。抓取事件 Kafka 化后置到 P2 或分析链路。
