# ADR-0005: 不使用 scrapy-redis 默认 scheduler / dupefilter

**状态**：已接受
**日期**：2026-04-29

## 背景

scrapy-redis 的默认 scheduler / dupefilter 适合将 Scrapy 的调度队列和去重状态外置到 Redis。但 crawler-executor 的架构边界要求：Redis 队列写入、URL 去重、优先级和重抓决策归第六类，本系统只读消费抓取指令。

如果直接接入 scrapy-redis 默认 scheduler，容易把 URL 队列维护、dupefilter 状态和 outlinks enqueue 能力带回执行层。

## 决策

003 不使用 scrapy-redis 默认 scheduler / dupefilter。

crawler-executor 将实现面向 Redis Streams consumer group 的轻量队列 consumer，并由 Scrapy spider 的启动入口消费 Fetch Command、构造 Scrapy request。

允许使用 Scrapy 自身能力：

- downloader middleware
- spider callback / errback
- pipeline
- settings
- stats / extensions

不引入 scrapy-redis 作为 003 运行时依赖。

## 备选方案

- 直接使用 scrapy-redis 默认 scheduler：不采纳。它可能写 Redis scheduler / dupefilter 状态，难以证明只读边界。
- 裁剪 scrapy-redis：暂不采纳。裁剪成本和行为审计成本高于直接实现轻量 Streams consumer。
- 继续用本地 seed 文件：不采纳。不能满足 M2 多 worker 队列消费目标。

## 后果

- 好处：执行层只读消费边界更容易验证。
- 好处：避免把 URL 去重、outlinks 回灌和调度状态引入 crawler-executor。
- 好处：队列消息到 request meta 的映射可控。
- 代价：需要维护少量 Redis Streams consumer 代码。
- 代价：不能直接获得 scrapy-redis 的成熟 scheduler 功能；但这些功能本就不属于本系统边界。

## 关联

- ADR-0003
- ADR-0004
- `specs/003-p2-readonly-scheduler-queue/`
