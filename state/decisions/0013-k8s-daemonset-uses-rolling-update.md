# ADR-0013: K8s DaemonSet 使用 RollingUpdate

**状态**：已接受  
**日期**：2026-05-01

## 背景

ADR-0011 在 M3 第一版中选择 `OnDelete`，主要为了低频手动滚动、逐点排障和控制重复抓取窗口。spec005 staging 验证推进后，实际操作中需要频繁更新 ConfigMap、镜像和运行参数；`OnDelete` 会要求人工删除 Pod，容易造成操作步骤与 production / staging 等价镜像约束不一致，也不利于使用 `kubectl rollout status` 建立统一验证习惯。

当前 ack 语义仍由 ADR-0006、ADR-0008、ADR-0009 约束：只有 `crawl_attempt` 发布成功后才 `XACK`，发布失败或停机未完成的消息留在 Redis Streams PEL 中等待恢复。因此从 `OnDelete` 切换到受控 `RollingUpdate` 不改变消息可靠性边界，但会让更新动作更标准化。

## 决策

M3 / M3a K8s DaemonSet 使用 `RollingUpdate`：

- `updateStrategy.type=RollingUpdate`。
- `rollingUpdate.maxUnavailable=1`。
- 更新镜像、ConfigMap 或 template 后，通过 `kubectl rollout status daemonset/<name>` 观察滚动进度。
- production 与 staging 使用同一更新策略和同一操作流程。
- PEL 可恢复、`crawl_attempt` 发布后 ack、Kafka 发布失败不 ack 的语义继续沿用 ADR-0006、ADR-0008、ADR-0009。

## 备选方案

- 继续使用 `OnDelete`：不采纳。它要求人工删除 Pod，不利于 staging 复刻 production 验证步骤，也容易在频繁验证时遗漏重建动作。
- `RollingUpdate maxUnavailable` 大于 1：不采纳。当前每个节点承载本地出口 IP 池，过大的不可用窗口会降低验证稳定性，并扩大重复抓取和 PEL 接管窗口。

## 后果

- **好处**：镜像和 template 更新可以用 Kubernetes 原生 rollout 流程观察，staging / production 操作习惯保持一致。
- **好处**：减少手工删除 Pod 带来的漏操作和误操作。
- **代价**：滚动期间仍可能存在少量重复抓取或未完成消息留 PEL，需要继续依赖现有 PEL / `attempt_id` / 下游幂等语义。
- **后续**：如未来需要严格摘流或零重复抓取，需要另行收口停机与 in-flight 取消策略。

## 关联

- ADR-0006
- ADR-0008
- ADR-0009
- ADR-0011
- `specs/004-p3-k8s-daemonset-hostnetwork/`
- `specs/005-m3a-adaptive-politeness-egress-concurrency/`
