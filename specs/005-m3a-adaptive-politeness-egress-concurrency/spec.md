# 功能规格：M3a 自适应 Politeness 与出口并发控制

**功能分支**：`005-m3a-adaptive-politeness-egress-concurrency`
**创建日期**：2026-04-30
**状态**：已完成（本地实现 + staging 等价镜像环境验证通过；production 复刻待发布流程执行）
**输入来源**：`.specify/memory/product.md`、`.specify/memory/architecture.md`、`state/current.md`、`state/roadmap.md`、`state/decisions/0003-redis-write-side-belongs-to-scheduler.md`、`state/decisions/0004-use-redis-streams-consumer-group-for-fetch-queue.md`、`state/decisions/0006-ack-fetch-command-after-crawl-attempt-published.md`、`state/decisions/0010-system-group-class-2-positioning.md`、`state/decisions/0012-adaptive-politeness-and-egress-concurrency.md`

## 定位与边界检查

- **Roadmap 位置**：M3a：自适应 Politeness 与出口并发控制。
- **产品门禁**：仍服务第二类抓取执行系统；不引入 URL 选择、业务优先级、重抓窗口、解析派发、事实层投影或内容质量判断。
- **架构边界**：本 spec 只定义执行层短窗口安全控制：sticky-pool、per-(host, ip) pacer、IP cooldown、host slowdown、软封禁反馈、本地有界延迟和相关指标。
- **相关 ADR**：ADR-0003、ADR-0004、ADR-0006、ADR-0010、ADR-0012。

## 关闭小结

2026-05-03，spec005 以 staging 等价镜像环境为功能验收口径完成关闭。当前系统已经具备准生产级自适应防封禁能力：

- **K8s 常驻执行形态**：DaemonSet + `hostNetwork=true` + 每目标 node 单 worker，支持 health / readiness / Prometheus 暴露。
- **受控滚动更新**：DaemonSet 采用 `RollingUpdate maxUnavailable=1`，staging / production 使用一致 rollout 观察流程。
- **多出口 IP 运行时发现**：worker 能在 `enp0s5` 上发现 primary + secondary IPv4，并通过 Scrapy `bindaddress` 使用不同本地 IP 出口。
- **host-aware sticky-pool**：同一 host 映射到稳定的 K 个出口身份候选池，避免 `host -> 1 IP` 的单点热点。
- **per-(host, egress identity) pacing**：按 `(host, egress_identity)` 控制最小启动间隔、jitter 和 backoff。
- **本地有界 delayed buffer**：未 eligible 消息保留在本地有界缓冲，未执行不 ack；buffer 满时停止继续 `XREADGROUP`。
- **软封禁反馈闭环**：429、challenge、反爬 200、timeout、连接失败和 5xx 被归一化为不同信号，并按 `(host, ip)`、`ip`、`host`、可选 `(host, asn)` 维度影响 backoff / cooldown / slowdown。
- **Redis TTL 执行态边界**：只写 `EXECUTION_STATE_REDIS_PREFIX` 下短窗口状态，不写 URL 队列、优先级、去重或长期画像事实。
- **可靠 ack 语义**：仍遵守 `crawl_attempt` 发布成功后才 `XACK`；Kafka failure 或未完成消息留在 PEL。
- **Kafka 发布链路 smoke**：staging 中 broker 网络、CA 路径和最小 producer publish 已验证。
- **运行指标可解释性**：已观察到 sticky-pool、egress identity selection、pacer delay、多出口 IP 204 请求和依赖健康等 Prometheus 指标。

不属于本次关闭范围：

- production 复刻验证。
- Grafana 看板 / 告警。
- 长期稳定性压测。
- 控制平面动态策略下发。
- JS 渲染、浏览器指纹或复杂 TLS 指纹对抗。

## 背景

004 目标集群资源准备过程中已确认 OKE crawler node pool、`hostNetwork` 所需节点标签、`enp0s5` 多 IPv4 网卡和 Redis / Kafka Secret 现场。但继续推进 004 会把部署验证和功能缺口混在一起。

