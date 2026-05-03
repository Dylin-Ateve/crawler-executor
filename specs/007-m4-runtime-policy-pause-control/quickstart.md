# 快速开始：M4 运行时执行策略与停抓控制

本文档定义 007 的本地验证流程。脚本名称作为目标契约记录，具体脚本由 `tasks.md` 后续任务实现。

## 前置条件

- P2 Redis Streams consumer group 验证已通过。
- P1 `crawl_attempt` producer 可用。
- M3a `STICKY_POOL`、pacer、delayed buffer 和 Redis TTL 执行态可用。
- Redis / Valkey、Kafka、对象存储测试环境可用。
- 不要求 production 环境；production 复刻后置到 M5。

## 建议环境变量

```bash
export RUNTIME_POLICY_PROVIDER=file
export RUNTIME_POLICY_FILE=/tmp/crawler-effective-policy.json
export RUNTIME_POLICY_RELOAD_INTERVAL_SECONDS=5
export RUNTIME_POLICY_FAIL_OPEN_WITH_BOOTSTRAP=true
export RUNTIME_POLICY_LKG_MAX_AGE_SECONDS=3600

export FETCH_QUEUE_BLOCK_MS=1000
export FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS=25
```

## 示例策略文件

```bash
cat >/tmp/crawler-effective-policy.json <<'JSON'
{
  "schema_version": "1.0",
  "version": "policy-local-001",
  "generated_at": "2026-05-03T10:00:00Z",
  "default_policy": {
    "enabled": true,
    "paused": false,
    "egress_selection_strategy": "STICKY_POOL",
    "sticky_pool_size": 4,
    "host_ip_min_delay_ms": 2000,
    "host_ip_jitter_ms": 500,
    "download_timeout_seconds": 30,
    "max_retries": 2,
    "max_local_delay_seconds": 300
  },
  "scope_policies": [
    {
      "scope_type": "politeness_key",
      "scope_id": "site:example",
      "policy": {
        "host_ip_min_delay_ms": 5000,
        "max_retries": 1
      }
    }
  ]
}
JSON
```

## Step 1：policy reload 验证

目标：

- 策略文件变更后不重启 worker 即可生效。
- 策略版本指标更新。

预期命令：

```bash
deploy/scripts/run-m4-policy-reload-validation.sh
```

通过条件：

- 日志显示 `policy-local-001` 加载成功。
- 修改策略为 `policy-local-002` 后，reload interval 内应用新版本。
- `crawler_policy_load_total{result="success"}` 增加。

## Step 2：last-known-good 验证

目标：

- 策略文件非法时不覆盖 LKG。
- LKG 指标可见。

预期命令：

```bash
deploy/scripts/run-m4-policy-lkg-validation.sh
```

通过条件：

- 有效策略加载成功。
- 文件替换为非法 JSON 后，worker 继续使用上一版本。
- `crawler_policy_lkg_active` 变为 1。
- `crawler_policy_load_total{result="validation_error"}` 或 `read_error` 增加。

## Step 3：pause 验证

目标：

- 全局 / 作用域 pause 不发起 HTTP 请求。
- pause terminal attempt 发布成功后 `XACK`。

预期命令：

```bash
deploy/scripts/run-m4-pause-validation.sh
```

通过条件：

- 测试 HTTP server 未收到 paused request。
- Kafka 中出现 `error_type=paused` 的 `crawl_attempt`。
- Redis PEL 最终清空。
- `crawler_fetch_paused_total` 增加。

## Step 4：deadline 验证

目标：

- 已过期或 delayed 后过期的 Fetch Command 不发起 HTTP 请求。

预期命令：

```bash
deploy/scripts/run-m4-deadline-validation.sh
```

通过条件：

- 测试 HTTP server 未收到 expired request。
- Kafka 中出现 `error_type=deadline_expired` 的 `crawl_attempt`。
- Redis PEL 最终清空。
- `crawler_fetch_deadline_expired_total` 增加。

## Step 5：max retries 验证

目标：

- command `max_retries` 覆盖默认值。
- Kafka publish failure 不进入 max retries terminal。

预期命令：

```bash
deploy/scripts/run-m4-max-retries-validation.sh
```

通过条件：

- `max_retries=0` 的 fetch 层可重试失败第一次即 terminal。
- `max_retries=2` 的 fetch 层失败在预算内保留 PEL。
- Kafka 不可用时不因 retry budget `XACK` 丢弃。

## Step 6：严格优雅停机验证

目标：

- SIGTERM 后停止新 `XREADGROUP` / `XAUTOCLAIM`。
- 未完成消息保留 PEL。

预期命令：

```bash
deploy/scripts/run-m4-graceful-shutdown-validation.sh
```

通过条件：

- SIGTERM 后日志显示 read / claim stopped。
- 停机窗口内不再出现新的 `XREADGROUP` / `XAUTOCLAIM`。
- delayed buffer 或 in-flight 未完成消息不 `XACK`。
- `crawler_shutdown_events_total` 对应事件增加。

## Step 7：回归测试

```bash
.venv/bin/pytest
```

建议优先覆盖：

- runtime policy 纯逻辑单元测试。
- Fetch Command parse / deadline / max retries 测试。
- pause / deadline terminal attempt pipeline 测试。
- graceful shutdown consumer / spider 测试。

## 本地验证记录

2026-05-03 本地执行结果：

| 脚本 / 测试 | 结果 |
|---|---|
| `deploy/scripts/run-m4-policy-reload-validation.sh` | 通过 |
| `deploy/scripts/run-m4-policy-lkg-validation.sh` | 通过 |
| `deploy/scripts/run-m4-pause-validation.sh` | 通过 |
| `deploy/scripts/run-m4-deadline-validation.sh` | 通过 |
| `deploy/scripts/run-m4-max-retries-validation.sh` | 通过 |
| `deploy/scripts/run-m4-graceful-shutdown-validation.sh` | 通过 |
| `.venv/bin/pytest` | 通过，144 passed |
