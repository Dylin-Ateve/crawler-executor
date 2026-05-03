# 架构决策记录（ADR）

本目录记录会影响多个 feature、跨阶段持续生效、或会改变系统边界的架构决策。

## 编号规则

- 文件名格式：`NNNN-kebab-case-title.md`
- 编号递增，不复用。
- 旧决策被替代时，不删除原 ADR；将“状态”改为“被 NNNN 替代”。

## 状态

- `已提议`：已提出，尚未作为约束生效。
- `已接受`：已采纳，后续 spec 和 plan 必须遵守。
- `被 NNNN 替代`：已被后续 ADR 替代。

## 模板

```markdown
# ADR-NNNN: 标题

**状态**：已提议 / 已接受 / 被 NNNN 替代
**日期**：YYYY-MM-DD

## 背景

为什么需要做这个决策。包括背景、约束、已知问题和触发场景。

## 决策

明确写出被采纳的决策。

## 备选方案

- 方案 A：不采纳原因。
- 方案 B：不采纳原因。

## 后果

- 好处。
- 代价。
- 后续需要关注的事项。

## 关联

- 关联 spec。
- 关联 ADR。
- 关联上层架构章节或契约。
```

## 索引

| ADR | 标题 | 状态 | 日期 |
|---|---|---|---|
| [0001](0001-scrapy-over-heritrix.md) | 放弃 Heritrix，从 Scrapy 起步独立演进 | 已接受 | 2026-04-29 |
| [0002](0002-event-model-single-crawl-attempt.md) | 事件模型收敛为单一 `crawl_attempt` | 已接受 | 2026-04-29 |
| [0003](0003-redis-write-side-belongs-to-scheduler.md) | Redis 队列写入侧归第六类，本系统只读消费 | 已接受 | 2026-04-29 |
| [0004](0004-use-redis-streams-consumer-group-for-fetch-queue.md) | 使用 Redis Streams consumer group 承载抓取指令队列 | 已接受 | 2026-04-29 |
| [0005](0005-do-not-use-scrapy-redis-scheduler.md) | 不使用 scrapy-redis 默认 scheduler / dupefilter | 已接受 | 2026-04-29 |
| [0006](0006-ack-fetch-command-after-crawl-attempt-published.md) | `crawl_attempt` 发布成功后再确认抓取指令 | 已接受 | 2026-04-29 |
| [0007](0007-fetch-command-identity-and-invalid-message-handling.md) | 抓取指令标识与无效消息处理 | 已接受 | 2026-04-29 |
| [0008](0008-kafka-publish-failure-not-in-max-deliveries-terminal-semantics.md) | Kafka 发布失败不进入最大投递次数终态语义 | 已接受 | 2026-04-29 |
| [0009](0009-graceful-shutdown-and-pel-handover.md) | 优雅停机与 PEL 移交语义 | 已接受 | 2026-04-30 |
| [0010](0010-system-group-class-2-positioning.md) | crawler-executor 锁定为系统群第二类的纯粹实现 | 已接受 | 2026-04-29 |
| [0011](0011-k8s-rollout-uses-pel-recovery-shutdown-posture.md) | K8s 低频滚动采用 PEL 可恢复的关停姿态 | 被 0013 替代 | 2026-04-30 |
| [0012](0012-adaptive-politeness-and-egress-concurrency.md) | 自适应 Politeness 与出口并发控制边界 | 已接受 | 2026-04-30 |
| [0013](0013-k8s-daemonset-uses-rolling-update.md) | K8s DaemonSet 使用 RollingUpdate | 已接受 | 2026-05-01 |
| [0014](0014-control-plane-policy-scope-and-streams-boundary.md) | 控制平面策略作用域与 Redis Streams 边界 | 已接受 | 2026-05-03 |

## 待回补 ADR 候选

以下决策已在规格或现状文档中出现，但本轮暂不一次性补齐，后续相关 feature 启动时回补：

- 关闭 Scrapy follow，链接抽取归上游。
- 取消 parse-tasks 派发模式，第三类自订阅。
- 对象存储采用 OCI SDK，禁用 S3-compatible。
- OCI 双认证模式业务无感。
- `content_sha256 = SHA-256 on uncompressed HTML body`。
- 每次抓取保留独立快照，不按 `url_hash` 覆盖。
- URL 归一化库 Python 实现先由本系统持有。
- gzip 不通过 HTTP `Content-Encoding` 表达。