当前系统的主要缺口是：P0 / P2 时代的 `STICKY_BY_HOST = host -> 1 IP`、静态 `DOWNLOAD_DELAY` 和 `CONCURRENT_REQUESTS_PER_DOMAIN` 只能支持早期验证，不足以支撑生产中有限出口 IP 池下的吞吐与防封平衡。

业务侧没有承诺单 host 最大请求速率，因此本系统不能把目标写成固定 per-host rate cap。005 的目标是把生产策略调整为观测驱动的自适应防封闭环，同时守住第二类边界：只做执行安全控制，不做 URL 调度决策。

## 已确认决策

1. **生产策略**：采用 host-aware sticky-pool，而不是 `host -> 1 IP`。
2. **Scrapy slot**：第一层最小实现复用 Scrapy downloader slot，设置 `request.meta["download_slot"] = f"{host}@{egress_identity}"`。
3. **出口身份**：优先使用 public egress IP；如果第一版没有 private-to-public 映射，允许暂用 bind private IP 作为 `egress_identity`，但必须标注 `egress_identity_type=bind_ip` 并保留补齐映射空间。
4. **反馈维度**：软封禁反馈必须区分 `(host, egress_ip)`、`egress_ip`、`host`、可选 `(host, asn/cidr)`，不得混成“有错就退避”。
5. **Redis 写入边界**：允许 TTL、命名空间隔离、非事实化的短窗口执行安全状态；禁止 URL 队列写入、优先级重排、去重结果和长期 Host / IP / ASN 画像事实。
6. **本地延迟边界**：允许本地 delayed buffer，但必须有容量和时间上限；buffer 满时必须停止读取新 Redis Stream 消息。
7. **004 关系**：005 完成并通过目标验证后，004 才能恢复 ConfigMap 审核、DaemonSet dry-run 和目标集群验证。

## 用户场景与测试

### 用户故事 1 - 单 host 在多个出口身份间受控轮转（优先级：P1）

作为 crawler-executor 运行方，我需要同一 host 不再被锁死到单个出口 IP，而是在一个稳定的小候选池内轮转，从而提高大 IP 池利用率，同时保持源站视角下的可控分散度。

**独立测试**：构造同一 host 的多条 Fetch Command，配置 `STICKY_POOL_SIZE=K`，验证该 host 只使用 K 个候选 `egress_identity`，且多次运行候选池稳定。

**验收场景**：

1. **假设**本节点有 N 个可用出口身份，且 `STICKY_POOL_SIZE=4`，**当**同一 host 连续产生多条请求，**则**出口身份只来自该 host 的 4 个候选身份。
2. **假设**进程重启且 IP 池不变，**当**同一 host 再次生成候选池，**则**候选身份集合保持稳定。
3. **假设**某个候选身份进入 cooldown，**当**同一 host 继续有请求，**则**worker 在剩余可用候选身份中选择，不退回全随机。

### 用户故事 2 - per-(host, ip) pacing 避免同一出口过密访问同一 host（优先级：P1）

作为源站风险控制负责人，我需要避免同一个出口身份对同一 host 过于密集地发起请求，即便全局并发和 IP 池规模较大。

**独立测试**：对同一 `(host, egress_identity)` 注入多条请求，验证两次实际下载开始时间不小于配置的最小间隔，并带有可配置 jitter。

**验收场景**：

1. **假设**`HOST_IP_MIN_DELAY_MS=2000`，**当**两条请求被分配到同一 `(host, egress_identity)`，**则**第二条请求不会在前一条开始后的 2 秒内启动。
2. **假设**两条请求分配到不同 egress identity，**当**host 未触发整体 slowdown，**则**它们可以并行或更紧密地执行。
3. **假设**请求尚未 eligible，**当**本地 delayed buffer 未满，**则**worker 将其保留为本地待执行状态，不发布失败事件、不 `XACK`。

