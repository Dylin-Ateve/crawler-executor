# 契约：production 复刻验证

## 执行入口

production 验证默认在跳板机执行。

必须显式加载 production 环境：

```bash
set -a
. deploy/environments/production.env
set +a
```

## 必需审计项

- `M3_K8S_NAMESPACE`
- `M3_DAEMONSET_NAME`
- `M3_CONFIGMAP_NAME`
- `M3_LABEL_SELECTOR`
- DaemonSet `hostNetwork=true`
- DaemonSet `RollingUpdate maxUnavailable=1`
- 容器 image ref 为显式 tag，不得为 `latest`
- Redis Secret key 存在但不输出值
- Kafka Secret key 存在但不输出值
- Object Storage 必需 env / Secret 存在但不输出值
- `RUNTIME_POLICY_PROVIDER=file`
- `RUNTIME_POLICY_FILE=/etc/crawler/runtime/runtime_policy.json`
- ConfigMap `runtime_policy` 能挂载为 policy file
- `CRAWLER_DEBUG_MODE` 发布前必须显式确认

## 最小 smoke

默认使用 debug stream：

```text
crawl:tasks:debug:<node>
crawler-executor-debug:<node>
```

通过条件：

- Fetch Command 可投递。
- worker 日志出现 `fetch_queue_response_observed` 或 terminal skip 对应日志。
- Kafka 发布 `crawl_attempt` 成功。
- Object Storage smoke 对 HTML 快照可读取 / 解压 / hash。
- Redis stream PEL 最终 `pending=0`。
- M4 指标可看到当前 policy version。

## 恢复条件

验证结束后必须确认：

- `CRAWLER_DEBUG_MODE=false`
- runtime policy 为 production 目标 bootstrap / release version
- DaemonSet rollout complete
- health / readiness 通过
- debug stream PEL 清空或已记录可解释残留

## 证据模板

```text
production_replica_validation_ok
namespace=<namespace>
daemonset=<daemonset>
image=<image_ref>
policy_version=<policy_version>
smoke_job_id=<job_id>
command_count=<n>
pel_pending=0
```
