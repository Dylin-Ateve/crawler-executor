# M4 staging 验证报告

**验证日期**：2026-05-04  
**验证环境**：staging OKE / `crawler-executor` namespace  
**执行位置**：跳板机  
**验证镜像**：`phx.ocir.io/axfwvgxlpupm/crawler-executor:m4-staging-20260504-001`  
**对应 spec**：`007-m4-runtime-policy-pause-control`

## 结论

M4“运行时执行策略与停抓控制”已在 staging 等价镜像环境完成验证。验证覆盖 K8s ConfigMap 文件型 effective policy provider、运行时热加载、last-known-good、作用域 pause、`deadline_at` 过期跳过、Fetch Command `max_retries=0` 生效、SIGTERM 严格停机入口和恢复到正常 staging 配置。

production 复刻验证仍按 roadmap 后置到 M5；本次不声明 production 已验证。

## 环境与前置

- DaemonSet：`crawler-executor`
- Namespace：`crawler-executor`
- 节点形态：2 个 `scrapy-egress=true` node，每 node 一个 `hostNetwork=true` Pod。
- 验证前应用 M4 runtime policy K8s 配置：
  - `RUNTIME_POLICY_PROVIDER=file`
  - `RUNTIME_POLICY_FILE=/etc/crawler/runtime/runtime_policy.json`
  - `RUNTIME_POLICY_RELOAD_INTERVAL_SECONDS=5`
  - `RUNTIME_POLICY_LKG_MAX_AGE_SECONDS=3600`
  - ConfigMap key `runtime_policy` 挂载为 `runtime_policy.json`
- 配置审计脚本：`deploy/scripts/run-m4-k8s-policy-config-audit.sh`

配置审计通过，输出包含：

```text
m4_k8s_policy_config_audit_ok namespace=crawler-executor daemonset=crawler-executor configmap=crawler-executor-config
```

## 关键过程记录

### 1. 旧镜像识别与 M4 镜像切换

初始 DaemonSet 已具备 `RUNTIME_POLICY_*` 配置，但镜像内缺少 M4 代码：

```text
crawler.policy_provider MISSING
crawler.runtime_policy MISSING
fetch_queue_has_policy_provider False
fetch_queue_has_deadline_expired False
policy_load_total False
policy_current_version False
policy_lkg_active False
fetch_deadline_expired_total False
shutdown_events_total False
```

随后构建并切换到 M4 staging 镜像：

```text
phx.ocir.io/axfwvgxlpupm/crawler-executor:m4-staging-20260504-001
```

新镜像 rollout 后，M4 policy / metrics 代码可用，后续行为验证继续执行。

### 2. policy reload

先加载 `policy-staging-m4-001`，投递 debug Fetch Command 后观察到：

```text
crawler_policy_load_total{result="success"} 1.0
crawler_policy_current_version{version="policy-staging-m4-001"} 1.0
```

随后将 ConfigMap `runtime_policy` 更新为 `policy-staging-m4-002`。等待 ConfigMap volume 传播并再次投递 debug Fetch Command 后观察到：

```text
crawler_policy_load_total{result="success"} 2.0
crawler_policy_load_total{result="not_modified"} 1.0
crawler_policy_current_version{version="policy-staging-m4-001"} 1.0
crawler_policy_current_version{version="policy-staging-m4-002"} 1.0
```

结论：策略文件变更无需重启 worker 即可被运行时加载。`crawler_policy_current_version` 当前会保留历史 version label；本次以新 version label 出现作为 reload 生效证据。

### 3. last-known-good

将 ConfigMap `runtime_policy` 临时更新为非法 JSON `{bad-json}`，等待传播后投递 debug Fetch Command。指标输出：

```text
crawler_policy_load_total{result="success"} 2.0
crawler_policy_load_total{result="not_modified"} 1.0
crawler_policy_load_total{result="validation_error"} 1.0
crawler_policy_current_version{version="policy-staging-m4-001"} 1.0
crawler_policy_current_version{version="policy-staging-m4-002"} 1.0
crawler_policy_lkg_active 1.0
crawler_policy_lkg_age_seconds 756.3315267562866
```

结论：非法策略不会覆盖 last-known-good；worker 继续保留上一有效策略并暴露 LKG 指标。

