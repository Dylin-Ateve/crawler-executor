# 演进路线图：crawler-executor

**更新日期**：2026-05-03
**文档层级**：现状层 / 路线图
**组织方式**：按能力里程碑组织，不按固定时间承诺。

## 1. 里程碑

### M0：单节点 Scrapy 多出口 IP PoC

- **目标**：验证 Scrapy worker 能在真实 Linux 节点上通过多个本地辅助 IP 出口抓取，并维护 Host/IP 短窗口冷却。
- **状态**：已验证。
- **对应 spec**：`specs/001-scrapy-distributed-crawler/`
- **验收信号**：echo endpoint 观察到多个出口 EIP；失败 Host/IP 进入 TTL 冷却；Prometheus 指标可观察。

### M1：内容可靠持久化与 `crawl_attempt` 投递

- **目标**：HTML gzip 写入 OCI Object Storage；每次 attempt 发布单一 `crawl_attempt` 事件。
- **状态**：已验证（连接级 fetch 失败事件化待后续补强）。
- **对应 spec**：`specs/002-p1-content-persistence/`
- **依赖 ADR**：ADR-0002。
- **验收信号**：成功 HTML 的对象可读取、gzip 可解压、事件字段与对象一致；非 HTML 跳过与对象存储失败均发布正确状态事件。

### M2：第六类队列只读消费接入

- **目标**：接入 Redis Streams consumer group 队列只读消费形态，不在本系统写入新 URL。
- **状态**：目标节点已验证；优雅停机当前按过渡策略接受，严格 ADR-0009 / FR-022 语义未收口。
- **依赖 ADR**：ADR-0003、ADR-0004、ADR-0005、ADR-0006、ADR-0007、ADR-0008、ADR-0009。
- **对应 spec**：`specs/003-p2-readonly-scheduler-queue/`
- **验收信号**：多个 worker 可通过 `XREADGROUP` 消费第六类 `XADD` 的抓取指令；本系统无 Redis URL 写入行为；同一 `job_id + canonical_url` 重复投递生成相同 `attempt_id`；`crawl_attempt` 发布成功后 `XACK`；Kafka failure 下消息留 PEL 并可由 `XAUTOCLAIM` 接管，Kafka 恢复后发布并 ack。只读边界脚本已覆盖 key diff 与目标 stream `XLEN` 前后不变。SIGTERM / SIGINT 当前可保持 PEL 不清空和可恢复底线，但目标节点验证显示 shutdown flag 触发晚于 SIGTERM 到达，退出期间仍可能 claim / 重复处理；在低频手动滚动、任务幂等、允许少量重复抓取前提下暂时接受。

### M3：生产部署基础

- **目标**：K8s DaemonSet + hostNetwork、健康探针、指标端口、配置注入和节点隔离。
- **状态**：staging 验证通过，production 待复刻。004 已完成部署方案、模板和 staging 集群验证；生产部署前发现的 005 功能性遗漏已在 M3a 中补齐。
- **对应 spec**：`specs/004-p3-k8s-daemonset-hostnetwork/`
- **当前现场**：staging `scrapy-node-pool`、`subnetCollection 10.0.12.0/22`、`scrapy-egress=true`、`enp0s5`、2 个 node、每 node 5 个 IPv4；`crawler-executor` namespace、Redis/Kafka Secret、DaemonSet、ConfigMap、Kafka publish smoke 和 Redis Streams PEL 清空均已验证通过。
- **恢复条件**：staging 已满足，004 可关闭；production 需按 staging 同一流程复刻 Redis PING、Kafka publish smoke、Object Storage 权限、真实 ConfigMap 审核、DaemonSet dry-run / apply 和集群审计。
- **验收信号**：节点扩缩容时 worker 自动跟随；liveness 仅反映进程 / reactor / metrics endpoint 基本存活；Kafka / Redis / OCI 依赖异常通过 Prometheus 指标和告警反映，不因短暂抖动触发探针失败。

### M3a：自适应 Politeness 与出口并发控制

- **目标**：在大出口 IP 池下补齐生产防封与吞吐模型，包括 host-aware sticky-pool、per-(host, ip) downloader slot、IP 级 cooldown、host 级降速、软封禁反馈和有界本地延迟。
- **状态**：本地实现、验证脚本与 staging 目标环境 smoke 均已通过；production 待复刻。
- **依赖 ADR**：ADR-0012。
- **对应 spec**：`specs/005-m3a-adaptive-politeness-egress-concurrency/`
- **验收信号**：同一 host 可在 K 个出口身份间受控轮转；429 / CAPTCHA / challenge / 反爬 200 页能按 `(host, ip)`、`ip`、`host` 维度触发不同退避；本地 delayed buffer 有容量和时间上限，buffer 满时停止 `XREADGROUP`；不会写 URL 队列、优先级或长期画像事实。本地脚本与 staging 真实多出口 IP smoke 已覆盖上述核心口径。

### M4：运行时执行策略与停抓控制

