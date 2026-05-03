# 交付变更记录：crawler-executor

**更新日期**：2026-05-03
**文档层级**：现状层 / 交付记录
**排序规则**：倒序记录已合并或已完成验证的 spec 与架构决策。

## 2026-05-03

### P3 / 004：恢复 staging 验证与关闭收口

- **关联 spec**：`specs/004-p3-k8s-daemonset-hostnetwork/`
- **恢复结论**：005 已补齐 004 暂停时发现的生产功能性缺口，004 从“已暂停”恢复为 staging 验证中。
- **已复用证据**：staging OKE 已验证 DaemonSet `hostNetwork=true`、`ClusterFirstWithHostNet`、`RollingUpdate maxUnavailable=1`、2 node / 2 pod、`enp0s5` IP 池 `5-5`、health/readiness、Kafka producer smoke 和 Redis PEL 清空。
- **验证中发现并修复**：T037 staging smoke 暴露 `FETCH_QUEUE_CLAIM_MIN_IDLE_MS=60000` 会在 005 delayed buffer / 下载 / Kafka 发布窗口内过早 `XAUTOCLAIM` active PEL，已将 production / staging 默认值提升为 `600000ms`；同时修复 `FetchQueueSpider.start()` 在 async loop 中同步执行 Redis 阻塞读导致 Scrapy downloader 被饿住的问题，改为线程 offload。
- **关闭前剩余项**：仍需补干净 Fetch Command 消费后 `crawl_attempt` 发布并 `XACK`、Object Storage 内容持久化、debug stream 定向路由、pause flag、手动删除 / RollingUpdate 下 PEL reclaim，以及依赖异常不触发 liveness 雪崩的明确记录。

### M3a / 005：staging 等价镜像环境验证通过

- **关联 spec**：`specs/005-m3a-adaptive-politeness-egress-concurrency/`
- **关闭结论**：若以 staging 等价镜像环境为功能验收口径，spec005 已完成；production 复刻验证进入后续发布流程。
- **K8s 验证**：staging OKE `crawler-executor` namespace 中 2 个 `scrapy-egress=true` node 通过 DaemonSet 审计；`hostNetwork=true`、`ClusterFirstWithHostNet`、`RollingUpdate maxUnavailable=1`、health/readiness、每 node 单 Pod 均通过。
- **IP 池验证**：`enp0s5` 发现 5 个 IPv4，覆盖 1 个 primary + 4 个 secondary；`M3_IP_POOL_EXPECTED_RANGE=5-5` 通过。
- **M3a 功能验证**：config、sticky-pool、pacer、soft-ban feedback、delayed buffer、Redis boundary 脚本均通过；真实运行指标观察到 sticky-pool assignment、egress identity selection、pacer delay 和多出口 IP 的 204 请求。
- **Kafka / PEL 验证**：修正 `subnetApp` ingress 使 nodepool `10.0.12.0/22` 可访问 Kafka broker `9092`；修正容器 CA 路径为 `/etc/ssl/certs/ca-certificates.crt`；最小 Kafka producer smoke 返回 `remaining=0 results=['ok']`；测试 PEL 最终清空。
- **后续**：production 需按 staging 同一流程复刻验证；Object Storage 权限和长期运行看板仍需按生产发布流程补做。

### ADR-0013：K8s DaemonSet 使用 RollingUpdate

- **关联 ADR**：`state/decisions/0013-k8s-daemonset-uses-rolling-update.md`
- **新增决策**：M3 / M3a DaemonSet 从 `OnDelete` 切换为 `RollingUpdate maxUnavailable=1`，通过 `kubectl rollout status` 统一 staging / production 更新观察流程。
- **替代关系**：ADR-0011 标记为被 ADR-0013 替代；PEL 可恢复、`crawl_attempt` 发布成功后 ack、Kafka failure 不 ack 语义继续沿用。

## 2026-05-01

### M3a / 005：自适应 Politeness 与出口并发控制本地收口

