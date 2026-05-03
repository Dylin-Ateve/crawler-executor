# 当前状态：crawler-executor

**更新日期**：2026-05-03
**对应 commit**：待下次合并后回填
**对照终态**：`.specify/memory/architecture.md`
**当前阶段**：P0 核心链路已验证；P1 `crawl_attempt` producer 已通过目标节点 T055 验证。M2 `specs/003-p2-readonly-scheduler-queue/` 已完成目标节点验证。T015c 优雅停机实现已满足 PEL 不清空与可恢复底线，但目标节点验证显示严格 "SIGTERM 后立即停止读 / claim 并在 drain 时限前退出" 未满足；按任务幂等、允许少量重复抓取的运行假设暂时接受为过渡策略。M3 `specs/004-p3-k8s-daemonset-hostnetwork/` 已完成 staging 等价镜像环境验证。M3a `specs/005-m3a-adaptive-politeness-egress-concurrency/` 已完成本地实现、staging OKE 等价镜像环境验证和真实运行 smoke。006 已完成 M4 前置概念校准：不再使用 `HostGroup` 作为 executor 一等概念，不再把 `scrapy-redis` 作为未来运行形态，`crawl_attempt` 开始透传执行上下文。下一步收敛为 M4“运行时执行策略与停抓控制”：先实现 effective policy 本地 provider、热加载、last-known-good、作用域 pause、`deadline_at` / `max_retries` 生效和严格优雅停机；production 复刻验证、Kafka outbox、DLQ 和完整生产观测后置到后续 milestone。

## 1. 当前架构快照

```text
第六类 Fetch Command / 本地验证输入
        |
        v
Redis Streams consumer group
        |
        v
Scrapy worker
        |
        +--> 本地辅助 IP bindaddress
        +--> Valkey/Redis 短窗口黑名单与 005 执行安全 TTL 状态
        +--> Prometheus 单 worker 指标
        +--> OCI Object Storage gzip HTML 快照
        +--> Kafka crawl_attempt producer
```

当前仍是研发验证形态，不是完整终态：

- 已通过 Redis Streams consumer group 目标节点验证；真实第六类生产队列接入仍待上游联调。
- staging OKE 已完成 004/005 共用的部署基础验证：`crawler-executor` namespace、2 个 `scrapy-egress=true` node、DaemonSet `hostNetwork=true`、`RollingUpdate maxUnavailable=1`、每 node 5 个 `enp0s5` IPv4、health/readiness、Kafka publish smoke、Object Storage smoke、干净 Fetch Command 消费、debug stream、pause flag、PEL reclaim 和 Redis Streams PEL 清空均通过；004 关闭前仅需最终审计与文档状态收口。
- 生产防封和吞吐模型已完成 005 本地与 staging 验证：生产默认切换到 `STICKY_POOL`，支持 host-aware sticky-pool、per-(host, ip) pacer、IP cooldown、host slowdown、软封禁反馈、本地有界 delayed buffer 和 Redis TTL 执行态；production 仍需按 staging 同一流程复刻验证。
- 尚未交付第五类消费端事实投影。
- 尚未完成运行时 effective policy 热加载、last-known-good、作用域 pause、`deadline_at` / `max_retries` 生效和严格优雅停机收口；这些已纳入 M4。
- 控制平面策略作用域已按 ADR-0014 收敛为 `tier` / `site_id` / `host_id` / `politeness_key` / `policy_scope_id`，不再使用 Heritrix 风格 `HostGroup` 作为 executor 概念。

## 1.1 准生产能力小结

截至 2026-05-03，若以 staging 等价镜像环境为功能验收口径，系统已具备以下准生产级能力：

- K8s DaemonSet 常驻执行，`hostNetwork=true`，每目标 node 一个 worker。
- `RollingUpdate maxUnavailable=1` 受控滚动更新。
- `enp0s5` 多 IPv4 发现和 Scrapy `bindaddress` 出口绑定。
- host-aware sticky-pool，避免 `host -> 1 IP` 的单出口热点。
- per-(host, egress identity) pacer，支持最小间隔、jitter、backoff 和 delayed buffer。
- 软封禁反馈按 `(host, ip)`、`ip`、`host`、可选 `(host, asn)` 维度进入短窗口执行安全状态。
- Redis TTL 执行态边界，禁止写 URL 队列、优先级、去重和长期画像事实。
- Redis Streams PEL 可恢复，`crawl_attempt` 发布成功后才 `XACK`。
- Kafka publish smoke、CA 路径和 broker 网络在 staging 通过。
- Prometheus 已能观察 sticky-pool、pacer、多出口请求结果、反馈信号、执行态读写和依赖健康。

production 仍需按 staging 同一流程复刻验证；Grafana / 告警、长期压测、Kafka outbox、DLQ、运行时 effective policy 和 IaC 不属于当前已完成能力。其中运行时 effective policy、pause、`deadline_at` / `max_retries` 生效和严格优雅停机纳入 M4，其余生产化能力后置到 M5 / M5a。

## 2. 模块矩阵

