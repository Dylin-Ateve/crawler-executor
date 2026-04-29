# 实施计划：P2 第六类队列只读消费与多 worker 运行形态

**分支**：`003-p2-readonly-scheduler-queue`
**日期**：2026-04-29
**规格文档**：`specs/003-p2-readonly-scheduler-queue/spec.md`

## 摘要

003 将 crawler-executor 的输入侧从本地 seed 文件推进到 Redis Streams consumer group 队列消费。系统只读消费第六类 `XADD` 下发的抓取指令，继续复用 P1 对象存储和 `crawl_attempt` producer，并补强连接级 fetch 失败的 attempt 事件化路径。

## 技术上下文

**语言/版本**：Python 3.9+  
**主要依赖**：Scrapy、Redis / Valkey client、Kafka client、OCI SDK、Prometheus client  
**存储**：OCI Object Storage；Redis / Valkey 作为队列载体；Kafka 作为事件总线  
**测试**：pytest、Scrapy 集成测试、Redis / Valkey 本地或目标节点验证脚本  
**目标平台**：Linux 爬虫节点；后续可进入 Kubernetes 节点  
**项目类型**：抓取执行数据管道  
**性能目标**：本阶段先验证多 worker 正确性，不承诺 30-50 pages/sec 稳定吞吐  
**约束**：使用 Redis Streams consumer group；不引入 scrapy-redis 默认 scheduler / dupefilter；只读消费第六类队列；不写 URL 队列；不 enqueue outlinks；不实现第五类事实投影  
**规模/范围**：单节点多 worker 或少量 worker 的队列消费验证

## 门禁检查

| 门禁 | 来源 | 结果 | 说明 |
|---|---|---|---|
| 章程门禁 | `.specify/memory/constitution.md` | 通过 | 规格先行，先定义队列边界、失败语义和验收标准。 |
| 产品门禁 | `.specify/memory/product.md` | 通过 | 仍聚焦第二类执行系统，不进入调度决策和事实层。 |
| 架构门禁 | `.specify/memory/architecture.md` | 通过 | 符合“抓取指令进 → 原始字节落盘 + `crawl_attempt` 事件出”。 |
| 决策门禁 | `state/decisions/` | 通过 | 遵守 ADR-0002、ADR-0003、ADR-0004、ADR-0005、ADR-0006、ADR-0010。 |
| 路线图对齐 | `state/roadmap.md` | 记录 | 对应 M2：第六类队列只读消费接入。 |

## 项目结构

### 文档

```text
specs/003-p2-readonly-scheduler-queue/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── redis-fetch-command.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### 源码

```text
src/crawler/crawler/
├── queues.py              # 队列 consumer 抽象与实现
├── spiders/               # 队列驱动 spider 或入口适配
├── pipelines.py           # 复用 P1 crawl_attempt pipeline
├── attempts.py            # attempt_id 生成或继承规则
├── metrics.py             # 队列消费与 fetch failed 指标
└── settings.py            # 队列相关配置

tests/
├── unit/
└── integration/

deploy/scripts/
```

**结构决策**：不使用 scrapy-redis 默认 scheduler / dupefilter；新增轻量 Redis Streams queue consumer 抽象。

## 复杂度跟踪

| 例外项 | 必要原因 | 未采纳更简单方案的原因 |
|---|---|---|
| 队列 consumer 抽象 | 需要隔离 Redis Streams / List / scrapy-redis 方案差异 | 直接把队列读取写进 spider 会降低可测试性，也难以证明只读边界 |
| fetch failed errback 事件化 | 需要保证取到指令后无论连接是否成功都有 attempt 事实 | 只依赖 Scrapy 日志会让第五类缺失失败事实 |
| Redis 写入边界测试 | ADR-0003 要求证明不写 URL 队列 | 只做人工代码审查不足以防止后续回归 |
| `crawl_attempt` 发布后再 `XACK` | 保证已 ack 指令都有系统群可追溯事实 | request 入队后立即 ack 会造成无 attempt 事实的任务丢失 |
