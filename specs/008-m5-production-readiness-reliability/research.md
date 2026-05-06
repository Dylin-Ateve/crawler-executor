# 研究记录：M5 生产就绪与可靠性补偿

**日期**：2026-05-04  
**范围**：production 复刻、专项停机、Kafka outbox / 故障补偿、发布 / 回滚 SOP。

## 1. production 复刻策略

### 决策

production 首次验证采用 staging 同形态流程：跳板机加载环境、渲染配置、审计、DaemonSet apply、rollout、debug stream smoke、指标 / 日志 / PEL 验证、恢复配置。

### 理由

staging 已被定义为 production 功能验证等价镜像环境。production 复刻的主要风险不是代码路径，而是 Secret、endpoint、node label、网络、Object Storage 权限、Kafka ACL、Redis prefix 和 ConfigMap / DaemonSet 差异。

### 未采纳方案

- **直接主流 `crawl:tasks` 小流量**：无法隔离生产真实队列干扰，失败时难以区分上游任务质量与 executor 配置问题。
- **只做 kubectl dry-run**：无法验证 Redis / Kafka / OCI 和多出口 IP 的真实运行路径。

## 2. in-flight SIGTERM 验证

### 决策

使用慢响应端点制造请求已发起但未完成的状态，SIGTERM 目标 Pod PID 1，验证 previous 日志、PEL、后续 reclaim 和最终发布。

### 理由

007 staging 验证已证明 SIGTERM handler 和退出摘要存在，但没有证明下载中断时消息不会错误 `XACK`。该场景是 RollingUpdate 和手动重启的关键风险。

### 未采纳方案

- **只看 shutdown metrics**：指标无法证明具体 stream message 的 PEL 状态。
- **强删 Pod**：更接近灾难场景，但不适合作为第一版可重复验证脚本。

## 3. delayed buffer SIGTERM 验证

### 决策

通过 M4 policy / pacer 参数让任务进入 delayed buffer，SIGTERM 后验证 buffered message 留 PEL，并在后续 worker reclaim 后按正常或 deadline terminal 路径完成。

### 理由

M3a 引入本地 delayed buffer 后，消息可能已经离开 Redis 新消息读取路径、进入 worker 内存等待。production 前必须证明这类内存态不会造成 ack 丢失。

### 未采纳方案

- **只做单元测试**：单元测试可覆盖逻辑，但不能证明 Scrapy、Redis Stream、signal 和 K8s 生命周期组合行为。

## 4. Kafka outbox / 故障补偿

### 决策

先定义本地 outbox 契约，再决定是否在 M5 第一批实现。outbox 仅保存待发布 `crawl_attempt`，不保存 URL 调度状态。

### 理由

当前语义是 Kafka publish failure 时不 `XACK`，消息保留 PEL；这能避免队列消息丢失，但对象已写入后事件长期不可见仍会影响下游事实完整性。outbox 需要持久化事件 payload、重放状态、水位和错误原因。

### 设计候选

| 方案 | 优点 | 风险 |
|---|---|---|
| 节点本地 SQLite outbox | 实现简单、可事务化、易抽样审计 | 节点盘容量、Pod 重建路径和 PV 策略需确认 |
| 本地文件 JSONL outbox | 易观察、实现轻量 | 并发写、截断恢复和状态更新复杂 |
| Redis side stream outbox | 易重放、跨节点可见 | 会扩大 Redis 写入边界，需要 ADR 说明不是 URL 队列写入 |

### 初步倾向

优先评估节点本地 SQLite 或等价轻量持久化；若需要跨节点 outbox，应先新增 ADR。

## 5. 发布 / 回滚

### 决策

发布前保存 image ref、ConfigMap policy version / 摘要和 DaemonSet generation；回滚同时恢复 image 与 policy，随后执行 health / metrics / smoke。

### 理由

M4 policy 与镜像能力强相关。只回滚镜像不回滚 policy，或者只回滚 policy 不回滚镜像，都可能留下不可解释行为。

## 6. open items

- production 的精确 kube context、registry namespace、Object Storage bucket / namespace 和 Kafka ACL 不写入规格；由 `deploy/environments/production.env`、Secret 和跳板机环境承载。
- outbox 若需要 PV 或 hostPath 策略，需要在实现前确认 crawler node 的磁盘生命周期和清理策略。
