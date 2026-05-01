# 实施计划：P3 K8s DaemonSet + hostNetwork 生产部署基础

**分支**：`004-p3-k8s-daemonset-hostnetwork`  
**日期**：2026-04-30  
**规格文档**：`specs/004-p3-k8s-daemonset-hostnetwork/spec.md`

## 摘要

004 将 crawler-executor 从目标节点脚本验证推进到 K8s 节点级常驻部署基础。M3 采用专用 crawler node pool、DaemonSet、`hostNetwork: true`、每 node 单 pod 的形态，使每个 pod 能使用宿主机 50-70 个本地出口 IPv4 进行抓取，并继续只读消费第六类 Redis Streams Fetch Command。

M3 第一版不追求完整生产规模调优，也不进入第五类事实投影、第三类解析或完整控制平面。重点是部署形态、配置注入、节点隔离、探针、指标、debug stream 和最小紧急停抓入口。

## 技术上下文

**语言/版本**：Python 3.9+  
**主要依赖**：Scrapy、Redis / Valkey client、Kafka client、OCI SDK、Prometheus client、K8s  
**存储**：OCI Object Storage；Redis / Valkey 作为队列载体；Kafka 作为事件总线  
**测试**：pytest、K8s manifest dry-run、目标集群 DaemonSet 验证脚本  
**目标平台**：K8s crawler node pool；Linux node；`hostNetwork`  
**项目类型**：抓取执行数据管道  
**性能目标**：本阶段不承诺 30-50 pages/sec 单节点稳定吞吐；只验证节点级常驻消费与可运维部署基础  
**约束**：每个 crawler node 默认一个 pod；不在同 node 运行多个 crawler pod 争抢 IP 池；只读消费 Redis Streams；不写 URL 队列；debug attempt 必须 `tier=debug`  
**规模/范围**：少量 crawler node 灰度，节点 IP 池按 50-70 个本地出口 IPv4 设计

## 门禁检查

| 门禁 | 来源 | 结果 | 说明 |
|---|---|---|---|
| 章程门禁 | `.specify/memory/constitution.md` | 通过 | 先定义 M3 部署规格、探针口径和验证标准，再进入 manifest 实现。 |
| 产品门禁 | `.specify/memory/product.md` | 通过 | 仍聚焦第二类抓取执行，不引入 URL 选择、解析、质量评价或事实层。 |
| 架构门禁 | `.specify/memory/architecture.md` | 通过 | 符合 DaemonSet / hostNetwork / 指标端口 / Secret 注入的终态方向。 |
| 决策门禁 | `state/decisions/` | 通过 | 遵守 ADR-0003、ADR-0004、ADR-0006、ADR-0008、ADR-0009、ADR-0010、ADR-0011。 |
| 路线图对齐 | `state/roadmap.md` | 记录 | 对应 M3：生产部署基础。 |

## 项目结构

### 文档

```text
specs/004-p3-k8s-daemonset-hostnetwork/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### 预期源码 / 部署结构

```text
src/crawler/crawler/
├── health.py              # readiness / liveness / dependency metrics 扩展
├── ip_pool.py             # hostNetwork IPv4 扫描与 50-70 IP 验证
├── metrics.py             # consumer heartbeat / dependency health 指标
├── settings.py            # K8s / pause / debug / probe 配置
└── spiders/fetch_queue.py # pause flag / consumer name / debug 上下文复用

deploy/
├── k8s/                   # M3 manifest / kustomize 或等价部署模板
└── scripts/               # M3 目标集群验证脚本

