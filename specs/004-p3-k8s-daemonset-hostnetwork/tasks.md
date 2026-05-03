# 任务：P3 K8s DaemonSet + hostNetwork 生产部署基础

**输入**：`spec.md`、`plan.md`、`research.md`、`data-model.md`  
**前置条件**：P2 Redis Streams 队列消费目标节点验证通过；ADR-0013 已接受；具备至少 1-2 台 crawler 测试 node。
**当前状态**：已完成。2026-05-03 起，005 已完成本地实现与 staging OKE 等价镜像环境验证，004 从暂停现场恢复并完成 staging 关闭验证；production 复刻进入后续发布流程。

## 暂停与恢复现场

- OKE node pool：`scrapy-node-pool`。
- subnet：`subnetCollection`。
- node 数量：2。
- node label：`scrapy-egress=true` 已确认存在。
- taint：暂未配置，符合第一轮实测策略。
- host interface：`enp0s5`。
- staging 每 node IPv4 数量：5，按 `M3_IP_POOL_EXPECTED_RANGE=5-5` 验证；production profile 仍按 `60-70` 验证。
- Redis / Kafka：staging 已验证 Kafka broker TCP 9092、容器 CA 路径和最小 producer smoke；Redis Stream PEL 已清空。
- namespace：`crawler-executor`。
- Secret：`crawler-executor-redis` 与 `crawler-executor-kafka` 已创建，预期 key 均存在。
- ConfigMap / DaemonSet：staging 已 apply 并通过 M3 K8s DaemonSet 审计。

## 阶段 1：规格与部署决策

- [x] T001 创建 004 M3 规格草案。
- [x] T002 确认部署形态：专用 crawler node pool + DaemonSet + `hostNetwork: true` + 每 node 单 pod。
- [x] T003 确认关停语义 B：低频手动滚动、任务幂等、允许少量重复抓取、未完成 in-flight 留 PEL。
- [x] T004 确认健康检查口径：liveness 不包含 Kafka / Redis / OCI 短暂依赖故障。
- [x] T005 确认 debug attempt 事件边界：正式 topic + `tier=debug`。
- [x] T006 新增 ADR-0011，记录 K8s 低频滚动的 PEL 可恢复关停姿态。
- [x] T006a 新增 ADR-0013，替代 ADR-0011 的 OnDelete 方案，确认 DaemonSet 使用 `RollingUpdate maxUnavailable=1`。

## 阶段 2：配置模型与运行参数

- [x] T007 定义 K8s Secret 字段清单与引用名，禁止真实凭据入库。
- [x] T008 定义 ConfigMap 字段清单：queue、consumer、并发、timeout、claim idle、drain、IP 排除列表、debug、pause。
- [x] T009 实现或整理 `FETCH_QUEUE_CONSUMER` 模板：`${NODE_NAME}-${POD_NAME}`。
- [x] T010 公式化 `FETCH_QUEUE_CLAIM_MIN_IDLE_MS`，覆盖 K8s termination grace、005 delayed buffer、下载重试和 Kafka delivery timeout，并在示例配置中体现。
- [x] T011 定义 M3 默认 `FETCH_QUEUE_BLOCK_MS=1000`，说明 SIGTERM 响应延迟与 Redis 轮询频率取舍。
- [x] T012 定义 debug stream / group / consumer 命名规则。

## 阶段 3：节点级 IP 池适配

- [x] T013 增加 `ip_pool.py` hostNetwork pod IPv4 发现验证脚本与 quickstart 步骤。
- [x] T014 增加 50-70 个本地出口 IPv4 的 IP 池规模验证脚本或诊断命令。
- [x] T015 明确 `CRAWL_INTERFACE` 语义：M3 生产第一版默认 `enp0s5`，`all` / 具体 interface / `LOCAL_IP_POOL` 仅作诊断、调试或回退。
- [x] T016 验证 `EXCLUDED_LOCAL_IPS` 能排除保留 / 禁用 IP。
- [x] T017 记录运行期 NIC 变化策略：重启 pod 重新扫描，M3 不做周期 rescan。

## 阶段 4：健康检查与指标

- [x] T018 定义 liveness endpoint：进程 / reactor / metrics endpoint 基本存活。
- [x] T019 定义 readiness endpoint：worker 初始化完成、消费循环最近心跳；不因外部依赖单次抖动失败。
- [x] T020 增加 consumer heartbeat 指标或复用现有指标暴露最近循环时间。
- [x] T021 增加 Redis / Kafka / OCI 依赖健康指标，不接入 liveness fail。
- [x] T022 编写探针验证脚本：模拟 Kafka / Redis / OCI 短暂异常，确认不触发 liveness 错误失败。

## 阶段 5：K8s 部署模板

- [x] T023 创建 `deploy/k8s/` 目录结构。
- [x] T024 创建 DaemonSet 模板，包含 `hostNetwork: true`、`dnsPolicy: ClusterFirstWithHostNet`、nodeSelector、tolerations、Prometheus 端口。
- [x] T025 设置 updateStrategy 为 `RollingUpdate maxUnavailable=1`。
- [x] T026 创建 ConfigMap 模板，不包含敏感值。
- [x] T027 创建 Secret 引用模板，仅提供 key 名称和引用方式，不提交真实 secret。
- [x] T028 定义 resource requests / limits 初始建议，并说明与 IP 池和并发的关系。
- [x] T029 定义 ServiceMonitor / PodMonitor 或等价 Prometheus 抓取模板。

