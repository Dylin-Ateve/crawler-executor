# 功能规格：P3 K8s DaemonSet + hostNetwork 生产部署基础

**功能分支**：`004-p3-k8s-daemonset-hostnetwork`  
**创建日期**：2026-04-30  
**状态**：已完成（staging 等价镜像环境验证通过；production 复刻进入发布流程）
**输入来源**：`.specify/memory/product.md`、`.specify/memory/architecture.md`、`state/current.md`、`state/roadmap.md`、`state/decisions/0003-redis-write-side-belongs-to-scheduler.md`、`state/decisions/0004-use-redis-streams-consumer-group-for-fetch-queue.md`、`state/decisions/0006-ack-fetch-command-after-crawl-attempt-published.md`、`state/decisions/0008-kafka-publish-failure-not-in-max-deliveries-terminal-semantics.md`、`state/decisions/0009-graceful-shutdown-and-pel-handover.md`、`state/decisions/0010-system-group-class-2-positioning.md`、`state/decisions/0013-k8s-daemonset-uses-rolling-update.md`

## 定位与边界检查

- **Roadmap 位置**：M3：生产部署基础。
- **产品门禁**：仍服务第二类抓取执行系统，不引入 URL 选择、优先级决策、解析派发、事实层投影或内容质量判断。
- **架构边界**：本 spec 只定义 crawler-executor 在 K8s 内常驻运行、节点级网络访问、配置注入、健康检查和调试路由；不改变第六类队列写入侧与第五类事实层职责。
- **相关 ADR**：ADR-0003、ADR-0004、ADR-0006、ADR-0008、ADR-0009、ADR-0010、ADR-0013。ADR-0011 已被 ADR-0013 替代，只保留历史背景价值。

## 背景

P2 已验证 Redis Streams consumer group、多 worker 正常 ack 路径、Kafka failure / PEL reclaim、只读边界和无效消息处理。当前系统已能支撑多个 worker 从同一队列常驻消费并发布 `crawl_attempt`，但仍处于目标节点脚本验证形态，尚未具备 K8s 生产部署基础。

M3 的目标是把 crawler-executor 推进到 K8s 集群中的节点级常驻部署形态：每台具备多出口网卡的 crawler node 运行一个 crawler pod，pod 通过 `hostNetwork` 访问宿主机辅助 IPv4 池，持续只读消费第六类 Redis Streams 抓取指令，并保留对单个 node / pod 的精确调试能力。

本 spec 不追求一次性完成大规模生产调优。M3 只收口部署基础、运行参数注入、健康探针、指标暴露、节点隔离、调试路由与滚动更新约束。

## 暂停与恢复记录

**暂停日期**：2026-04-30

**暂停原因**：目标集群资源准备过程中发现生产上线前仍存在功能性遗漏。继续推进 004 会把部署问题、环境问题和功能缺口混在同一条验证链路里，不利于定位和回滚。因此 004 暂停在“部署基础准备 / 目标集群现场记录”阶段，等待后续新 spec 明确并补齐功能缺口后再恢复。

**恢复日期**：2026-05-03

**恢复原因**：005 已完成本地实现与 staging OKE 等价镜像环境验证，补齐 004 暂停时识别出的自适应 politeness、sticky-pool、per-(host, egress identity) pacer、soft-ban feedback、本地有界延迟、Redis TTL 执行态边界与相关指标缺口。004 重新进入 staging 验证与关闭收口阶段。

**当前 staging 现场**：

- OKE node pool 已创建并用于第一轮实测：`scrapy-node-pool`。
- node pool subnet：`subnetCollection`。
- crawler node 数量：2。
- crawler 调度 label：`scrapy-egress=true`，两个 node 均已确认存在。
- taint：暂未配置，符合 004 第一轮实测策略。
- host interface：`enp0s5`。
- staging 每个 node 的 `enp0s5` IPv4 数量：5，按 `M3_IP_POOL_EXPECTED_RANGE=5-5` 验证；production profile 仍按 `60-70` 验证。
- Kafka broker TCP 9092 已在 staging 从所有 crawler node IP 连通；容器 CA 路径使用 `/etc/ssl/certs/ca-certificates.crt`。
- K8s namespace：`crawler-executor`。
- K8s Secret 已创建且 key 存在：
  - `crawler-executor-redis`：`fetch_queue_redis_url`、`redis_url`。
  - `crawler-executor-kafka`：`username`、`password`。