### 用户故事 3 - 软封禁反馈按维度触发退避（优先级：P1）

作为运维人员，我需要系统能根据 429、CAPTCHA / challenge、反爬 200 页、timeout 和 5xx 等反馈动态调整短窗口策略，而不是把所有错误等价处理。

**独立测试**：使用可控测试 server 返回 429、challenge HTML、普通 5xx 和成功响应，验证不同信号写入不同维度的执行安全状态，并影响后续调度。

**验收场景**：

1. **假设**同一 `(host, egress_identity)` 连续出现 429 或 challenge，**当**达到阈值，**则**只对该 `(host, egress_identity)` 增加 backoff，不影响同 host 的全部出口身份。
2. **假设**同一 egress identity 在多个 host 上集中出现 challenge，**当**达到阈值，**则**该 egress identity 进入 IP 级 cooldown。
3. **假设**同一 host 在多个 egress identity 上集中出现 challenge，**当**达到阈值，**则**host 进入整体 slowdown。
4. **假设**同一 host 在同一 ASN / CIDR 分桶内集中出现 challenge，**当**ASN / CIDR 功能启用，**则**该分桶进入短窗口 soft limit；第一版可以只暴露指标，不强制启用控制。

### 用户故事 4 - 本地 delayed buffer 有界且不会把 PEL 变成隐藏调度队列（优先级：P1）

作为第六类和运维人员，我需要 crawler-executor 在本地 pacing 时保留 Redis Streams 的可恢复语义，不无限预读消息，也不把大量 pending 消息藏在某个 worker 内部。

**独立测试**：配置很小的 `LOCAL_DELAYED_BUFFER_CAPACITY`，写入超过容量的同 host 请求，验证 buffer 满后 worker 停止 `XREADGROUP`，已读但未执行的消息留在 PEL 且不 `XACK`。

**验收场景**：

1. **假设**本地 delayed buffer 达到容量上限，**当**Redis Stream 仍有更多消息，**则**worker 不再读取新消息，直到 buffer 释放。
2. **假设**delayed 消息尚未实际抓取，**当**worker 退出，**则**该消息不 `XACK`，保留在 PEL 等待后续 reclaim。
3. **假设**delayed 消息等待时间超过 `MAX_LOCAL_DELAY_SECONDS`，**当**worker 仍无法执行，**则**记录告警指标并保持停止读取新消息，不发布虚假的 `crawl_attempt` 成功或失败事实。

### 用户故事 5 - Redis 执行态写入可审计且不污染 URL 队列（优先级：P1）

作为架构维护者，我需要证明 005 增加的 Redis 写入只属于短窗口执行安全状态，不会违反 ADR-0003 / ADR-0010。

**独立测试**：运行包含成功、429、challenge、timeout 和 delayed buffer 的验证场景，审计 Redis key diff，确认只出现允许前缀和 TTL 状态，不出现 URL 队列、去重或优先级 key。

**验收场景**：

1. **假设**启用 005 的反馈闭环，**当**发生 soft-ban，**则**Redis 只写入 `EXECUTION_STATE_REDIS_PREFIX` 下的 TTL key。
2. **假设**运行完整验证场景，**当**审计 Redis key diff，**则**不得出现 outlink queue、scheduler queue、dupefilter、priority 或长期 profile key。
3. **假设**执行安全 key 写入成功，**当**检查 TTL，**则**所有 key 均有 TTL，且不超过 `EXECUTION_STATE_MAX_TTL_SECONDS`。

### 用户故事 6 - 指标能解释吞吐与防封取舍（优先级：P2）

作为运维人员，我需要通过 Prometheus 指标看到 sticky-pool、pacer、cooldown、slowdown、challenge rate 和 delayed buffer 状态，从而判断吞吐瓶颈和封禁风险来自哪里。

**独立测试**：触发候选池选择、pacer delay、IP cooldown、host slowdown 和 buffer full，验证对应指标存在且 label 不泄露敏感凭据。

**验收场景**：