### 4. pause 与 deadline

恢复有效策略，并加入作用域策略：

- `policy_scope_id=m4-staging-paused`
- `paused=true`
- `pause_reason=staging_validation_pause`

投递两条 debug Fetch Command：

- `job_id=m4-staging-paused`，命中 `policy_scope_id=m4-staging-paused`
- `job_id=m4-staging-deadline`，携带过期 `deadline_at=2026-01-01T00:00:00Z`

指标输出：

```text
crawler_policy_load_total{result="success"} 3.0
crawler_policy_load_total{result="not_modified"} 1.0
crawler_policy_load_total{result="validation_error"} 1.0
crawler_policy_current_version{version="policy-staging-m4-paused"} 1.0
crawler_policy_lkg_active 0.0
crawler_fetch_paused_total{matched_scope_type="policy_scope_id",reason="staging_validation_pause"} 1.0
crawler_fetch_deadline_expired_total{matched_scope_type="default"} 1.0
```

结论：作用域 pause 和过期 `deadline_at` 均在发起 HTTP 请求前生效，并通过 M4 指标区分原因。

### 5. max_retries=0

投递 `url=http://127.0.0.1:1/`、`max_retries=0` 的 debug Fetch Command。指标输出：

```text
crawler_fetch_queue_events_total{result="empty"} 2322.0
crawler_fetch_queue_events_total{result="read"} 7.0
crawler_fetch_queue_events_total{result="ack"} 7.0
crawler_policy_decision_total{matched_scope_type="default"} 6.0
crawler_policy_decision_total{matched_scope_type="policy_scope_id"} 1.0
crawler_fetch_retry_terminal_total{reason="retry_exhausted"} 1.0
```

同一 debug stream 的 PEL 查询：

```text
xpending {'pending': 0, 'min': None, 'max': None, 'consumers': []}
```

结论：Fetch Command `max_retries=0` 生效，fetch 层失败第一次即进入 retry exhausted terminal attempt；发布成功后消息已 `XACK`，PEL 清空。

### 6. SIGTERM 严格停机

对验证 Pod 执行 `kill -TERM 1`，随后读取 previous container 日志：

```text
fetch_queue_shutdown_signal_received reason=signal:15 seen_messages=7 acked_count=7 drain_seconds=25
fetch_queue_shutdown_loop_exit elapsed_seconds=0.001 drain_timeout=false seen_messages=7 acked_count=7 in_flight_estimate=0
```

结论：SIGTERM 到达后立即进入 shutdown 路径，记录停机入口和退出总结；本次验证现场没有未完成 in-flight，`in_flight_estimate=0`。

### 7. 恢复正常 staging 配置

验证结束后恢复 staging ConfigMap 与 DaemonSet：

- `CRAWLER_DEBUG_MODE=false`
- `runtime_policy.version=policy-staging-bootstrap`

恢复后审计脚本通过：

```text
m4_k8s_policy_config_audit_ok namespace=crawler-executor daemonset=crawler-executor configmap=crawler-executor-config
```

最终 Pod 内确认：

```text
CRAWLER_DEBUG_MODE=false
```

## 发现与修正

1. ConfigMap / DaemonSet 配置就绪不等于镜像包含 M4 代码。后续 staging 验证必须先执行镜像内代码检查，确认 `crawler.policy_provider`、`crawler.runtime_policy` 和 M4 metrics 存在。
2. staging 镜像不保证包含所有 `deploy/scripts`，debug Fetch Command 投递应使用 Pod 内 Python 和运行时 Redis 依赖直接写入 debug stream。
3. ConfigMap volume 会热更新，但环境变量不会热更新；恢复 `CRAWLER_DEBUG_MODE=false` 后必须 rollout restart DaemonSet 才能让 Pod 环境变量生效。

上述修正已回填到 `staging-runbook.md`。

## 后续

- production 复刻仍按 M5 执行，不由本报告关闭。
- Grafana / 告警、Kafka outbox、DLQ、长期压测仍后置。
- 若后续要求证明 SIGTERM 下存在 in-flight 或 delayed buffer 时 PEL 留存，可在 M5 production 复刻前设计专门长请求 / delayed buffer 场景补充。