| 终态能力 | 当前状态 | 当前证据 / 说明 |
|---|---|---|
| Scrapy 执行框架 | 部分完成 | 已建立 Scrapy 项目、middleware、spider、pipeline；尚未进入完整生产调度与部署。 |
| 多出口 IP 轮换 | 部分完成 | 单节点真实 Linux + 多辅助 IP + EIP 映射已验证；005 已实现 host-aware sticky-pool；staging K8s hostNetwork 下每 node 5 个 IPv4 验证通过，production 仍需复刻。 |
| IP 健康检查与黑名单 | 部分完成 | Valkey/Redis 失败计数、TTL 黑名单、Prometheus 指标已验证；005 已补齐 soft-ban signal、`(host, ip)` backoff、IP cooldown、host slowdown 和可选 ASN soft limit；staging 运行指标验证通过。 |
| Politeness 策略 | 部分完成 | 已忽略 robots.txt，并保留并发、延迟、重试 fallback；005 已实现 ADR-0012 的自适应防封闭环，本地与 staging 验证通过。M4 将以本地文件 / ConfigMap provider 先实现 effective policy 热加载与 last-known-good，后续控制平面可输出同形态策略。 |
| 分布式调度只读消费 | 完成 P2 目标节点验证；优雅停机严格语义未收口 | 003 已验证 Redis Streams consumer group 单 worker、多 worker、fetch failed、无效消息和 Kafka failure / PEL reclaim；不引入 scrapy-redis 默认 scheduler / dupefilter。只读边界脚本已覆盖 key diff 与目标 stream `XLEN` 前后不变。优雅停机目标节点验证显示当前实现不清空 PEL，但 SIGTERM 后 shutdown flag 触发较晚，退出中的 worker 仍可能继续 claim / 重复处理；当前仅按低频手动滚动、任务幂等、允许少量重复抓取的过渡策略接受。 |
| HTML 对象存储 | 完成 P1 切片 | OCI Object Storage 写入、读取、gzip 校验和失败保护已验证；生命周期策略未配置。 |
| `crawl_attempt` producer | 完成 P2 验证切片 | 目标节点验证覆盖 stored / skipped / storage failed / Kafka failure 分支；003 已补强连接级 fetch failed 事件化。 |
| 执行上下文透传 | 完成 006 校准 | `crawl_attempt` schema / payload 已支持 `command_id`、`trace_id`、`job_id`、`host_id`、`site_id`、`tier`、`politeness_key`、`policy_scope_id`。 |
| 第五类事实投影 | 不属于本系统 | PostgreSQL pages/crawl_logs 等由第五类消费端承接，本仓库只保留 producer 契约。 |
| ClickHouse Host 画像 | 不属于本系统 | 已明确归第五类，当前不在本仓库实现。 |
| 下游 Python 解析服务 | 不属于本系统 | 第三类订阅事件自取 storage_key，本系统不派发 parse-tasks。 |
| K8s 部署 | staging 完成 | 004 已形成 DaemonSet + hostNetwork 模板、探针、配置分层和目标集群审计脚本；staging 已验证 `RollingUpdate maxUnavailable=1`、每 node 单 Pod、IP 池发现、health/readiness、Kafka/Object Storage smoke、干净消费、debug stream、pause flag、PEL reclaim 和 PEL 清空。production 仍需复刻同一流程。 |
| Terraform / cloud-init 自动化 | 暂不规划 | 当前不进入近期规划，后续规模化时再评估。 |
| Prometheus 指标 | 部分完成 | 已有请求、耗时、IP、黑名单、存储、Kafka producer 指标；005 已补 sticky-pool、pacer、delayed buffer、feedback、cooldown、slowdown、Redis 执行态指标；staging 已观察到 sticky-pool、pacer、多 egress IP 204 请求指标，集群级队列、lag、资源面板未完成。 |
| Grafana / 告警 | 未完成 | 尚未配置看板和告警规则。 |
| 24 小时稳定性与 Heritrix 对比 | 未完成 | P0 已决定后置，不阻塞 P1。 |

## 3. 原始目标完成度

| 目标 | 状态 | 当前证据 |
|---|---|---|
| 更换爬虫框架为 Scrapy | 部分完成 | Scrapy worker、spider、middleware、pipeline 已实现并通过真实节点验证。 |
| 多出口 IP 轮换 | 部分完成 | P0 Step 5a/5b 验证多本地 IP 与多个公网 EIP。 |
| 可控 Politeness 策略 | 部分完成 | 支持并发、单域名并发、延迟、重试和 robots 关闭；005 已补齐 sticky-pool、per-(host, ip) pacing、软封禁反馈和本地有界延迟，本地与 staging 验证通过。 |
| 大规模持久化存储 | 部分完成 | HTML 写入对象存储与 `crawl_attempt` producer 已完成；消费端事实投影归第五类。 |
| Host 画像分析能力 | 不属于本系统 | 画像与事实层归第五类。 |
| 可运维 K8s 化部署 | staging 完成 | staging OKE DaemonSet + hostNetwork + RollingUpdate、debug、pause、PEL reclaim、Object Storage 和干净消费闭环已验证；production/IaC 尚未完成。 |

## 4. 原始实施计划对照