- 已新增生产 / staging 环境 profile：
  - `deploy/environments/production.env`：记录当前 OCI / OKE 生产候选参数。
  - `deploy/environments/staging.env`：复刻 production 功能口径，仅保留 staging 资源规模、端点、凭据和存储 bucket 等物理差异。

**已由 005/staging 验证覆盖的 004 基础项**：

- ConfigMap / DaemonSet 已在 staging apply 并完成 server dry-run。
- `run-m3-k8s-daemonset-audit.sh` 通过：`hostNetwork=true`、`ClusterFirstWithHostNet`、`RollingUpdate maxUnavailable=1`、每 node 单 Pod、health/readiness 与 IP 池发现均通过。
- staging 最小 Kafka producer smoke 通过，Redis Streams PEL 已清空。

**关闭结论**：

1. 干净 Fetch Command smoke 已验证 DaemonSet worker 消费、`crawl_attempt` 发布成功后 `XACK`，最终 PEL `pending=0`。
2. Object Storage 独立 smoke 与 HTML smoke 均验证成功，`storage_result=stored`。
3. debug stream 已验证定向路由到 `crawl:tasks:debug:<node>` / `crawler-executor-debug:<node>`，事件保留 debug 上下文，debug PEL `pending=0`。
4. pause flag 已验证 ConfigMap volume 传播、paused 阶段不读新消息、恢复后继续消费并 `pending=0`。
5. 手动删除 owner pod 已验证 PEL 可接管，消息最终发布并 `XACK`；重复 publish 使用同一 `attempt_id`，符合当前少量重复抓取假设。
6. 依赖异常不接入 liveness / readiness：staging 曾观察 Kafka 连接异常进入依赖健康指标，最终审计中 liveness/readiness 仍保持 OK；Redis/OCI 本轮完成正向 smoke，破坏性故障注入和告警规则留给 production 运维验证。

## 已确认决策

1. **部署形态**：采用专用 crawler node pool + DaemonSet + `hostNetwork: true` + 每个 node 一个 crawler pod。`dnsPolicy` 使用 `ClusterFirstWithHostNet`。
2. **调度隔离**：crawler node pool 当前命名为 `scrapy-node-pool`，节点调度 label 为 `scrapy-egress=true`；M3 第一轮实测暂不配置 taint，普通 workload 隔离先依赖专用 node pool + label，taint / toleration 作为后续增强隔离项保留。
3. **滚动更新策略**：采用 `RollingUpdate maxUnavailable=1`，服务 staging / production 一致的标准 rollout 操作；消息可靠性继续依赖 PEL 可恢复与 `crawl_attempt` 发布后 ack 语义。
4. **关停语义**：M3 选择 ADR-0009 的 B 路径：drain 较短，未完成 in-flight 留 PEL，由后续 worker `XAUTOCLAIM` 接管；低频手动滚动、任务幂等、允许少量重复抓取是当前运行假设。
5. **健康检查口径**：liveness 只检查进程 / reactor / metrics endpoint 基本存活；readiness 不因 Kafka / Redis / OCI 短暂不可达而失败。外部依赖健康通过 Prometheus 指标和告警承接。
6. **调试事件边界**：debug stream 产生的 `crawl_attempt` 仍发布到正式 Kafka topic，但 Fetch Command 必须携带 `tier=debug`、可识别 `job_id` / `trace_id`，第五类按 `tier=debug` 过滤或单独标记。
7. **IP 池来源**：第一版采用启动时扫描宿主机可用 IPv4 + `EXCLUDED_LOCAL_IPS` 过滤；NIC 运行期变更通过重启 pod 生效，暂不做周期 rescan。
8. **网卡规模假设**：每个 node 暂按 50-70 个出口 IP / 辅助 IPv4 上限设计，不再沿用 P0 约 44 个 IP 的限制作为 M3 上限。

## 用户场景与测试

### 用户故事 1 - 每个 crawler node 常驻一个执行 pod（优先级：P1）

