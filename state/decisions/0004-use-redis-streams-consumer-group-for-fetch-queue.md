# ADR-0004: 使用 Redis Streams consumer group 承载抓取指令队列

**状态**：已接受
**日期**：2026-04-29

## 背景

003 需要把 crawler-executor 的输入侧从本地 seed 文件推进到第六类下发的队列指令。队列协议需要支持多个 worker 并发消费、消费确认、未完成消息恢复和低 CPU 空转等待。

候选方案包括 Redis Streams consumer group、Redis List、scrapy-redis 默认 scheduler，以及自定义队列协议。

## 决策

003 使用 Redis Streams consumer group 作为抓取指令队列协议。

数据流：

```text
第六类调度系统 --XADD--> crawl:tasks
                         |
                         v
crawler-executor worker --XREADGROUP--> 处理抓取
                         |
                         +--> OCI Object Storage
                         +--> Kafka crawl_attempt
                         |
                         v
                      XACK
```

默认流与分组：

- 主任务流：`crawl:tasks`
- consumer group：`crawler-executor`
- consumer name：由 worker 实例标识生成
- DLQ：`crawl:tasks:dlq` 可选，003 不默认启用

worker 空队列等待使用有限阻塞时间，例如 `BLOCK 5000ms`。不得使用永久阻塞，避免 SIGTERM 到来时无法及时退出。

## 备选方案

- Redis List：不采纳为目标形态。List 简单，但 ack、pending、claim 和多 worker 异常恢复语义不足。
- scrapy-redis 默认 scheduler：不采纳。它的核心价值是替换 Scrapy scheduler / dupefilter，容易引入 URL 去重和队列写入语义。
- 本地 seed 文件：不采纳。只适合 P0/P1 验证，不能支撑多 worker 运行形态。

## 后果

- 好处：consumer group 提供 ack、PEL、pending 和 `XAUTOCLAIM` 等多 worker 恢复能力。
- 好处：worker 可以在无消息时低 CPU 等待。
- 好处：队列协议内务写入与 URL 调度写入边界清晰。
- 代价：第六类需要按 Streams 协议 `XADD` 抓取指令。
- 代价：003 需要实现或封装 Streams consumer，而不是直接复用 scrapy-redis scheduler。

## 关联

- ADR-0003
- ADR-0005
- ADR-0006
- `specs/003-p2-readonly-scheduler-queue/`