### 阶段 1：PoC 验证

| 事项 | 状态 | 备注 |
|---|---|---|
| 单节点 hostNetwork DaemonSet bind 辅助 IP | staging 通过 | staging K8s hostNetwork 下 `enp0s5` 发现 5 个 IPv4，绑定访问与 smoke 指标通过。 |
| 最小化 Scrapy：多 IP 轮换 + Redis 黑名单 | 完成 | P0 已实现并验证。 |
| echo endpoint 多 IP 生效 | 完成 | httpbin/ip 等 echo endpoint 已验证。 |
| 24 小时 vs 单 IP Heritrix 对比 | 未完成 | 后置，未作为进入 P1 的阻塞项。 |
| 单节点稳定 30 pages/sec | 未完成 | 尚未做稳定吞吐压测。 |

### 阶段 2：核心爬虫开发

| 事项 | 状态 | 备注 |
|---|---|---|
| IP 轮换 middleware | 完成 | `LocalIpRotationMiddleware` 已实现。 |
| 健康检查 middleware | 部分完成 | HTTP 失败和黑名单验证完成；captcha/全局策略需扩展。 |
| UA 随机化 | 未完成 | 尚未接入。 |
| 重试 | 部分完成 | Scrapy retry 配置已存在；与 IP 切换策略仍需生产化验证。 |
| 对象存储上传 + Kafka 投递 | 完成 P1 切片 | 已验证 HTML + `crawl_attempt` producer，覆盖成功、跳过、对象存储失败和 Kafka 失败记录。 |
| Redis Streams 队列消费 | 完成 P2 目标节点验证 | 已验证 `XREADGROUP` 只读消费、`crawl_attempt` 发布成功后 `XACK`、多 worker 正常 ack 路径和 Kafka failure / PEL reclaim。 |
| Prometheus 指标暴露 | 部分完成 | 单 worker 指标已可用，集群级指标未完成。 |

### 阶段 3：存储与下游

| 事项 | 状态 | 备注 |
|---|---|---|
| PostgreSQL 集群 + pg_partman | 不属于本系统 | 已迁出到第五类事实层。 |
| ClickHouse 集群 | 不属于本系统 | Host 画像归第五类。 |
| Kafka consumer 写 PG | 不属于本系统 | 本仓库只负责 producer 事件契约。 |
| 对象存储生命周期策略 | 未完成 | P1 不删除旧对象，后续再处理。 |

### 阶段 4：自动化与规模化

| 事项 | 状态 | 备注 |
|---|---|---|
| Terraform 节点 + 辅助 IP + EIP | 暂不规划 | 当前不进入近期规划。 |
| cloud-init 节点初始化 | 暂不规划 | 当前不进入近期规划。 |
| 5 台灰度观察 | 未完成 | 未开始。 |
| 扩至全量并关闭 Heritrix | 未完成 | 未开始。 |

### 阶段 5：观测与调优

| 事项 | 状态 | 备注 |
|---|---|---|
| Grafana 看板 | 未完成 | 未开始。 |
| 告警规则 | 未完成 | 未开始。 |
| Host 画像报表 | 不属于本系统 | 第五类输出。 |
| 反爬反馈调优 | 未完成 | 依赖长期运行数据。 |

## 5. 已知技术债

- D-DEBT-1：URL 归一化库 Python 实现先由本系统持有，后续迁移到契约仓库。
- D-DEBT-2：`crawl_attempt` schema 暂在本仓库，后续迁移到契约仓库。
- D-DEBT-3：005 已补齐 env / ConfigMap 参数化的自适应防封闭环，并通过 staging 验证；M4 将先用本地文件 / ConfigMap provider 实现 effective policy 热加载、last-known-good 和作用域 pause，后续再接控制平面运行时下发。
- D-DEBT-4：`content_sha256` 当前只覆盖 HTML 快照场景。
- D-DEBT-5：P2 只读边界目标节点脚本已覆盖 Redis key diff 与目标 stream `XLEN` 前后对比，后续可继续补允许状态变化清单和更宽 audit pattern。
- D-DEBT-6：T015c 优雅停机当前只满足 PEL 不清空与可恢复底线；严格 "SIGTERM 后立即停止 `XREADGROUP` / `XAUTOCLAIM`、drain deadline 前退出" 未满足，后续需修正更早停机入口或调整 ADR-0009 / FR-022 的严格语义。
- D-DEP-1：短窗口执行安全状态与第五类 Host / IP / ASN 长期画像事实的切分契约待回填。

## 6. 运行中的关键指标

当前已有单 worker 指标基础，尚未形成稳定生产看板：

- 请求总数、HTTP 状态码计数。
- 响应耗时。
- 活跃 IP 数、黑名单数量。
- sticky-pool、per-(host, ip) backoff、IP cooldown、host slowdown、challenge rate 等指标已补齐，staging 已观察到 sticky-pool、pacer 与多出口请求指标；仍需生产看板化。
- 对象存储上传结果。
- Kafka producer 发布结果。
- M4 仍需补 policy load、policy version、last-known-good、pause、deadline expired、max retries terminal、shutdown drain 等运行时控制指标。
