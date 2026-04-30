# 交付变更记录：crawler-executor

**更新日期**：2026-04-30
**文档层级**：现状层 / 交付记录
**排序规则**：倒序记录已合并或已完成验证的 spec 与架构决策。

## 2026-04-30

### ADR-0012：自适应 Politeness 与出口并发控制边界

- **关联 ADR**：`state/decisions/0012-adaptive-politeness-and-egress-concurrency.md`
- **新增决策**：生产方向从静态 per-host rate cap / `STICKY_BY_HOST = host -> 1 IP` 调整为自适应防封闭环；P0 / staging 可保留历史策略，生产需采用 host-aware sticky-pool。
- **边界澄清**：crawler-executor 仍不得写 URL 队列、优先级、去重或长期 Host / IP / ASN 画像事实；允许写入 TTL、命名空间隔离的短窗口执行安全状态，如 `(host, ip)` backoff、IP cooldown、host slowdown 和可选 `(host, asn/cidr)` soft limit。
- **后续影响**：004 继续暂停；下一步先新建自适应 Politeness 与出口并发控制 spec，补齐 sticky-pool、per-(host, ip) downloader slot、软封禁反馈、本地有界延迟和相关指标后，再恢复 K8s 部署验证。

### P3 / 004：K8s DaemonSet + hostNetwork 生产部署基础暂停并记录现场

- **关联 spec**：`specs/004-p3-k8s-daemonset-hostnetwork/`
- **新增能力**：建立 M3 规格草案与部署基础模板，明确专用 crawler node pool、DaemonSet、`hostNetwork: true`、每 node 单 pod、Redis Streams 常驻消费、node / pod 精准调试、Secret / ConfigMap 分层、health probe、pause flag 和目标集群审计脚本。
- **关键决策**：关停语义选择 B（低频手动滚动、任务幂等、允许少量重复抓取、未完成 in-flight 留 PEL 后续 reclaim）；liveness 只检查进程 / reactor / metrics endpoint 基本存活，外部依赖短暂故障进入指标和告警；debug stream 的 `crawl_attempt` 仍进入正式 topic，但必须携带 `tier=debug` 供第五类过滤或标记。
- **目标集群现场**：已确认 OKE node pool `scrapy-node-pool`、subnet `subnetCollection`、2 个 node 均带 `scrapy-egress=true`；host interface 为 `enp0s5`，每 node 约 65 个 IPv4；Redis endpoint `aaajqtckmia7tfijfk75vfiz4rw4goapkg3geaw2tmaaog4ogcwh6ta-p.redis.us-phoenix-1.oci.oraclecloud.com:7379` TCP 连通；namespace `crawler-executor` 已创建；`crawler-executor-redis` 和 `crawler-executor-kafka` Secret key 均存在。
- **暂停原因**：生产部署前发现功能性遗漏。团队决定暂停 004，不继续 apply ConfigMap / DaemonSet，也不进入生产流量验证；后续先制定新 spec 补齐功能缺口。
- **当前状态**：已暂停。ConfigMap、DaemonSet、Redis PING、Kafka publish smoke、Object Storage 权限、常驻消费、debug、pause 和 PEL reclaim 目标集群验证均待恢复后执行。

### P2 / 003：优雅停机与 PEL 移交语义落地（T015c 收尾）

- **关联 spec**：`specs/003-p2-readonly-scheduler-queue/`
- **新增能力**：
  - 新增 ADR-0009《优雅停机与 PEL 移交语义》，沉淀 SIGTERM / SIGINT 同语义、SIGHUP / SIGQUIT 不纳入、停机期间禁止 `XAUTOCLAIM`、25 秒 drain 缺省时限、不接管 Scrapy 自身关停（共享标志 + spider 消费循环检查）、阻塞读至多等一个 `block_ms`、停机期失败分支沿用 ADR-0006 / ADR-0008。
  - spec 003 增补边界场景、FR-022、SC-008 与 2026-04-30 澄清记录；research §5 增补优雅停机行为表；plan 决策门禁补 ADR-0008/0009 与复杂度跟踪。
  - 实现侧 `RedisStreamsFetchConsumer` 暴露 `request_shutdown()` / `is_shutting_down` / `acked_count`；`FetchQueueSpider` 通过 `spider_closed` / `engine_stopped` 信号触发停机入口与退出总结；`FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS` 暴露到 settings。
  - 单元测试覆盖：consumer 停机后不再调用 `xreadgroup` / `xautoclaim`、`reclaim` 期间进入停机的边界、spider `spider_closed` / `engine_stopped` handler 行为与重复触发幂等、`start()` 在停机态立即退出。
  - 新增 `deploy/scripts/run-p2-graceful-shutdown-validation.sh`，覆盖 SIGTERM、SIGINT 同语义、SIGHUP 不进入优雅停机路径三阶段断言。
- **目标节点验证结果**：`run-p2-graceful-shutdown-validation.sh` Phase 1 失败，SIGTERM 后 worker 退出耗时 68 秒，超过脚本设置的 `FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS=8` + 5 秒容差；PEL `count=1`、`xlen=1`，说明不清空 PEL 与可恢复底线满足。
- **发现问题**：`fetch_queue_shutdown_signal_received` 实际在 `spider_closed` 阶段才记录，晚于 SIGTERM 到达；退出期间同一 `stream_message_id` 出现两次 `fetch_queue_response_observed`，PEL `max_times_delivered=2`，说明退出中的 worker 仍可能继续 `XAUTOCLAIM` / 重复处理。
- **当前状态**：T015c 实现与单元验证完成，但严格 ADR-0009 / FR-022 语义未满足。团队确认当前 K8s 场景为低频手动滚动、任务幂等、允许少量重复抓取，因此当前实现作为过渡策略接受；M3 可先进入规格草案，不进入 manifest 实现。

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
