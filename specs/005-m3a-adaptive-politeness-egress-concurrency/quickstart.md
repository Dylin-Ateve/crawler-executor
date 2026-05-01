# 快速开始：M3a 自适应 Politeness 与出口并发控制

本文档定义 005 的本地和目标节点验证流程。脚本名称先作为目标契约记录，具体脚本由 `tasks.md` 后续任务实现。

## 前置条件

- P2 Redis Streams consumer group 验证已通过。
- P1 `crawl_attempt` producer 可用。
- Redis / Valkey 可用于 Fetch Queue 和短窗口执行安全状态。
- 至少一个具备多个本地出口 IP 的目标节点可用于最终验证。
- 004 暂停状态保持，不在 005 未完成前部署 DaemonSet。

## 建议环境变量

```bash
export EGRESS_SELECTION_STRATEGY=STICKY_POOL
export STICKY_POOL_SIZE=4
export EGRESS_IDENTITY_SOURCE=auto
export ALLOW_BIND_IP_AS_EGRESS_IDENTITY=true

export HOST_IP_MIN_DELAY_MS=2000
export HOST_IP_JITTER_MS=500
export HOST_IP_BACKOFF_BASE_MS=5000
export HOST_IP_BACKOFF_MAX_MS=300000
export IP_COOLDOWN_SECONDS=1800
export HOST_SLOWDOWN_SECONDS=600

export LOCAL_DELAYED_BUFFER_CAPACITY=100
export MAX_LOCAL_DELAY_SECONDS=300
export STOP_READING_WHEN_DELAYED_BUFFER_FULL=true

export SOFT_BAN_WINDOW_SECONDS=300
export HOST_IP_SOFT_BAN_THRESHOLD=2
export IP_CROSS_HOST_CHALLENGE_THRESHOLD=3
export HOST_CROSS_IP_CHALLENGE_THRESHOLD=3

export EXECUTION_STATE_REDIS_PREFIX=crawler:exec:safety
export EXECUTION_STATE_MAX_TTL_SECONDS=86400
export EXECUTION_STATE_WRITE_ENABLED=true
```

production 与 staging profile 都必须保持 `EGRESS_SELECTION_STRATEGY=STICKY_POOL`。`STICKY_BY_HOST` 只允许单独的 P0 / 回退验证 profile 显式启用，不作为 staging 默认。

## T005 profile 审核结果

| profile | 结论 | 说明 |
|---|---|---|
| `deploy/environments/production.env` | 已准备切换 | `IP_SELECTION_STRATEGY=STICKY_POOL` 与 `EGRESS_SELECTION_STRATEGY=STICKY_POOL` 均已设置；005 参数块已补齐。 |
| `deploy/environments/staging.env` | 镜像 production 行为 | `IP_SELECTION_STRATEGY=STICKY_POOL` 与 `EGRESS_SELECTION_STRATEGY=STICKY_POOL` 均已设置；`EXECUTION_STATE_WRITE_ENABLED=true`，但 Redis prefix 使用 `crawler:exec:safety:staging` 与 production 隔离。 |

T019 完成后以 `EGRESS_SELECTION_STRATEGY` 作为 005 策略入口，`IP_SELECTION_STRATEGY` 仅作为历史兼容字段。staging 和 production 在两套隔离集群中执行同一验证流程，只允许网卡名、IP 数、存储 / Kafka / Redis 端点等物理资源值不同。

## 本地验证记录

2026-05-01 本地执行结果：

| 脚本 / 测试 | 结果 |
|---|---|
| `deploy/scripts/run-m3a-config-audit.sh` | 通过 |
| `deploy/scripts/run-m3a-sticky-pool-validation.sh` | 通过 |
| `deploy/scripts/run-m3a-pacer-validation.sh` | 通过 |
| `deploy/scripts/run-m3a-soft-ban-feedback-validation.sh` | 通过 |
| `deploy/scripts/run-m3a-delayed-buffer-validation.sh` | 通过 |
| `deploy/scripts/run-m3a-redis-boundary-validation.sh` | 通过 |
| `.venv/bin/pytest tests/unit/test_egress_identity.py tests/unit/test_egress_policy.py tests/unit/test_politeness.py tests/unit/test_response_signals.py tests/unit/test_fetch_safety_state.py tests/unit/test_soft_ban_feedback.py tests/unit/test_fetch_queue_m3a.py tests/integration/test_egress_middleware.py tests/unit/test_ip_pool.py` | 通过，59 passed |

目标节点 smoke 仍需在恢复 004 前执行，尤其需要确认真实多出口 IP、Redis / Kafka / Object Storage Secret 和 Prometheus 抓取。

## Step 1：静态配置审计

目标：

- 确认 production profile 不再默认 `STICKY_BY_HOST`。
- 确认 delayed buffer 有容量和时间上限。
- 确认 Redis 执行态 prefix 与 URL 队列 prefix 隔离。