- **目标**：在不改变 executor 只执行抓取指令的边界下，补齐 effective policy 契约、本地文件 / ConfigMap provider、运行时热加载、last-known-good、全局 / 作用域 pause、`deadline_at` 与 `max_retries` 生效、严格优雅停机收口和 M4 指标。
- **状态**：本地实现与验证完成；staging / production 复刻不在本 spec 范围。
- **对应 spec**：`specs/007-m4-runtime-policy-pause-control/`
- **前置校准**：`specs/006-policy-scope-and-document-alignment/` 已通过 ADR-0014 移除旧 Heritrix 分组概念和外置 scheduler 旧目标，并补齐 `crawl_attempt` 执行上下文透传。
- **策略边界**：M4 第一版只消费已经解析好的 effective policy；策略优先级、业务策略合并、Host/Site 成员关系解析、URL 选择、业务优先级和重抓窗口仍归控制平面或第六类，不在 executor 内实现。
- **最小策略源**：在上游控制平面尚未建成前，使用本地文件 / ConfigMap provider 承载与未来控制平面同形态的 effective policy；该 provider 不是空实现，必须能验证热加载、pause、last-known-good 和作用域覆盖。
- **验收信号**：策略文件变更不需要重启 worker；策略源异常或策略校验失败时保留 last-known-good 并暴露指标；全局 / 作用域 pause 在约定时间内生效；过期 `deadline_at` 任务在发起请求前跳过并发布 terminal `crawl_attempt`；Fetch Command `max_retries` 覆盖默认重试 / 投递上限；SIGTERM 后立即停止 `XREADGROUP` / `XAUTOCLAIM`，未完成消息保留 PEL；不得引入 URL 调度、策略分组成员管理或外置 scheduler 语义。
- **明确不做**：不做 production 复刻验证；不做 Kafka outbox / 故障补偿；不做 poison message / DLQ；不做完整 Grafana / 告警落地；不做 JS 渲染或浏览器抓取。

### M5：生产就绪与可靠性补偿

- **目标**：在正式 production 部署前完成 staging 到 production 的等价复刻验证，并补齐长期稳定抓取所需的可靠性与生产治理能力。
- **状态**：后置。
- **对应 spec**：待规划。
- **能力范围**：
  - production 复刻 staging 验证：真实多出口 IP、sticky-pool、pacer、soft-ban feedback、delayed buffer、Redis 写入边界、Kafka publish smoke、Object Storage 权限、ConfigMap / Secret 审核、DaemonSet dry-run / apply、PEL 清空和指标抓取。
  - Kafka outbox / 故障补偿：对象已写入但 Kafka 长时间不可用时的本地持久缓冲、重放、高水位告警和补偿流程。
  - 24 小时稳定性压测、单节点 30-50 pages/sec、P95 延迟、Kafka / Redis / OCI 抖动恢复验证。
  - 对象生命周期策略、孤儿对象巡检和 `crawl_attempt` 与对象存在性抽样校验。
  - 发布 / 回滚 SOP、Secret 最小权限、Kafka ACL、OCI policy、Redis prefix 隔离和敏感配置审计。
- **验收信号**：production 可按 staging 同一流程复刻部署和验证；长时间运行无不可解释的 PEL 堆积、对象丢失或 Kafka 事件丢失；故障补偿具备可审计重放路径；生产发布、暂停、回滚和恢复流程可执行。

### M5a：生产观测与队列治理

- **目标**：把 M0-M4 已有指标组织成正式生产看板、告警和队列治理契约，补齐第六类与 executor 之间的反压和失败处理协议。
- **状态**：后置。
- **对应 spec**：待规划。
- **能力范围**：
  - Grafana 基础看板、Prometheus alert rules、on-call SOP、容量与成本面板。
  - Redis queue lag、PEL 总量、consumer idle、delayed buffer、pause、policy LKG、依赖健康和出口健康的跨 worker 观测。
  - poison message / DLQ 协议：非法消息、超过最大投递次数、永久失败消息的结构化失败原因和上游消费方式。
  - 队列分片与反压契约：第六类如何分 stream，如何根据 executor backlog / delayed buffer / pause 状态减速或重排。
- **当前过渡行为**：非法 Fetch Command 解析失败或缺少 `url` / `job_id` / `canonical_url` 时，executor 记录日志和指标后直接 `XACK` 丢弃，不发布 `crawl_attempt`，也不写 DLQ。
- **验收信号**：生产运行面板可定位队列、出口、源站、Redis、Kafka、OCI 和策略源问题；关键异常可告警；第六类能消费或处理 executor 暴露的队列失败与反压信号。

### M6：JS 渲染与现代反爬补齐

- **目标**：在第二类内部扩展渲染型抓取能力，不新建平行执行系统。
- **状态**：后置。
- **对应 spec**：待规划。
- **验收信号**：渲染任务与普通 fetch 共享 `crawl_attempt` 事件语义；不会把解析或内容质量职责带回执行层。

## 2. 跨阶段债务

