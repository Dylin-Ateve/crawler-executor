# 交付变更记录：crawler-executor

**更新日期**：2026-04-29
**文档层级**：现状层 / 交付记录
**排序规则**：倒序记录已合并或已完成验证的 spec 与架构决策。

## 2026-04-29

### 文档体系迁移

- **新增能力**：将规格文档拆分为北极星层、现状层、增量层，并新增 ADR 目录。
- **关联文档**：`.specify/memory/product.md`、`.specify/memory/architecture.md`、`state/current.md`、`state/roadmap.md`、`state/decisions/`
- **关联 ADR**：ADR-0010

### 架构边界调整：第二类纯粹化

- **新增能力**：crawler-executor 锁定为系统群第二类，边界收敛为“抓取指令进 → 原始字节落盘 + `crawl_attempt` 事件出”。
- **关键变化**：PostgreSQL / ClickHouse 事实层外迁至第五类；parse-tasks 派发取消；Scrapy follow 关闭；Redis 队列写入侧归第六类。
- **关联 ADR**：ADR-0010

### 事件模型收敛

- **新增能力**：producer 目标从成功页面 metadata 收敛为单一 `crawl_attempt` 事件，承载 fetch / content / storage 三类正交结果。
- **关联 spec**：`specs/002-p1-content-persistence/`
- **关联 ADR**：ADR-0002

### P1：内容可靠持久化与 `crawl_attempt` producer 收口

- **关联 spec**：`specs/002-p1-content-persistence/`
- **新增能力**：目标节点 T055 验证通过，覆盖 Kafka `crawl_attempt` smoke、OCI Object Storage smoke、成功 HTML `storage_result=stored`、非 HTML `storage_result=skipped`、对象存储失败 `storage_result=failed`、Kafka 发布失败记录与对象保留。
- **当前状态**：P1 已收口；下一阶段进入 M2：第六类队列只读消费与多 worker 运行形态。

### P2 / 003：第六类队列只读消费目标节点验证

- **关联 spec**：`specs/003-p2-readonly-scheduler-queue/`
- **新增能力**：目标节点完成 Redis Streams consumer group 验证，覆盖 Step 1 写入测试 Fetch Command、Step 2 单 worker 发布 `crawl_attempt`、Step 3 多 worker 正常 ack 路径、Step 4 只读边界脚本口径、Step 5 无效消息丢弃与记录。
- **失败语义验证**：补充验证 Kafka failure / PEL reclaim 三阶段不变量：Kafka 不可达时不 `XACK`，第二个 worker 通过 `XAUTOCLAIM` 接管且 `times_delivered` 递增，Kafka 恢复后发布 `crawl_attempt` 并 `XACK`。
- **脚本修正**：`run-p2-kafka-failure-pending-validation.sh` 兼容 redis-py `xpending()` 返回 dict / tuple 两种形态。
- **当前状态**：P2 目标节点验证通过；只读边界审计脚本已覆盖 key diff 与目标 stream `XLEN` 前后不变，后续可继续补允许状态变化清单和更宽 audit pattern。

### P2 / 003：第六类队列只读消费规划启动

- **关联 spec**：`specs/003-p2-readonly-scheduler-queue/`
- **新增能力**：建立 003 规划骨架，回补 ADR-0003 至 ADR-0007，明确 Redis Streams consumer group、禁用 scrapy-redis 默认 scheduler / dupefilter、`crawl_attempt` 发布成功后再 `XACK`，以及基于 `job_id + canonical_url` 生成确定性 `attempt_id`。
- **当前状态**：已被同日 P2 目标节点验证记录取代。

## 2026-04-27 至 2026-04-29

### P1：内容可靠持久化与 producer 第一版

- **关联 spec**：`specs/002-p1-content-persistence/`
- **新增能力**：HTML gzip 写入 OCI Object Storage；对象写入后读取和解压校验；Kafka `page-metadata` producer 第一版；对象存储失败时不发布成功 metadata；Kafka 失败时保留对象并记录失败。
- **当前状态**：已被 2026-04-29 的 `crawl_attempt` producer 收口记录取代。

### P0：单节点 Scrapy 多出口 IP PoC

- **关联 spec**：`specs/001-scrapy-distributed-crawler/`
- **新增能力**：Scrapy 项目骨架、IP 发现、Host/IP 粘性选择、Redis/Valkey TTL 黑名单、Prometheus 单 worker 指标、echo endpoint 多出口验证。
- **当前状态**：核心链路已验证；24 小时稳定性和 K8s hostNetwork 后置。
