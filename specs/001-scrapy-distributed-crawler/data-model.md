# Data Model: Scrapy Distributed Crawler

## Entities

### URL Task

- `url`
- `dedupe_key`
- `host`
- `priority`
- `depth`
- `source`
- `retry_count`
- `created_at`

### Page Snapshot

- `url`
- `url_hash`
- `host`
- `fetched_at`
- `status_code`
- `content_type`
- `content_length`
- `storage_key`
- `storage_etag`
- `compressed_size`
- `outlinks_count`
- `egress_ip`

### Crawl Event

- `url_hash`
- `host`
- `attempted_at`
- `egress_ip`
- `response_time_ms`
- `status_code`
- `error_type`
- `retry_count`
- `bytes_downloaded`
- `outlinks_count`

### IP Health State

- `host`
- `egress_ip`
- `status`
- `failure_count`
- `last_failure_at`
- `cooldown_until`
- `reason`

## Open Modeling Questions

- Canonical URL rules for dedupe.
- Page versioning rules for recrawl.
- Retention period for page metadata, crawl logs, and analytic events.
- Whether parse task identity is page snapshot based or URL based.