1. **假设**请求因 `(host, egress_identity)` pacer 延迟，**当**采集指标，**则**可以看到 delayed count / delay seconds 分布。
2. **假设**IP 进入 cooldown，**当**采集指标，**则**可以看到 cooldown gauge 和触发原因计数。
3. **假设**challenge 信号出现，**当**采集指标，**则**可以按 host hash、egress identity hash、signal type 聚合；ASN / CIDR label 第一版可选。

## 功能需求

- **FR-001**：系统必须新增 `egress_identity` 概念，优先代表 public egress IP；缺少映射时允许使用 bind private IP，并通过 `egress_identity_type` 标注。
- **FR-002**：系统必须支持 host-aware sticky-pool，按 host 从当前可用出口身份中稳定选择 K 个候选身份。
- **FR-003**：sticky-pool 的 K 必须可配置，且不能大于可用出口身份数量；可用出口身份少于 K 时使用实际数量。
- **FR-004**：出口选择必须避开已处于 IP cooldown 的身份，并尽量避开当前 `(host, egress_identity)` backoff 未到期的身份。
- **FR-005**：Scrapy Request 必须设置 `download_slot = "{host}@{egress_identity}"` 或等价语义，使 downloader slot 从 host 维度扩展到 `(host, egress_identity)` 维度。
- **FR-006**：系统必须实现 per-(host, egress_identity) pacer，支持最小间隔、jitter、指数 backoff 和最大 backoff。
- **FR-007**：系统必须实现本地 delayed buffer，保存已从 Redis Streams 读取但因 pacing 暂未 eligible 的 Fetch Command。
- **FR-008**：本地 delayed buffer 必须配置容量上限；达到上限时必须停止 `XREADGROUP` 读取新消息。
- **FR-009**：本地 delayed buffer 必须配置最大等待时间；超限时必须记录日志和指标，不得发布虚假的 `crawl_attempt`，不得 `XACK` 未执行消息。
- **FR-010**：worker 停机时，未执行或未成功发布 `crawl_attempt` 的 delayed 消息不得 `XACK`。
- **FR-011**：系统必须识别至少以下反馈信号：HTTP 429、可配置 CAPTCHA / challenge body pattern、可配置反爬 200 body pattern、timeout、连接失败、5xx。
- **FR-012**：反馈信号必须映射到不同退避维度：`(host, egress_identity)`、`egress_identity`、`host`，ASN / CIDR 作为可选扩展。
- **FR-013**：系统必须把短窗口执行安全状态写入允许的 Redis prefix，且每个 key 必须设置 TTL。
- **FR-014**：系统不得向 Redis URL 队列、outlink queue、scheduler queue、dupefilter、priority 或长期 profile key 写入任何内容。
- **FR-015**：系统必须保留 ADR-0006 的 ack 语义：只有 `crawl_attempt` 发布成功后才 `XACK` Fetch Command。
- **FR-016**：系统必须暴露 sticky-pool、pacer delay、delayed buffer、soft-ban signal、backoff、cooldown、host slowdown 的 Prometheus 指标。
- **FR-017**：系统必须保留 `STICKY_BY_HOST` 作为 P0 / 显式回退策略，但 production 和 staging profile 不得继续默认使用该策略。
- **FR-018**：系统必须提供验证脚本，覆盖 sticky-pool、pacer、soft-ban feedback、delayed buffer 边界、Redis 写入边界和指标。

## 非功能需求

- **NFR-001**：所有新增 Redis 执行态 key 必须有 TTL，默认最大 TTL 不超过 24 小时，除非新 ADR 允许。
- **NFR-002**：delayed buffer 不得随 Redis Stream 长度无限增长；内存占用必须由容量配置硬限制。
- **NFR-003**：生产日志和指标不得输出 Kafka / Redis / OCI 凭据。
- **NFR-004**：新增策略不得破坏 P2 的 Kafka failure / PEL reclaim 语义。
- **NFR-005**：在 50-70 个本地出口 IPv4 / node 的目标环境中，sticky-pool 计算和状态查询不得成为明显 CPU 瓶颈。
- **NFR-006**：策略参数必须可由 env / ConfigMap 注入，后续可迁移到控制平面运行时覆盖。