预期命令：

```bash
deploy/scripts/run-m3a-config-audit.sh
```

通过条件：

- `EGRESS_SELECTION_STRATEGY=STICKY_POOL`。
- `STOP_READING_WHEN_DELAYED_BUFFER_FULL=true`。
- `EXECUTION_STATE_REDIS_PREFIX` 不为空且不等于 Fetch Queue stream / group 前缀。
- staging profile 与 production 一样使用 `EGRESS_SELECTION_STRATEGY=STICKY_POOL`，但 Redis 执行态 prefix 必须隔离。

## Step 2：sticky-pool 稳定性验证

目标：

- 同一 host 只映射到 K 个候选出口身份。
- 进程重启 / 重复执行时候选池稳定。

预期命令：

```bash
deploy/scripts/run-m3a-sticky-pool-validation.sh
```

通过条件：

- 对同一 host 生成的候选身份数量等于 `min(STICKY_POOL_SIZE, active_egress_identity_count)`。
- 重复运行候选集合一致。
- IP cooldown 后候选池选择避开冷却身份。

## Step 3：per-(host, ip) pacer 验证

目标：

- 同一 `(host, egress_identity)` 的请求启动间隔满足 `HOST_IP_MIN_DELAY_MS`。
- 不同 egress identity 的同 host 请求可以并行或更紧密执行。

预期命令：

```bash
deploy/scripts/run-m3a-pacer-validation.sh
```

通过条件：

- 日志中相同 `host_hash + egress_identity_hash` 的请求启动间隔不小于配置阈值。
- `crawler_pacer_delay_seconds` 有观测值。
- 未 eligible 消息不 `XACK`。

## Step 4：soft-ban feedback 验证

目标：

- 429 / challenge / 反爬 200 页触发正确维度的退避。
- 5xx / timeout 不被等价为强封禁信号。

预期命令：

```bash
deploy/scripts/run-m3a-soft-ban-feedback-validation.sh
```

通过条件：

- 同一 `(host, ip)` 连续 429 后产生 `host_ip` backoff。
- 同一 IP 跨多个 host challenge 后产生 IP cooldown。
- 同一 host 跨多个 IP challenge 后产生 host slowdown。
- 指标中 `crawler_feedback_signal_total` 按 signal type 增加。

## Step 5：delayed buffer 与 PEL 边界验证

目标：

- delayed buffer 满时停止 `XREADGROUP`。
- 未执行消息停机后留 PEL，不 `XACK`。
- 超过 `MAX_LOCAL_DELAY_SECONDS` 不发布虚假 `crawl_attempt`。

预期命令：

```bash
deploy/scripts/run-m3a-delayed-buffer-validation.sh
```

通过条件：

- `crawler_delayed_buffer_full_total` 增加。
- `crawler_xreadgroup_suppressed_total{reason="delayed_buffer_full"}` 增加。
- Redis Stream PEL 中保留未执行消息。
- Kafka / `crawl_attempt` 中没有 deferred 伪事实。

## Step 6：Redis 写入边界验证

目标：

- 证明 005 只写短窗口执行安全状态。
- 所有新增 key 有 TTL。

预期命令：

```bash
deploy/scripts/run-m3a-redis-boundary-validation.sh
```

通过条件：

- 新增 key 全部位于 `EXECUTION_STATE_REDIS_PREFIX` 或 Redis Streams consumer group 协议状态。
- 新增执行态 key 全部有 TTL。
- 未发现 URL queue、outlink、dupefilter、priority、profile key。
- 目标 Fetch Queue stream 未被 executor `XADD` 追加消息。

## Step 7：目标节点 smoke

目标：

- 在真实多出口 IP 节点上验证 sticky-pool、pacer、feedback 和指标可工作。

建议流程：

1. 使用小规模测试 stream，写入同一 host 和多 host 混合 Fetch Command。
2. 启动单 worker，启用 `STICKY_POOL`。
3. 观察日志中的 `egress_identity_hash`、`download_slot`、pacer delay。
4. 人工触发 429 / challenge 测试 endpoint。
5. 执行 Redis key diff 与 metrics 抓取。

通过条件：

- 至少一个 host 在多个出口身份间轮转。
- 同一 `(host, egress_identity)` 未过密启动。
- soft-ban 反馈能影响后续选择。
- 无禁止 Redis 写入。

## Step 8：004 恢复前检查

005 完成后，恢复 004 前必须确认：

- `deploy/environments/production.env` 已切换到 005 production 参数。
- 004 ConfigMap 契约不再把 `STICKY_BY_HOST` 描述为生产默认。
- 目标集群 ConfigMap 审核包含 005 运行参数。
- Redis PING、Kafka publish smoke、Object Storage 权限验证仍需按 004 quickstart 补做。
