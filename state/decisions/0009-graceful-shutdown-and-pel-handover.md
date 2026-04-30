# ADR-0009: 优雅停机与 PEL 移交语义

**状态**：已接受
**日期**：2026-04-30

## 背景

003 阶段的 spec FR-015 / FR-016 与 ADR-0006 已确立 "`crawl_attempt` 发布成功后再 `XACK`、可重试失败留 PEL" 的不变量。tasks.md T015c 进一步要求实现 "SIGTERM 停止读取新消息但不清空 PEL"。

实施过程中识别到，仅有一句 "停止读取新消息、不清空 PEL" 不足以约束实现：触发信号集合、停机期间的 `XAUTOCLAIM` 行为、drain 时限、与 Scrapy 自身关停的协同、阻塞读的处理、停机期间的失败分支语义都需要明确。否则在 M3（K8s DaemonSet + hostNetwork）阶段，`terminationGracePeriodSeconds`、滚动更新与 PEL 长度告警等约束没有可对齐的执行层语义，容易引入回归。

本 ADR 把上述语义沉淀为跨 feature 持续生效的不变量，与 ADR-0006 / ADR-0008 协同形成 "启动 → 运行 → 退出" 全生命周期的 ack 与 PEL 行为约束。

## 决策

1. **触发信号集合**：crawler-executor 把 SIGTERM 与 SIGINT 视为同语义优雅停机信号，触发 "停止读取新消息、允许 in-flight 完成、不清空 PEL" 的退出路径。SIGHUP / SIGQUIT 不纳入本路径，沿用进程默认行为。重复信号（SIGTERM/SIGINT 第二次到达）不强制立即退出，仍由 Scrapy 自身关停流程或 drain 时限兜底。

2. **不接管 Scrapy 自身关停**：crawler-executor 不注册自定义 `signal.signal()` handler 去覆盖 Scrapy engine 的关停行为。优雅停机以 "共享停机标志" 的方式实现：spider 的消费循环在每次迭代前检查标志，命中则退出循环；具体停机推进仍由 Scrapy engine 的关停流程负责。

3. **停机期间禁止接管 PEL**：进入停机状态后，consumer 不得再发起 `XAUTOCLAIM`，即不再为本进程接管别的 consumer 的 pending 消息。本进程已经在 PEL 中、尚未 ack 的消息保持留存，由其它存活 worker 在合适时机通过 `XAUTOCLAIM` 接管。

4. **In-flight 与 drain 时限**：已经从 `XREADGROUP` 拉到、并交给 Scrapy engine 的 request 允许完成。Drain 时限缺省 25 秒，通过 `FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS` 暴露，留出 K8s 默认 30 秒 grace period 的安全边距。drain 超时后，未完成的 in-flight 请求按 "未发布 attempt" 处理：不 `XACK`，由 Streams 协议在后续 `XAUTOCLAIM` 周期中接管。

5. **阻塞中的 `XREADGROUP`**：若停机信号在 `XREADGROUP` 阻塞窗口内到达，允许等待至多一个 `block_ms` 周期（缺省 5 秒）自然返回，不引入额外的 socket 中断逻辑。本周期内拉到的消息按 §6 规则处理。

6. **停机期间失败分支不变量**：
   - 已开始的 fetch 终态失败（达到 `max_deliveries` 上限）仍按 ADR-0006 发布终态 `crawl_attempt` 后 `XACK`。
   - Kafka 不可达分支仍按 ADR-0008 处理：不 `XACK`、留 PEL、不递增投递计数。
   - 不在退出前主动重新 `XAUTOCLAIM` 以 "赶在退出前发完"。

7. **可观测性最低集合**：
   - 收到停机信号时记录一条结构化日志 `fetch_queue_shutdown_signal_received`，包含信号名。
   - 退出前记录一条总结日志，至少包含本进程 acked 数、本进程留在 PEL 的 in-flight 数、drain 是否超时。
   - Prometheus 至少新增一个事件计数：`fetch_queue_event="shutdown"`。

## 备选方案

- **自行注册 signal handler 接管 Scrapy 关停**：不采纳。会与 Scrapy engine 关停流程并发，既复杂化退出路径，也可能阻断 Scrapy 自身的 reactor 关停顺序。
- **停机后仍允许 `XAUTOCLAIM`**：不采纳。让正在退出的 worker 接管别的 worker 的 PEL 是反直觉的，且增加 drain 时间不确定性。
- **drain 时限 = 0（立即退出，不等 in-flight）**：不采纳。会扩大 "已请求未发布 attempt" 的窗口，增加重复抓取与下游幂等压力。
- **drain 时限 ≥ K8s 默认 grace period（≥30 秒）**：不采纳。会与 K8s 默认 grace period 直接撞线，运行时被 SIGKILL 强杀，反而失去优雅停机意义。25 秒留 5 秒安全边距。
- **退出前主动 `XAUTOCLAIM` 处理 PEL**：不采纳。违反 ADR-0006 "PEL 恢复是 `XAUTOCLAIM` 的职责" 原则。
- **停机覆盖 SIGHUP / SIGQUIT**：暂不采纳。本仓库当前不依赖 SIGHUP 重载配置；SIGQUIT 通常用于 core dump 调试，不应触发优雅停机。后续若引入运行时配置重载或调试约定，再单独 ADR。

## 后果

- **好处**：M3（K8s DaemonSet + hostNetwork）阶段 `terminationGracePeriodSeconds=30` 与本仓库 25 秒 drain 时限对齐，滚动更新行为可预测。
- **好处**：退出路径与 ADR-0006 / ADR-0008 的不变量在所有路径下保持一致。
- **好处**：实现侵入面收敛在 spider 消费循环与 consumer 状态切换两处，便于回归测试。
- **代价**：若 in-flight 请求长尾超过 25 秒，相关消息会被 Streams 协议在停机后通过 `XAUTOCLAIM` 重投，依赖 attempt 幂等（ADR-0007）与对象存储覆盖语义兜底。
- **代价**：Kafka 长时间故障下停机仍会让 PEL 增长（与 ADR-0008 一致），需要运维侧 Kafka 健康度告警与紧急停抓 SOP 兜底。
- **后续**：若引入本地 outbox / Kafka 故障补偿队列，需要重新审视本 ADR 与 ADR-0008 的协同。

## 关联

- ADR-0006
- ADR-0008
- `specs/003-p2-readonly-scheduler-queue/spec.md` FR-015 / FR-016 / FR-017 / FR-022
- `specs/003-p2-readonly-scheduler-queue/research.md` §5
- `state/roadmap.md` M3 K8s DaemonSet + hostNetwork