作为运维人员，我需要每台具备多出口 IP 的 crawler node 自动运行一个 crawler-executor pod，并让该 pod 直接使用宿主机网络栈访问本地辅助 IPv4 池。

**优先级理由**：这是从目标节点脚本验证进入集群常驻消费的入口。

**独立测试**：给两个测试 node 打上 crawler label，部署 DaemonSet，验证每个 node 恰好一个 crawler pod 且 pod 使用 `hostNetwork`。

**验收场景**：

1. **假设** node 具备 `scrapy-egress=true` label，**当** DaemonSet 发布，**则**每个匹配 node 上运行一个 crawler pod。
2. **假设** node 未打 `scrapy-egress=true` label，**当** DaemonSet 发布，**则**crawler pod 不会调度到该 node。
3. **假设** pod 启动，**当**程序发现 IP 池，**则**仅使用本 node 可用 IPv4，且排除 `EXCLUDED_LOCAL_IPS`。

### 用户故事 2 - 集群内常驻消费 Redis Streams（优先级：P1）

作为第六类调度系统，我需要 crawler-executor 在 K8s 集群中持续只读消费 `crawl:tasks`，并保持 P2 的 ack / PEL / Kafka failure 语义。

**优先级理由**：常驻消费是 M3 的核心运行目标。

**独立测试**：向共享 Redis Stream 写入一批 Fetch Command，验证多个 node 上的 DaemonSet pod 共同消费，发布 `crawl_attempt` 后再 `XACK`。

**验收场景**：

1. **假设** Redis Stream 中存在有效 Fetch Command，**当**多个 crawler pod 常驻运行，**则**任务被消费并发布 `crawl_attempt`。
2. **假设** Kafka 短暂不可达，**当**pod 处理完成但发布失败，**则**消息不 `XACK`，留在 PEL，后续可被 `XAUTOCLAIM` 接管。
3. **假设** pod 重启，**当**其退出时仍有未 ack 消息，**则**不主动清空 PEL，后续由其它 worker 接管。

### 用户故事 3 - 精准定向调试 node / pod / 出口 IP（优先级：P1）

作为开发和运维人员，我需要把一批调试 URL 精准送到指定 node 上的指定 crawler pod，观察该 pod 的日志、指标、PEL 和出口 IP 行为。

**优先级理由**：多出口 IP 和节点级网络问题需要低成本定位，否则 M3 上线后排障成本过高。

**独立测试**：给指定 node 打 debug label，使用 debug stream `crawl:tasks:debug:<node_name>` 和独立 consumer group，向该 stream 写入 Fetch Command，验证只有目标 pod 消费。

**验收场景**：

1. **假设**指定 node 运行 crawler pod，**当**debug stream 写入任务且目标 pod 使用 debug 配置启动，**则**只有目标 pod 消费该调试流量。
2. **假设**debug Fetch Command 携带 `tier=debug`，**当**发布 `crawl_attempt`，**则**事件中保留 debug 上下文，供第五类过滤或标记。
3. **假设**调试结束，**当**恢复生产 stream 配置，**则**pod 回到 `crawl:tasks` / `crawler-executor` 消费组，不残留 debug 配置。

### 用户故事 4 - 健康检查与指标不放大依赖抖动（优先级：P1）

作为运维人员，我需要 liveness / readiness 能反映 crawler pod 自身是否存活，同时避免 Kafka、Redis 或 OCI 的短暂抖动造成全集群 unready。

**优先级理由**：错误的探针会导致雪崩式重启或误警。

**独立测试**：模拟 Kafka / Redis / OCI 短暂不可达，验证 liveness 不失败，readiness 不因单次依赖抖动失败；Prometheus 指标能反映依赖异常。

**验收场景**：

1. **假设**crawler 进程与 metrics endpoint 正常，**当**Kafka 暂时不可达，**则**liveness 不失败。
2. **假设**Redis 连接短暂失败，**当**worker 记录队列读取失败指标，**则**readiness 不因为一次依赖故障变为 false。
3. **假设**消费循环长期无心跳或进程卡死，**当**探针检查，**则**liveness 或 readiness 按约定失败。