| 编号 | 债务 | 当前处理 | 回填触发条件 |
|---|---|---|---|
| D-DEBT-1 | URL 归一化库 Python 实现先由本系统持有 | 当前保留在 `src/crawler/crawler/contracts/canonical_url.py` | 契约仓库提供官方 Python 实现和共享黄金测试集 |
| D-DEBT-2 | 事件 topic 与 schema 暂在本仓库 | 当前位于 `specs/002-p1-content-persistence/contracts/` | 系统群契约仓库建成并接管事件 schema |
| D-DEBT-3 | Politeness 仍以 env / ConfigMap 静态参数为主 | 005 已按 ADR-0012 补齐自适应防封闭环并通过 staging 验证 | 控制平面策略下发链路可用 |
| D-DEBT-4 | `content_sha256` 只覆盖 HTML 快照场景 | 当前仅在 `storage_result=stored` 时计算 | 上层架构要求所有响应统一 Raw 指纹 |
| D-DEBT-5 | Redis 只读边界审计仍可加宽 | 现有脚本已覆盖 key diff 与目标 stream `XLEN` 前后不变 | 进入 M5a 队列治理或生产审计规则收口 |
| D-DEBT-6 | 严格优雅停机语义未收口 | 当前满足 PEL 不清空与可恢复底线，但 SIGTERM 后仍可能继续 claim / 重复处理 | M4 严格优雅停机任务 |
| D-DEP-1 | 短窗口执行安全状态与第五类长期画像事实边界待契约化 | 当前以本系统本地短窗口判断为准 | 第五类发布 Host / IP / ASN 画像事实与执行缓存切分契约 |

## 3. 未完成关键生产能力

1. production 复刻 staging 验证：真实多出口 IP 下验证 sticky-pool、pacer、soft-ban feedback、delayed buffer、M4 policy / pause / deadline / retry、Redis 写入边界、Kafka publish smoke、Object Storage 权限和指标抓取。
2. K8s DaemonSet + hostNetwork production 部署。staging 已验证通过；production 仍需 dry-run、apply 与集群审计。
3. Grafana 基础看板、告警和运维 SOP。
4. 24 小时稳定性压测、30-50 pages/sec 单节点目标验证。
5. 本地出站事件缓冲和 Kafka 故障补偿。
6. Redis 只读边界审计补强：在现有 key diff + `XLEN` 前后对比之外，增加允许状态变化清单和更宽 audit pattern。
7. poison message / DLQ 协议、队列分片与第六类反压契约。

## 4. 明确后置或暂不规划

| 能力 | 当前决策 |
|---|---|
| ClickHouse Host profile | 归第五类，后置且不在本仓库实现。 |
| PostgreSQL `crawl_logs` / `page_snapshots` / `pages_latest` | 归第五类消费端投影，不在本仓库实现。 |
| `parse-tasks` topic 和下游解析服务 | 取消派发模式；第三类直接订阅 `crawl_attempt`。 |
| DLQ 专用 topic / poison message 协议 | 后置到 M5a；当前非法消息记录日志和指标后 `XACK` 丢弃，不发布 `crawl_attempt`。 |
| 本地 outbox / Kafka 故障补偿队列 | 后置到 M5；当前接受 Kafka 失败日志与对象保留。 |
| production 复刻验证与正式部署 | 后置到 M5；当前 M4 不要求 production dry-run / apply。 |
| 完整 Grafana / 告警落地 | 后置到 M5a；M4 只补新增能力需要的指标与告警草案。 |
| Terraform / cloud-init 辅助 IP 与 EIP 自动化 | 暂不规划，规模化时再评估。 |
| Heritrix 数据迁移与旧服务下线 | 后置，待 Scrapy 生产链路稳定后再评估。 |

## 5. 下一阶段建议

staging 已作为 production 功能验证等价镜像环境完成 004 / 005 的部署基础、005 功能验证，以及 004 的干净 Fetch Command 消费、`crawl_attempt` 发布后 `XACK`、Object Storage 内容持久化、debug stream、pause flag、手动删除 / RollingUpdate 下 PEL reclaim。004 可在 staging 口径下关闭；production 复刻验证和正式部署后置到 M5，在明确进入生产发布前再按同一操作流程执行。

007 已完成 M4 本地实现与验证。下一步建议进入 M5 前的评审：确认是否先在 staging 等价环境复跑 M4 policy / pause / deadline / retry / shutdown 验证，再决定 production 复刻窗口。

M3 第一版曾按 T015c 过渡运行假设设计：低频手动滚动、任务幂等、允许少量重复抓取、PEL 可恢复。007 已补更早 shutdown flag 入口，使后续 production 复刻前具备更清晰的滚动更新语义；仍建议在 staging 复测 SIGTERM / PEL 行为后再进入 production。

D-DEBT-5（只读边界 audit pattern 加宽）按现状层债务跟进，不阻塞 M3 启动。

若团队决定由本仓库临时维护某个消费端验证工具，必须先通过 ADR 说明其临时性质、退出条件和不进入第二类终态边界的原因。
