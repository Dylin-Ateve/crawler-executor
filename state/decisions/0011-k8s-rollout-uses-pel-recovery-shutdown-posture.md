# ADR-0011: K8s 低频滚动采用 PEL 可恢复的关停姿态

**状态**：已接受  
**日期**：2026-04-30

## 背景

ADR-0009 定义了优雅停机与 PEL 移交语义，目标是收到 SIGTERM / SIGINT 后停止读取新消息、不清空 PEL，并在 drain 时限内退出。目标节点执行 `run-p2-graceful-shutdown-validation.sh` 时发现：Scrapy engine 收到 SIGTERM 后会进入自身 shutdown 流程，但 in-flight 下载可能继续等待 `DOWNLOAD_TIMEOUT`、retry 与 engine 关停过程，总耗时可超过脚本设置的短 drain 时限。

目标节点观测到：

- SIGTERM 后 worker 退出耗时 68 秒，超过 `FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS=8` + 5 秒容差。
- PEL 保持 `count=1`、stream `xlen=1`，说明消息未被清空且可恢复。
- 同一 `stream_message_id` 出现重复响应日志，说明退出期间仍可能发生重复处理。

团队确认当前 K8s 场景为低频手动滚动、Fetch Command / `attempt_id` 幂等、允许少量重复抓取。M3 第一版目标是生产部署基础，而不是高频自动滚动或严格无重复摘流。

## 决策

M3 K8s DaemonSet 部署第一版采用 **PEL 可恢复的关停姿态**：

- 滚动更新低频、手动、可观察，第一版优先 `OnDelete` 更新策略。
- 允许少量重复抓取，依赖 `job_id + canonical_url` 生成的确定性 `attempt_id` 和下游幂等去重兜底。
- SIGTERM / SIGINT 后的最低可靠性目标是：不主动清空 PEL；已 `XACK` 的消息必须已有成功发布的 `crawl_attempt`；未完成或发布失败消息留 PEL，后续由其它 worker `XAUTOCLAIM` 接管。
- `FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS` 在 M3 第一版中作为退出总结和观测窗口，不承诺强制让 Scrapy engine 在该时限内终止所有 in-flight 下载。
- `terminationGracePeriodSeconds` 与 `FETCH_QUEUE_CLAIM_MIN_IDLE_MS` 必须按公式协同，避免退出中的 worker 在 grace 窗口内自 reclaim 或过早接管别的 worker 的 PEL。
- 若未来滚动更新频率提高、重复抓取不可接受，或需要严格摘流语义，必须重新收口 ADR-0009 的严格实现：更早设置 shutdown flag、停止 `XREADGROUP` / `XAUTOCLAIM`，并明确是否主动取消 in-flight 或收缩 download timeout。

## 运行参数约束

M3 plan 必须给出以下推导，而不是拍固定值：

```text
FETCH_QUEUE_CLAIM_MIN_IDLE_MS >= terminationGracePeriodSeconds * 1000 + safety_margin_ms
```

第一版建议：

- `FETCH_QUEUE_BLOCK_MS=1000`，降低空队列阻塞读对 SIGTERM 响应的影响。
- `updateStrategy=OnDelete`，避免自动滚动扩大重复抓取窗口。
- `terminationGracePeriodSeconds` 由 `DOWNLOAD_TIMEOUT`、Kafka flush timeout、对象存储上传和目标集群运维容忍度共同决定。

## 备选方案

- **严格 drain 完成后再退出**：不作为 M3 第一版。它需要重新收口当前 T015c 实现，并要求 `drain >= DOWNLOAD_TIMEOUT + publish/ack buffer`，会拉长低频滚动耗时。
- **SIGTERM 后主动取消 in-flight / 缩短 download timeout**：不采纳为第一版。会改变 Scrapy 失败语义，可能产生大量人为 fetch failed attempt。
- **继续沿用 ADR-0009 字面严格退出语义但不改实现**：不采纳。目标节点验证已证明该口径与真实行为不一致。

## 后果

- **好处**：M3 可以在已验证的 P2 ack / PEL / attempt 幂等基础上推进 K8s 部署基础，不被严格摘流实现阻塞。
- **好处**：低频手动滚动场景下运维行为更可控，且重复抓取风险可通过 debug / PEL / attempt 指标观测。
- **代价**：滚动期间可能出现少量重复抓取。
- **代价**：不适合高频自动滚动或严格无重复抓取场景。
- **后续**：严格优雅停机仍由 `specs/003-p2-readonly-scheduler-queue/tasks.md` 的 T015c-9 / T015c-10 跟踪。

## 关联

- ADR-0006
- ADR-0007
- ADR-0008
- ADR-0009
- `specs/003-p2-readonly-scheduler-queue/`
- `specs/004-p3-k8s-daemonset-hostnetwork/`