### 用户故事 5 - 紧急停抓可控且不破坏 DaemonSet（优先级：P2）

作为控制平面运营人员，我需要在法律、ToS、封禁或上游事故场景下快速停止读取新任务，但不通过删除 DaemonSet 这种破坏性操作。

**优先级理由**：紧急停抓是架构风险中的关键运维通道，但第一版可以作为 P2 能力收口。

**独立测试**：启用暂停标志，验证 pod 停止 `XREADGROUP` / `XAUTOCLAIM` 新任务，已在 PEL 中的消息按 ADR-0009 / ADR-0008 语义处理。

**验收场景**：

1. **假设**应用层暂停标志开启，**当**worker 运行，**则**不读取新 Fetch Command。
2. **假设**暂停期间 Redis Stream 仍增长，**当**worker 处于 paused 状态，**则**不 ack 未处理消息。
3. **假设**暂停标志关闭，**当**worker 恢复，**则**继续只读消费。

## 边界场景

- node 多于或少于预期网卡数量。
- 单 node 出口 IP 池为空或全部被排除。
- node 运行期新增 / 删除辅助 IP。
- pod 滚动重启时仍有 in-flight 请求。
- Kafka / Redis / OCI 短暂不可达。
- debug stream 流量误投到生产 group。
- debug attempt 污染第五类事实投影。
- `terminationGracePeriodSeconds`、`FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS`、`DOWNLOAD_TIMEOUT` 与 `FETCH_QUEUE_CLAIM_MIN_IDLE_MS` 配置不一致。
- 全集群紧急停抓。

## 需求

### 功能需求

- **FR-001**：M3 必须提供 DaemonSet 或等价节点级部署形态，每个匹配 crawler node 至多运行一个 crawler-executor pod。
- **FR-002**：crawler pod 必须使用 `hostNetwork: true`，以便 bind 宿主机辅助 IPv4 地址。
- **FR-003**：crawler pod 必须使用 `dnsPolicy: ClusterFirstWithHostNet` 或等价 DNS 配置。
- **FR-004**：crawler pod 只能调度到带有 `scrapy-egress=true` node label 的节点；M3 第一轮实测允许暂不配置 taint，后续生产加强隔离时应增加 `scrapy-egress=true:NoSchedule` taint 并使用对应 toleration。
- **FR-005**：consumer name 必须包含 node 与 pod 身份，例如 `${NODE_NAME}-${POD_NAME}`，便于 PEL 追踪和精确排障。
- **FR-006**：生产 stream 默认使用 `crawl:tasks`，consumer group 默认使用 `crawler-executor`。
- **FR-007**：调试 stream 必须与生产 stream 隔离，命名为 `crawl:tasks:debug:<node_name>`；debug consumer group 命名为 `crawler-executor-debug:<node_name>`。
- **FR-007a**：debug consumer name 必须命名为 `${NODE_NAME}-${POD_NAME}-debug`，并可从 Redis PEL 反查 node / pod。
- **FR-008**：debug Fetch Command 必须携带 `tier=debug`，并保留可追踪 `job_id` / `trace_id`；debug attempt 仍进入正式 `crawl_attempt` topic，由下游按 `tier=debug` 过滤或标记。
- **FR-009**：IP 池第一版由 pod 启动时扫描宿主机可用 IPv4 得到，并通过 `EXCLUDED_LOCAL_IPS` 过滤；运行期 NIC 变化通过重启 pod 生效。
- **FR-009a**：M3 生产第一版默认 `CRAWL_INTERFACE=enp0s5`；`all` / `*` 可作为显式全接口诊断能力，`LOCAL_IP_POOL` 只作为 debug override。
- **FR-010**：M3 必须支持 50-70 个本地出口 IPv4 的 node 规模假设，且不得把 P0 的 44 IP 数量作为上限。
- **FR-011**：`FETCH_QUEUE_CLAIM_MIN_IDLE_MS` 必须由公式推导，最小值不低于 `max(terminationGracePeriodSeconds * 1000 + safety_margin_ms, MAX_LOCAL_DELAY_SECONDS * 1000 + DOWNLOAD_TIMEOUT * (RETRY_TIMES + 1) * 1000 + KAFKA_DELIVERY_TIMEOUT_MS + safety_margin_ms)`。
  M3 第一版建议 `terminationGracePeriodSeconds=30`、`MAX_LOCAL_DELAY_SECONDS=300`、`DOWNLOAD_TIMEOUT=30`、`RETRY_TIMES=2`、`KAFKA_DELIVERY_TIMEOUT_MS=120000`、`safety_margin_ms=90000`、`FETCH_QUEUE_CLAIM_MIN_IDLE_MS=600000`。