- **关联 spec**：`specs/005-m3a-adaptive-politeness-egress-concurrency/`
- **新增能力**：实现 `egress_identity`、host-aware sticky-pool、per-(host, egress_identity) pacer、本地 delayed buffer、response / exception feedback signal、Redis TTL 执行安全状态、soft-ban feedback controller 和 005 指标。
- **生产路径**：`FetchQueueSpider` 的 `STICKY_POOL` 路径会写入 `egress_identity` / `egress_identity_hash` / `egress_identity_type` / `download_slot`，并读取 Redis 中的 `(host, ip)` backoff、IP cooldown 和 host slowdown 影响后续选择。
- **验证脚本**：新增并本地通过 `run-m3a-config-audit.sh`、`run-m3a-sticky-pool-validation.sh`、`run-m3a-pacer-validation.sh`、`run-m3a-soft-ban-feedback-validation.sh`、`run-m3a-delayed-buffer-validation.sh`、`run-m3a-redis-boundary-validation.sh`。
- **测试结果**：本地执行 005 相关单元 / 集成测试通过，59 passed。
- **004 恢复准备**：production profile、K8s base ConfigMap / DaemonSet env 和 004 ConfigMap 契约已切换到 005 生产参数；下一步仍需目标节点 smoke 后恢复 004 dry-run 与集群验证。

## 2026-04-30

### M3a / 005：自适应 Politeness 与出口并发控制规格启动

- **关联 spec**：`specs/005-m3a-adaptive-politeness-egress-concurrency/`
- **新增内容**：创建 005 规格、实施计划、研究记录、数据模型、运行参数契约、Redis 执行态契约、指标契约、quickstart 和任务清单。
- **目标范围**：补齐 host-aware sticky-pool、per-(host, ip) downloader slot、pacer、IP cooldown、host slowdown、soft-ban feedback、本地 delayed buffer 和 Redis 写入边界。
- **状态**：草案已创建，等待进入实现；004 继续暂停，待 005 验证通过后恢复 K8s 部署验证。

### ADR-0012：自适应 Politeness 与出口并发控制边界

- **关联 ADR**：`state/decisions/0012-adaptive-politeness-and-egress-concurrency.md`
- **新增决策**：production / staging 方向从静态 per-host rate cap / `STICKY_BY_HOST = host -> 1 IP` 调整为自适应防封闭环；P0 / 显式回退验证可保留历史策略，production / staging 默认采用 host-aware sticky-pool。
- **边界澄清**：crawler-executor 仍不得写 URL 队列、优先级、去重或长期 Host / IP / ASN 画像事实；允许写入 TTL、命名空间隔离的短窗口执行安全状态，如 `(host, ip)` backoff、IP cooldown、host slowdown 和可选 `(host, asn/cidr)` soft limit。
- **后续影响**：004 继续暂停；005 已创建用于补齐 sticky-pool、per-(host, ip) downloader slot、软封禁反馈、本地有界延迟和相关指标，005 验证通过后再恢复 K8s 部署验证。

### P3 / 004：K8s DaemonSet + hostNetwork 生产部署基础暂停并记录现场

- **关联 spec**：`specs/004-p3-k8s-daemonset-hostnetwork/`
- **新增能力**：建立 M3 规格草案与部署基础模板，明确专用 crawler node pool、DaemonSet、`hostNetwork: true`、每 node 单 pod、Redis Streams 常驻消费、node / pod 精准调试、Secret / ConfigMap 分层、health probe、pause flag 和目标集群审计脚本。
- **关键决策**：关停语义选择 B（低频手动滚动、任务幂等、允许少量重复抓取、未完成 in-flight 留 PEL 后续 reclaim）；liveness 只检查进程 / reactor / metrics endpoint 基本存活，外部依赖短暂故障进入指标和告警；debug stream 的 `crawl_attempt` 仍进入正式 topic，但必须携带 `tier=debug` 供第五类过滤或标记。
- **目标集群现场**：已确认 OKE node pool `scrapy-node-pool`、subnet `subnetCollection`、2 个 node 均带 `scrapy-egress=true`；host interface 为 `enp0s5`，每 node 约 65 个 IPv4；Redis endpoint `aaajqtckmia7tfijfk75vfiz4rw4goapkg3geaw2tmaaog4ogcwh6ta-p.redis.us-phoenix-1.oci.oraclecloud.com:7379` TCP 连通；namespace `crawler-executor` 已创建；`crawler-executor-redis` 和 `crawler-executor-kafka` Secret key 均存在。
- **暂停原因**：生产部署前发现功能性遗漏。团队决定暂停 004，不继续 apply ConfigMap / DaemonSet，也不进入生产流量验证；后续先制定新 spec 补齐功能缺口。
- **当时状态**：004 在 2026-04-30 暂停。该状态已于 2026-05-03 被上方“恢复 staging 验证与关闭收口”记录替代；剩余验证项继续按 004 tasks 跟进。

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