tests/
├── unit/
└── integration/
```

**结构决策**：M3 可以新增 `deploy/k8s/`，但不得把真实凭据写入 manifest；Secret 只提供模板或引用名。

当前第一版模板位于 `deploy/k8s/base/`：

- `configmap.yaml`：非敏感运行参数。
- `daemonset.yaml`：DaemonSet + `hostNetwork` + `ClusterFirstWithHostNet` + `RollingUpdate maxUnavailable=1` + 探针 + Prometheus annotation。
- `secrets.example.yaml`：仅展示 Secret 名称和 key，禁止替换为真实值后提交。

## 关键设计约束

### 关停参数公式

M3 采用 ADR-0011 的 PEL 可恢复姿态。

```text
FETCH_QUEUE_CLAIM_MIN_IDLE_MS >= terminationGracePeriodSeconds * 1000 + safety_margin_ms
```

plan 阶段建议默认：

- `FETCH_QUEUE_BLOCK_MS=1000`
- `terminationGracePeriodSeconds=30`
- `safety_margin_ms=30000`
- `FETCH_QUEUE_CLAIM_MIN_IDLE_MS=60000`
- `updateStrategy=RollingUpdate`
- `rollingUpdate.maxUnavailable=1`
- 不承诺 `FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS` 强制终止 Scrapy in-flight
- 该默认值服务低频手动滚动，保证 grace 窗口内不抢占退出中 pod 的 PEL；它不承诺覆盖所有长下载、对象存储上传或 Kafka flush 时长，M3 通过 `attempt_id` 幂等接受少量重复抓取

`FETCH_QUEUE_BLOCK_MS=1000` 的运行含义：

- 空队列时，SIGTERM / SIGINT 到达后，阻塞中的 `XREADGROUP` 最多等待约 1 秒自然返回。
- 代价是 Redis 空轮询频率高于 `5000ms` 口径；M3 接受该开销以换取低频手动滚动和精确调试时更快的反馈。
- 禁止永久阻塞；如目标集群把该值调高，必须显式记录新的停机响应延迟上限。

### 探针口径

- liveness：进程 / reactor / metrics endpoint 基本存活。
- readiness：worker 初始化完成、消费循环有心跳；不因 Kafka / Redis / OCI 单次抖动失败。
- 依赖健康：通过 Prometheus 指标和告警表达。

### Debug 事件边界

- debug stream 与 production stream 隔离。
- debug 命名规则详见 `contracts/debug-routing.md`：`crawl:tasks:debug:<node_name>`、`crawler-executor-debug:<node_name>`、`${NODE_NAME}-${POD_NAME}-debug`。
- debug `crawl_attempt` 仍进入正式 topic。
- Fetch Command 必须携带 `tier=debug`，并使用可识别 `job_id` / `trace_id`。

## 复杂度跟踪

| 例外项 | 必要原因 | 未采纳更简单方案的原因 |
|---|---|---|
| DaemonSet + hostNetwork | 节点本地辅助 IP 是 node 级资源，pod 必须能 bind 宿主机 IP | Deployment 无法天然保证每 node 一个 pod，容易多个 pod 争抢同一 IP 池 |
| RollingUpdate 更新策略 | staging / production 操作流程统一，支持 `kubectl rollout status` 观察更新；`maxUnavailable=1` 控制滚动窗口 | 自动滚动期间仍可能出现少量重复抓取，需要继续依赖 PEL 与下游幂等 |
| liveness 不检查外部依赖 | 避免 Kafka / Redis / OCI 短暂抖动触发错误重启 | 把依赖放入 liveness 会制造雪崩重启风险 |
| debug attempt 走正式 topic + `tier=debug` | 保持端到端真实链路，验证对象存储 / Kafka / 下游过滤 | 独立 topic 或禁用持久化会降低调试链路真实性 |
| 启动时扫描 IP 池 | 50-70 IP / node 显式配置成本高，扫描更贴合真实网卡状态；运行期 NIC 变化通过重启 pod 生效 | 每 node ConfigMap 可控但维护成本高且易漂移；周期性 rescan 会引入并发修改 IP 池的复杂度 |
| 应用层 pause flag | DaemonSet 不支持 replicas scale-to-zero，删除 DaemonSet 过于破坏性 | 通过 nodeSelector 驱逐 pod 适合下线，不适合作常规紧急停抓 |

## 后续计划约束

进入实现前必须补齐：

- 具体 manifest 目录和模板方式。
- health endpoint 或 metrics endpoint 的实现路径。
- pause flag 的配置来源和验证方式。

Secret 引用名和 key 已在 `contracts/k8s-secrets.md` 中定义；manifest 阶段必须按该契约使用显式 `secretKeyRef` / Secret volume，不提交真实值。
ConfigMap key、默认建议和禁止项已在 `contracts/k8s-configmap.md` 中定义；manifest 阶段必须按该契约创建 `crawler-executor-config`。
Debug stream / group / consumer 命名已在 `contracts/debug-routing.md` 中定义；T030 阶段实现切换逻辑。