- **FR-012**：M3 采用关停语义 B：低频手动滚动、任务幂等、允许少量重复抓取；未完成 in-flight 在退出后留 PEL 并由后续 `XAUTOCLAIM` 接管。
- **FR-013**：`FETCH_QUEUE_BLOCK_MS` 第一版建议为 `1000`，作为 SIGTERM 响应延迟与 Redis 轮询频率之间的取舍。
- **FR-014**：liveness 不得把 Kafka / Redis / OCI 短暂不可达作为失败条件；liveness 仅检查进程 / reactor / metrics endpoint 基本存活。
- **FR-014a**：M3 liveness endpoint 为 `/health/liveness`，默认端口 `HEALTH_PORT=9411`；返回 200 仅表示进程内 health HTTP handler 可响应。
- **FR-015**：readiness 不得因单次外部依赖抖动失败；外部依赖故障通过 Prometheus 指标和告警承接。
- **FR-015a**：M3 readiness endpoint 为 `/health/readiness`，默认端口 `HEALTH_PORT=9411`；判定条件为 worker 初始化完成且消费循环心跳不超过 `READINESS_MAX_HEARTBEAT_AGE_SECONDS`。
- **FR-016**：M3 必须暴露 Prometheus 指标端口，并能被集群监控系统发现。
- **FR-016a**：M3 必须暴露 Redis / Kafka / OCI 依赖健康指标，但这些指标不得接入 liveness 失败条件。
- **FR-017**：敏感配置必须通过 K8s Secret 或等价机制注入，镜像与仓库不得内嵌真实凭据。
- **FR-018**：行为参数必须通过 ConfigMap / env 注入，包括队列 stream / group、并发、timeout、drain、claim idle、IP 排除列表、debug 模式开关等。
- **FR-019**：M3 必须定义紧急停抓入口，优先采用应用层 pause flag，让 worker 停止读新消息但不删除 DaemonSet。
- **FR-020**：M3 不实现控制平面完整策略下发闭环；pause flag 只作为生产部署基础的最小停抓通道。

### 非功能需求

- **NFR-001**：部署方案不得降低 P0 多出口 IP 选择能力。
- **NFR-002**：部署方案不得降低 P1 对象存储与 `crawl_attempt` producer 能力。
- **NFR-003**：部署方案不得降低 P2 Redis Streams ack / PEL / reclaim 语义。
- **NFR-004**：单 node 单 pod 是 M3 的默认运行模型，不在同一 node 上运行多个 crawler pod 争抢同一 IP 池。
- **NFR-005**：调试能力必须能定位到 node、pod、consumer name、stream 和 trace_id。
- **NFR-006**：M3 不承诺 30-50 pages/sec 单节点稳定吞吐；只定义部署基础与可验证运行形态。

## 配置分层

### Secret

- Secret 契约详见 `contracts/k8s-secrets.md`。
- `crawler-executor-redis`：提供 `FETCH_QUEUE_REDIS_URL` 与 `REDIS_URL`，分别服务 Redis Streams 队列和 P0 IP health / blacklist；目标集群可让两个 key 指向同一 Redis 连接串。
- `crawler-executor-kafka`：提供 `KAFKA_USERNAME`、`KAFKA_PASSWORD`；Kafka broker、topic、协议和 CA 路径仍属于 ConfigMap。
- `crawler-executor-oci-api-key`：仅 `OCI_AUTH_MODE=api_key` 时挂载 `config` 与 `oci_api_key.pem`；生产优先使用 `instance_principal`，不得把 OCI API key 打入镜像。
- 后续 DaemonSet 模板必须使用显式 `secretKeyRef` / Secret volume 引用，不使用包含真实值的 manifest，不用 `envFrom` 无差别注入 Secret。

