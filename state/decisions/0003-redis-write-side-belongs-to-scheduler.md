# ADR-0003: Redis 队列写入侧归第六类，本系统只读消费

**状态**：已接受
**日期**：2026-04-29

## 背景

crawler-executor 的终态边界是“抓取指令进 → 原始字节落盘 + 单一 `crawl_attempt` 事件出”。在多 worker / 多节点运行形态下，本系统需要从统一队列获取抓取指令，但 URL 选择、优先级、重抓窗口、候选 URL 去重和队列写入都属于第六类（调度与决策）。

如果 crawler-executor 直接使用带写入语义的 scheduler / dupefilter 模式，可能会把 URL 回灌、去重状态维护或调度决策重新带回执行层，违反第二类边界。

## 决策

Redis / Valkey 队列写入侧归第六类。crawler-executor 只读消费第六类已经下发的抓取指令。

本系统不得：

- 向 URL 队列写入新任务。
- 将页面 outlinks 回灌队列。
- 维护上游 URL 去重过滤器。
- 根据本地发现内容决定新 URL 是否抓取。
- 在执行层重新解释或重排第六类优先级语义。

003 阶段的具体队列协议与实现形态由后续 ADR 约束：使用 Redis Streams consumer group（ADR-0004），不使用 scrapy-redis 默认 scheduler / dupefilter（ADR-0005），并在 `crawl_attempt` 发布成功后确认抓取指令（ADR-0006）。

允许的 Redis 写入仅限消费确认、消费者心跳、运行态指标或 pending/ack 等队列协议必需状态；这些写入不得表达 URL 选择、去重或优先级决策。

## 备选方案

- 由 crawler-executor 同时负责 Redis 队列写入和消费。不采纳。该方案把调度决策带回执行层，违反第二类边界。
- 使用 Scrapy follow / LinkExtractor 抽取 outlinks 后回灌 Redis。不采纳。链接发现和是否抓取属于第一类 / 第六类职责。
- 完全不用 Redis / Valkey，由本地 seed 文件继续驱动。不采纳。该模式只适合 P0/P1 验证，不能支持多 worker / 多节点运行形态。
- 直接采用带 scheduler / dupefilter 写入语义的默认方案。不采纳。该路径难以证明只读边界，且容易引入执行层不应持有的去重和调度状态。

## 后果

- 好处：第六类与第二类边界清晰，执行层保持“哑”。
- 好处：后续多 worker 运行可以围绕队列消费、ack、pending 和失败事实展开，而不污染调度决策。
- 好处：003 的验收可以明确检查“无 URL 队列写入”和“无 outlinks enqueue”。
- 代价：不能直接使用带调度写入语义的默认 scheduler 形态，003 需要维护轻量队列 consumer。
- 代价：第六类必须按约定提供稳定的抓取指令消息格式和 Redis Streams 队列协议。

## 关联

- `.specify/memory/product.md`
- `.specify/memory/architecture.md`
- `state/roadmap.md`
- `specs/003-p2-readonly-scheduler-queue/`
- ADR-0010
- ADR-0004
- ADR-0005
- ADR-0006
