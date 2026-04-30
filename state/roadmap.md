# 演进路线图：crawler-executor

**更新日期**：2026-04-30
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
- **状态**：目标节点已验证；优雅停机语义（ADR-0009 / FR-022）已落地实现，目标节点端到端脚本待执行。
- **依赖 ADR**：ADR-0003、ADR-0004、ADR-0005、ADR-0006、ADR-0007、ADR-0008、ADR-0009。
- **对应 spec**：`specs/003-p2-readonly-scheduler-queue/`
- **验收信号**：多个 worker 可通过 `XREADGROUP` 消费第六类 `XADD` 的抓取指令；本系统无 Redis URL 写入行为；同一 `job_id + canonical_url` 重复投递生成相同 `attempt_id`；`crawl_attempt` 发布成功后 `XACK`；Kafka failure 下消息留 PEL 并可由 `XAUTOCLAIM` 接管，Kafka 恢复后发布并 ack；SIGTERM / SIGINT 触发优雅停机后停止 `XREADGROUP` 与 `XAUTOCLAIM`、in-flight 完成后 ack 或留 PEL、不主动清空 PEL。只读边界脚本已覆盖 key diff 与目标 stream `XLEN` 前后不变，更宽 audit pattern 可继续补强。

### M3：生产部署基础

- **目标**：K8s DaemonSet + hostNetwork、健康探针、指标端口、配置注入和节点隔离。
- **状态**：未开始。
- **对应 spec**：待新建。
- **验收信号**：节点扩缩容时 worker 自动跟随；readiness 能反映对象存储 / Kafka / Redis 关键依赖异常。

### M4：控制平面策略运行时覆盖

- **目标**：Politeness、Tier、Site、HostGroup、紧急停抓等策略从控制平面下发并覆盖本地默认值。
- **状态**：未开始。
- **对应 spec**：待新建。
- **验收信号**：策略变更不需要重启 worker；停抓指令能在约定时间内生效；审计事件回流第五类。

### M5：JS 渲染与现代反爬补齐

- **目标**：在第二类内部扩展渲染型抓取能力，不新建平行执行系统。
- **状态**：后置。
- **对应 spec**：待规划。
- **验收信号**：渲染任务与普通 fetch 共享 `crawl_attempt` 事件语义；不会把解析或内容质量职责带回执行层。

## 2. 跨阶段债务

| 编号 | 债务 | 当前处理 | 回填触发条件 |
|---|---|---|---|
| D-DEBT-1 | URL 归一化库 Python 实现先由本系统持有 | 当前保留在 `src/crawler/crawler/contracts/canonical_url.py` | 契约仓库提供官方 Python 实现和共享黄金测试集 |
| D-DEBT-2 | 事件 topic 与 schema 暂在本仓库 | 当前位于 `specs/002-p1-content-persistence/contracts/` | 系统群契约仓库建成并接管事件 schema |
| D-DEBT-3 | Politeness 参数仍以内嵌默认值为主 | 当前由 Scrapy settings 承载 | 控制平面策略下发链路可用 |
| D-DEBT-4 | `content_sha256` 只覆盖 HTML 快照场景 | 当前仅在 `storage_result=stored` 时计算 | 上层架构要求所有响应统一 Raw 指纹 |
| D-DEP-1 | host×ip 黑名单事实/缓存边界待第五类契约 | 当前以本系统本地短窗口判断为准 | 第五类发布画像事实与执行缓存切分契约 |

## 3. 未完成关键生产能力

1. Redis 只读边界审计补强：在现有 key diff + `XLEN` 前后对比之外，增加允许状态变化清单和更宽 audit pattern。
2. K8s DaemonSet + hostNetwork 部署。
3. Grafana 基础看板、告警和运维 SOP。
4. 24 小时稳定性压测、30-50 pages/sec 单节点目标验证。
5. 控制平面策略运行时覆盖。
6. 本地出站事件缓冲和 Kafka 故障补偿。

## 4. 明确后置或暂不规划

| 能力 | 当前决策 |
|---|---|
| ClickHouse Host profile | 归第五类，后置且不在本仓库实现。 |
| PostgreSQL `crawl_logs` / `page_snapshots` / `pages_latest` | 归第五类消费端投影，不在本仓库实现。 |
| `parse-tasks` topic 和下游解析服务 | 取消派发模式；第三类直接订阅 `crawl_attempt`。 |
| DLQ 专用 topic | 后置；P1 先用日志和指标覆盖发布失败。 |
| 本地 outbox / Kafka 故障补偿队列 | 后置；当前接受 Kafka 失败日志与对象保留。 |
| Terraform / cloud-init 辅助 IP 与 EIP 自动化 | 暂不规划，规模化时再评估。 |
| Heritrix 数据迁移与旧服务下线 | 后置，待 Scrapy 生产链路稳定后再评估。 |

## 5. 下一阶段建议

003 已完成目标节点验证，T015c 优雅停机语义（ADR-0009 / FR-022）已落地。`run-p2-graceful-shutdown-validation.sh` 待目标节点执行后即可作为 003 完整收尾。

下一步建议进入 M3 生产部署基础：K8s DaemonSet + hostNetwork、配置注入、健康探针和指标端口收口。M3 spec 需要把 `terminationGracePeriodSeconds`、`preStop` 与 ADR-0009 25 秒 drain 时限对齐作为入口约束。

D-DEBT-5（只读边界 audit pattern 加宽）按现状层债务跟进，不阻塞 M3 启动。

若团队决定由本仓库临时维护某个消费端验证工具，必须先通过 ADR 说明其临时性质、退出条件和不进入第二类终态边界的原因。