## 关键实体

- **EgressIdentity**：执行器用于代表源站可见出口身份的 key，优先 public egress IP，第一版可 fallback 到 bind private IP。
- **StickyPoolAssignment**：host 到 K 个 EgressIdentity 的稳定候选集合。
- **HostIpPacerState**：`(host, egress_identity)` 的 next-allowed-at、backoff level 和最近反馈。
- **EgressCooldownState**：单个 egress identity 的短窗口 cooldown。
- **HostSlowdownState**：host 级整体降速状态。
- **FeedbackSignal**：从 response / exception / body pattern 中归一化出的执行反馈。
- **LocalDelayedFetchCommand**：已读入 PEL、尚未 eligible 或尚未启动下载的本地待执行命令。

## 边界场景

- IP 池为空或所有候选身份 cooldown。
- sticky-pool K 大于可用 IP 数。
- 同一 host 的消息大量集中，buffer 达到上限。
- worker 在 delayed buffer 持有消息时收到 SIGTERM。
- Kafka publish failure 发生在已完成下载之后。
- Redis 执行态写入失败，但 Redis Streams 消费仍可用。
- CAPTCHA / challenge pattern 误判或漏判。
- public egress 映射缺失，只能使用 bind private IP 作为近似身份。
- ASN / CIDR 数据缺失或 MaxMind 文件不可用。

## 成功标准

- **SC-001**：同一 host 的请求在 sticky-pool K 个候选出口身份内稳定轮转，不再锁死到单个 IP。
- **SC-002**：同一 `(host, egress_identity)` 的请求启动间隔满足配置的 pacer 最小间隔和 backoff。
- **SC-003**：429 / challenge / 反爬 200 页能按 `(host, ip)`、`ip`、`host` 维度触发不同退避。
- **SC-004**：本地 delayed buffer 满时停止 `XREADGROUP`，未执行消息不 `XACK`，停机后可由 PEL reclaim。
- **SC-005**：Redis key diff 只包含允许的短窗口执行安全状态，且所有新增 key 均有 TTL。
- **SC-006**：Prometheus 指标能解释当前请求延迟、cooldown、slowdown 和 challenge 触发原因。
- **SC-007**：005 完成后，004 可以恢复 ConfigMap 审核和 DaemonSet 目标集群验证，不再依赖 `STICKY_BY_HOST` 作为生产默认。

## 不在 005 范围

- 不实现第五类长期 Host / IP / ASN 画像事实。
- 不自动购买、释放、切换云厂商或切换 ASN / IP 段。
- 不改变第六类 URL 选择、优先级、重抓窗口和队列写入职责。
- 不实现完整控制平面运行时下发；005 只要求 env / ConfigMap 参数化。
- 不实现 JS 渲染、浏览器指纹或复杂 TLS 指纹对抗。
- 不恢复 004 DaemonSet 部署验证；005 收口后再恢复。

## 澄清记录

- 2026-04-30：关停 / 滚动仍沿用 ADR-0011 的 B 语义：低频手动滚动、任务幂等、允许少量重复抓取、PEL 可恢复。
- 2026-04-30：生产方向采用自适应防封，不采用静态 per-host rate cap 作为主模型。
- 2026-04-30：`STICKY_BY_HOST` 保留为 P0 / 回退策略，不作为生产默认。
- 2026-05-01：staging 与 production 是物理隔离环境，目标验证应复刻 production 功能口径；staging 默认也切换为 `STICKY_POOL`。
- 2026-04-30：ASN / CIDR 第一版以指标和可选 soft limit 为主，不做云资源自动化。
- 2026-05-03：staging OKE 等价镜像环境验证通过，spec005 按功能验收口径关闭；production 复刻作为发布验证后续执行。
