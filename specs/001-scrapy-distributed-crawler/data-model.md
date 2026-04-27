# 数据模型：Scrapy 分布式爬虫

## 实体

### URL 任务（URL Task）

- `url`
- `dedupe_key`
- `host`
- `priority`
- `depth`
- `source`
- `retry_count`
- `created_at`

说明：

- 站外链接可以被发现并记录，但不进入待抓取队列。
- `dedupe_key` 基于 canonical URL 计算。
- canonicalization 忽略 fragment、query 参数顺序、Host 大小写、默认端口和尾斜杠等差异。
- 具体契约见 `contracts/canonical-url.md`。

### 页面快照（Page Snapshot）

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

说明：

- `url_hash` 基于 canonical URL 计算，与 URL 任务的 `dedupe_key` 语义保持一致。
- 支持定期重爬。
- 页面存储只保留最新快照，不保留多版本历史。

### 抓取事件（Crawl Event）

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

### IP 健康状态（IP Health State）

- `host`
- `egress_ip`
- `status`
- `failure_count`
- `last_failure_at`
- `cooldown_until`
- `reason`

## 后置建模问题

- 页面元数据、抓取日志和分析事件的保留周期暂后置设计。
- 下游解析服务暂不纳入当前阶段，因此解析任务身份后置设计。
