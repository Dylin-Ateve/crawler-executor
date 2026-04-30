# 需求检查清单：P3 K8s DaemonSet + hostNetwork 生产部署基础

**创建日期**：2026-04-30  
**关联 spec**：`specs/004-p3-k8s-daemonset-hostnetwork/spec.md`

## 规格质量

- [x] 不包含实现细节 manifest。
- [x] 明确用户场景、验收标准和边界场景。
- [x] 明确 M3 不做第五类事实投影、第三类解析、完整控制平面和本地 outbox。
- [x] 已记录用户确认的三项关键决策：关停语义 B、健康检查口径、debug attempt 事件边界。
- [x] 已记录 50-70 个本地出口 IPv4 的 node 规模假设。
- [x] 已补齐 `research.md`、`data-model.md`、`plan.md`、`quickstart.md`、`tasks.md` 草案。

## 门禁检查

- [x] 章程门禁：规格先行，未直接进入 K8s manifest 实现。
- [x] 产品门禁：仍聚焦第二类抓取执行系统，不引入 URL 选择、解析或事实层职责。
- [x] 架构门禁：符合 DaemonSet / hostNetwork / Secret 注入 / 指标端口要求。
- [x] 决策门禁：遵守 ADR-0003 / 0004 / 0006 / 0008 / 0009 / 0010。

## 待 plan 阶段细化

- [x] 具体 DaemonSet manifest 文件路径与模板方式。
- [x] liveness / readiness endpoint 的实现路径与判定字段。
- [x] IP 池扫描命令、过滤规则与 50-70 IP 目标节点验证命令。
- [x] `claim_min_idle_ms`、`terminationGracePeriodSeconds`、`FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS` 的具体默认值。
- [x] pause flag 的配置来源与验证脚本。
- [x] debug stream 切换与恢复步骤。
- [x] Secret / ConfigMap 样例模板。