### ConfigMap / env

- ConfigMap 契约详见 `contracts/k8s-configmap.md`。
- `crawler-executor-config` 只保存非敏感行为参数，包括 queue、并发、timeout、drain、claim idle、IP 排除列表、P1 持久化、Kafka 非敏感参数、debug 和 pause。
- `FETCH_QUEUE_CONSUMER` 不得作为静态 ConfigMap 值；必须由 Downward API 注入的 `NODE_NAME` / `POD_NAME` 生成。
- `FETCH_QUEUE_REDIS_URL`、`REDIS_URL`、`KAFKA_USERNAME`、`KAFKA_PASSWORD`、OCI API key 和任何 token 不得进入 ConfigMap。

## 资源与并发推导

M3 第一版不把具体 CPU / memory 数值写死在 spec 中，但 plan 必须按以下关系推导：

- `ip_count = len(discovered_local_ip_pool - excluded_ips)`。
- `CONCURRENT_REQUESTS` 第一版仍可按 `min(ip_count * per_ip_concurrency, global_cap)` 推导，但恢复 004 前必须按 ADR-0012 重新审核与 sticky-pool、per-(host, ip) pacer、IP cooldown 和 host slowdown 的关系。
- `CONCURRENT_REQUESTS_PER_DOMAIN` 与 `DOWNLOAD_DELAY` 不再视为生产 politeness 主模型；004 恢复时只能作为 fallback 参数保留。
- CPU / memory requests 必须覆盖目标并发、Kafka producer flush、对象存储上传和 gzip 压缩开销。

## 成功标准

- **SC-001**：两个带 crawler label 的 node 上各运行一个 crawler pod，非 crawler node 不运行 crawler pod。
- **SC-002**：crawler pod 使用 `hostNetwork`，并能发现本 node 的本地出口 IPv4 池；在 50-70 个 IP 假设下不因固定上限失败。
- **SC-003**：多个 DaemonSet pod 常驻消费同一 Redis Stream，发布 `crawl_attempt` 后再 `XACK`。
- **SC-004**：指定 node 的 debug stream 可被指定 pod 消费，debug attempt 携带 `tier=debug`。
- **SC-005**：Kafka / Redis / OCI 短暂不可达不触发 liveness 失败；依赖异常可通过指标观察。
- **SC-006**：滚动或手动删除 pod 时，未完成消息不被清空，后续可由其它 worker reclaim；允许少量重复抓取。
- **SC-007**：敏感凭据不出现在镜像、manifest 明文、仓库文档或 ConfigMap 中。
- **SC-008**：启用 pause flag 后，worker 停止读取新 Fetch Command；关闭后恢复消费。

## 不在 M3 范围

- 不实现第五类事实投影。
- 不实现第三类解析服务或 parse-task 派发。
- 不实现完整控制平面策略运行时下发。
- 不实现本地 outbox / Kafka 故障补偿队列。
- 不承诺生产吞吐压测结果。
- 不做 Terraform / cloud-init 自动化。
- 不实现周期性 NIC rescan；运行期 NIC 变化通过重启 pod 生效。

## 澄清记录

- 2026-04-30：确认 M3 使用 DaemonSet + `hostNetwork` + 每 node 单 pod。
- 2026-04-30：确认每个 node 暂按 50-70 个本地出口 IPv4 上限设计。
- 2026-04-30：确认关停语义选择 B：低频手动滚动、任务幂等、允许少量重复抓取，未完成 in-flight 留 PEL 后续 reclaim。
- 2026-04-30：确认 liveness 只检查进程 / reactor / metrics endpoint 基本存活；Kafka / Redis / OCI 短暂不可达只进指标和告警，不作为 liveness / readiness 单次失败条件。
- 2026-04-30：确认 debug stream 产生的 `crawl_attempt` 仍发正式 topic，但必须携带 `tier=debug` 供第五类过滤或标记。
- 2026-04-30：确认 debug 命名规则：`crawl:tasks:debug:<node_name>`、`crawler-executor-debug:<node_name>`、`${NODE_NAME}-${POD_NAME}-debug`。
- 2026-04-30：确认暂不推进 manifest 实现，先完成 004 spec 草案评审。
