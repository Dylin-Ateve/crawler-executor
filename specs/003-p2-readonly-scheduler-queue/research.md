# 研究：P2 第六类队列只读消费与多 worker 运行形态

## 1. 队列协议选择

### 选项 A：Redis Streams consumer group

优点：

- 原生支持 consumer group、pending、ack 和重取未确认消息。
- 适合多 worker 正常消费和异常恢复。
- 消费状态可观测，便于后续多节点运行。

代价：

- 第六类必须按 Streams 协议写入。
- 需要定义 stream key、group、consumer name、pending reclaim 策略。

当前结论：采纳。003 使用 Redis Streams consumer group。

### 选项 B：Redis List

优点：

- 简单，适合快速 PoC。
- 第六类写入成本低。

代价：

- ack / pending / reclaim 语义弱。
- 多 worker 异常恢复和消息丢失边界需要额外设计。

当前结论：仅适合作为临时验证路径，不建议作为 M2 目标形态。

### 选项 C：scrapy-redis 默认 scheduler

优点：

- 与 Scrapy 集成成熟。
- 能快速获得分布式 scheduler 和 dupefilter 能力。

代价：

- 默认 scheduler / dupefilter 可能写 Redis 状态。
- 容易把 URL 去重、调度状态和链接回灌带回 crawler-executor。

当前结论：不采纳。003 不引入 scrapy-redis 默认 scheduler / dupefilter。

### 选项 D：自定义轻量 Redis / Valkey consumer

优点：

- 可精确控制只读消费边界。
- 便于将队列消息映射为 Scrapy request meta。
- 便于测试和约束“无 URL 队列写入”。

代价：

- 需要维护少量队列消费代码。
- 需要自行处理 ack、pending、重取和指标。

当前结论：采纳。003 实现轻量 Redis Streams consumer。

## 2. 抓取指令消息格式

最小字段：

- `url`

推荐字段：

- `command_id`
- `job_id`
- `canonical_url`
- `trace_id`
- `host_id`
- `site_id`
- `tier`
- `politeness_key`
- `deadline_at`
- `max_retries`

已确认：

- 第六类不提供 `attempt_id`。
- `attempt_id` 由 crawler-executor 基于 `job_id + canonical_url` 确定性生成。
- Fetch Command 必须包含 `url`、`job_id`、`canonical_url`。
- `host_id` / `site_id` 字段应由第六类提供，但当前阶段允许为空，暂不强制必填。
- 无效消息直接丢弃并记录日志 / 指标。
- 003 不规划 DLQ；未来若启用，DLQ 归第六类。

## 3. fetch failed 事件化

P1 T055 覆盖了：

- HTML 成功：`storage_result=stored`
- 非 HTML：`storage_result=skipped`
- 对象存储失败：`storage_result=failed`
- Kafka 失败：对象保留并记录发布失败

尚未覆盖：

- DNS 失败
- TCP 连接拒绝
- 下载超时
- TLS 握手失败

003 需要为 Scrapy request 增加 errback 或等价机制，将连接级失败构造成 item / payload，并发布：

- `fetch_result=failed`
- `content_result=unknown`
- `storage_result=skipped`
- `error_type`
- `error_message`
- `attempt_id`
- canonical URL / `url_hash`

## 4. 只读边界验证

003 的测试需要覆盖：

- 抓取含 outlinks 页面后 Redis 队列无新增 URL。
- executor 不写第六类去重 key。
- 若使用 Redis Streams，只允许 ack / pending / consumer group 相关状态变化。
- 若使用自定义 consumer，代码层面不暴露 enqueue API。

## 5. ack 与失败分支

每条 `XREADGROUP` 拉到的消息最终进入三类结果之一：

1. 成功抓取：发布 `crawl_attempt` 成功后 `XACK`。
2. 可重试失败：不 `XACK`，消息留在 PEL，后续由 `XAUTOCLAIM` 接管。
3. 永久失败：发布终态失败 `crawl_attempt` 后 `XACK`。

可重试失败包括网络抖动、临时 DNS 失败、连接超时、对方 5xx、429、临时限流。永久失败包括 URL 格式非法、不支持 scheme、404 / 410、投递次数超限。

worker 收到 SIGTERM 后停止新的 `XREADGROUP`，不清空 PEL；正在 fetch 的请求完成后，若 `crawl_attempt` 发布成功则 `XACK`，否则交给后续 `XAUTOCLAIM`。

## 6. 初步建议

003 直接实现 Redis Streams consumer group 轻量 consumer。第六类在本阶段可由本地脚本模拟 `XADD`，但生产语义仍归第六类。
