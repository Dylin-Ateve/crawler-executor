# 快速开始：M5 生产就绪与可靠性补偿

本文档定义 008 第一阶段的验证入口。脚本名称作为目标契约记录，具体实现由 `tasks.md` 后续任务落地。

## 前置条件

- M4 staging 验证已通过。
- staging 已恢复 `CRAWLER_DEBUG_MODE=false` 和稳定 runtime policy。
- production 环境变量由 `deploy/environments/production.env` 承载。
- 操作默认在跳板机执行。
- 面向运行期的辅助脚本放在 `ops/`。

## Step 1：production 配置审计

目标：

- 确认 production Secret / ConfigMap / DaemonSet / node label / image / policy 基础条件满足。
- 不输出任何 Secret 值。

预期命令：

```bash
set -a
. deploy/environments/production.env
set +a

ops/scripts/run-production-config-audit.sh
```

通过条件：

- 输出 `production_config_audit_ok`。
- image ref 为显式 tag。
- runtime policy 配置与 M4 契约一致。

## Step 2：production dry-run / rollout

目标：

- 使用 production env 渲染 ConfigMap 和 DaemonSet。
- 先 dry-run，再按窗口 apply。

预期命令：

```bash
deploy/scripts/render-k8s-configmap-from-env.sh >/tmp/crawler-executor-config.production.yaml
kubectl -n "$M3_K8S_NAMESPACE" apply --dry-run=server -f /tmp/crawler-executor-config.production.yaml

deploy/scripts/render-k8s-daemonset-from-env.sh >/tmp/crawler-executor-daemonset.production.yaml
kubectl -n "$M3_K8S_NAMESPACE" apply --dry-run=server -f /tmp/crawler-executor-daemonset.production.yaml
```

apply 必须在明确发布窗口内执行。

## Step 3：production 最小 smoke

目标：

- 通过 debug stream 投递 10-50 条 Fetch Command。
- 验证 `crawl_attempt`、Object Storage、PEL 和 M4 指标。

预期命令：

```bash
ops/scripts/run-production-smoke.sh --count 10
```

通过条件：

- `crawl_attempt` 发布成功。
- debug stream PEL `pending=0`。
- HTML 快照可读取 / 解压。
- `crawler_policy_current_version` 符合预期。

## Step 4：in-flight SIGTERM 专项验证

目标：

- 验证请求下载中 SIGTERM 不错误 ack。

预期命令：

```bash
ops/scripts/run-shutdown-inflight-validation.sh
```

通过条件：

- SIGTERM 后停止新读 / claim。
- 未完成消息留 PEL。
- 后续 worker reclaim 并完成 publish / ack。

## Step 5：delayed buffer SIGTERM 专项验证

目标：

- 验证 delayed buffer 非空时 SIGTERM 不丢消息。

预期命令：

```bash
ops/scripts/run-shutdown-delayed-buffer-validation.sh
```

通过条件：

- buffered message 不 `XACK`。
- 后续 worker reclaim。
- 未过期任务正常执行，过期任务发布 `deadline_expired` terminal attempt。

## Step 6：Kafka outbox 设计评审

目标：

- 基于 `contracts/kafka-outbox.md` 决定 M5 是否实现 outbox。
- 若采用 persist-first ack 或 Redis side stream outbox，必须先新增 ADR。

评审输入：

- outbox 数据模型。
- 状态机。
- 容量上限。
- replay SOP。
- 指标和告警草案。

## Step 7：发布 / 回滚演练

目标：

- 记录发布前 image / policy。
- 验证回滚命令和恢复检查。

通过条件：

- image ref 可恢复。
- policy version 可恢复。
- DaemonSet rollout complete。
- health / metrics / smoke 通过。