## 阶段 6：调试与停抓

- [x] T030 实现或配置 debug stream 切换方式，支持指定 node / pod 消费 `crawl:tasks:debug:<node_name>`。
- [x] T031 编写 debug Fetch Command 写入脚本，强制携带 `tier=debug`、可识别 `job_id` / `trace_id`。
- [ ] T032 验证 debug attempt 发布到正式 topic 且保留 `tier=debug`（脚本与配置已准备，需目标 Kafka 环境验证）。
- [x] T033 定义最小 pause flag，启用后 worker 停止读新消息但不删除 DaemonSet。
- [ ] T034 验证 pause flag 开启 / 关闭的消费行为和 PEL 行为（本地脚本已覆盖 env + pause file；K8s 通过 ConfigMap volume 文件动态生效，需目标 Redis / 集群执行）。

## 阶段 7：目标集群验证

- [x] T035a 记录目标集群第一轮资源现场：`scrapy-node-pool`、`subnetCollection`、`scrapy-egress=true`、`enp0s5`、每 node 约 65 个 IPv4、namespace 与 Redis/Kafka Secret。
- [x] T035b 恢复 004 前，完成新 spec 对生产功能性缺口的补齐与评审：005 已完成本地实现与 staging OKE 等价镜像环境验证。
- [x] T035 在至少 1 个 crawler node 上部署 DaemonSet，验证 pod 使用 hostNetwork 并发现 IP 池：staging 审计通过，`enp0s5` 发现 5 个 IPv4。
- [x] T036 在至少 2 个 crawler node 上部署 DaemonSet，验证每 node 一个 pod：staging 审计通过，2 个 `scrapy-egress=true` node 各 1 个 Running pod。
- [x] T037 向生产测试 stream 写入 Fetch Command，验证多个 pod 常驻消费并发布 `crawl_attempt` 后 `XACK`；staging T037 v3 两条 HTML smoke 均 `storage_result=stored`，最终 PEL `pending=0`。
- [x] T037a 修复 staging T037 暴露的 reactor 阻塞风险：`FetchQueueSpider.start()` 不再在 async loop 中同步执行 Redis `ensure_group` / `XREADGROUP`，改为线程 offload；本地相关单元测试通过。
- [x] T037b 使用包含 T037a 修复的新镜像重新执行 staging T037，确认 response/errback、`crawl_attempt` 发布和 PEL 清空。
- [x] T038 手动删除单个 pod，验证未完成消息留 PEL 且后续可 reclaim；staging 临时 `FETCH_QUEUE_CLAIM_MIN_IDLE_MS=5000` 触发接管，消息最终发布并 `XACK`，PEL `pending=0`；重复 publish 符合当前少量重复抓取假设。
- [x] T039 验证 Kafka / Redis / OCI 短暂依赖异常进入指标和告警，而不触发 liveness 雪崩；staging 已观察 Kafka 依赖异常进入指标且 liveness/readiness 保持 OK，Redis/OCI 本轮完成正向 smoke，破坏性 Redis/OCI 故障注入留给 production 运维验证。
- [x] T040 验证指定 node 的 debug stream 路由与 `tier=debug` 事件边界；staging 临时 `CRAWLER_DEBUG_MODE=true` 后解析为 `crawl:tasks:debug:<node>` / `crawler-executor-debug:<node>` / `${NODE_NAME}-${POD_NAME}-debug`，debug HTML smoke 发布 `storage_result=stored`，debug PEL `pending=0`。
- [x] T041 验证 pause flag 能停止读取新消息并可恢复；staging ConfigMap volume 传播脚本通过，严格 pause 测试中 paused 阶段不消费且 PEL `pending=0`，恢复后 HTML smoke 发布 `storage_result=stored` 并回到 `pending=0`。
- [x] T041a 补 Object Storage 内容写入权限验证；staging `p1_object_storage_smoke_ok`，HTML smoke 多次 `storage_result=stored`。

## 阶段 8：文档收口

- [x] T042 更新 `quickstart.md` 的目标集群部署和验证记录。
- [x] T043 更新 `state/current.md`、`state/roadmap.md`、`state/changelog.md`。
- [x] T044 若 M3 实现发现需要改变 ADR-0011 或 ADR-0009，先新增 / 修订 ADR，再更新 plan：ADR-0013 已接受并替代 ADR-0011 的默认 rollout 策略。

## 依赖与执行顺序

- 阶段 1 阻塞后续所有阶段。
- 阶段 2 阻塞阶段 5。
- 阶段 3 可与阶段 4 并行。
- 阶段 4 阻塞阶段 7 的探针验证。
- 阶段 5 阻塞阶段 7。
- 阶段 6 可与阶段 5 并行，但目标集群验证前必须完成。
- 阶段 8 是 M3 退出评审。
