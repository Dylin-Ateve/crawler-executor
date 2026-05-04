# 最小规模化抓取 Runbook

**适用阶段**：M4 staging 已验证后，基于当前 executor 能力开展受控内容抓取。  
**执行位置**：跳板机。  
**目标**：按 Redis Fetch Command 契约向 `crawl:tasks` 投递抓取任务，由 DaemonSet worker 消费并产出对象存储 HTML 快照与 `crawl_attempt` 事件。

## 当前系统已具备的能力

- K8s DaemonSet 常驻执行，`hostNetwork=true`，每个 `scrapy-egress=true` node 一个 worker。
- staging 下每 node 5 个 `enp0s5` IPv4 已验证；production 多出口 IP 仍需按 M5 复刻。
- Redis / Valkey Streams consumer group 只读消费第六类 Fetch Command。
- `crawl_attempt` 发布成功后才 `XACK`；Kafka 发布失败时消息留 PEL，后续可 reclaim。
- HTML 内容写入 OCI Object Storage，gzip 快照可由 `storage_key` 定位。
- host-aware `STICKY_POOL`、per-(host, egress identity) pacer、soft-ban feedback、IP cooldown、host slowdown、本地 delayed buffer 已在 staging 验证。
- M4 runtime policy 文件型 provider 已在 staging 验证：policy reload、last-known-good、作用域 pause、`deadline_at`、`max_retries`、SIGTERM shutdown 指标可用。
- Prometheus 暴露 worker 级请求、存储、Kafka、Redis、出口健康、M3a 和 M4 控制指标。

## 当前仍不具备的生产能力

- production 复刻验证尚未完成。
- 没有 Kafka outbox / 本地持久化补偿；对象已写但 Kafka 长时间不可用时仍需后续 M5 能力兜底。
- 没有 poison message / DLQ 协议；非法消息当前记录后 `XACK` 丢弃，不发布 `crawl_attempt`。
- 没有完整 Grafana / 告警 / on-call SOP。
- 没有 24 小时稳定性压测和 30-50 pages/sec 单节点目标验证。
- 不负责 URL 选择、业务优先级、重抓窗口、outlinks 入队、解析派发或事实投影。

## Fetch Command 最小字段

每行 JSON object，必须包含：

```json
{"url":"https://www.wikipedia.org/","canonical_url":"https://www.wikipedia.org","job_id":"job_20260504_batch"}
```

建议同时提供：

```json
{
  "command_id": "job_20260504_batch:00000001",
  "trace_id": "trace:job_20260504_batch",
  "tier": "default",
  "politeness_key": "host:www.wikipedia.org",
  "deadline_at": "2026-05-04T09:30:00Z",
  "max_retries": 2
}
```

关键语义：

- `job_id + canonical_url` 决定 executor 生成的确定性 `attempt_id`。
- 同一 `job_id + canonical_url` 重复投递会生成相同 `attempt_id`，适合幂等追踪，不适合表达两个独立批次。
- `deadline_at` 是“最晚允许开始抓取”的时间，过期后不会发起 HTTP 请求。
- `max_retries=0` 表示第一次 fetch 层可重试失败即 terminal；Kafka publish failure 不消耗该预算。
- `policy_scope_id`、`politeness_key`、`host_id`、`site_id`、`tier` 会参与 M4 effective policy 匹配。

## 生成 JSONL

准备 URL 列表：

```bash
cat >/tmp/urls.txt <<'EOF'
https://www.wikipedia.org/
https://example.com/a?b=1
EOF
```

生成 Fetch Command JSONL：

```bash
ops/scripts/generate-fetch-command-jsonl.py /tmp/urls.txt \
  --job-id job_20260504_seed_001 \
  --tier default \
  --deadline-minutes 120 \
  --max-retries 2 \
  --output /tmp/fetch-commands.jsonl
```

可选参数：

- `--site-id site_xxx`
- `--host-id-prefix host_`
- `--politeness-prefix host:`
- `--policy-scope-id policy_scope_xxx`
- `--limit 1000`

## 校验 JSONL

```bash
ops/scripts/validate-fetch-command-jsonl.py /tmp/fetch-commands.jsonl
```

更严格地要求至少一个执行上下文字段：

```bash
ops/scripts/validate-fetch-command-jsonl.py /tmp/fetch-commands.jsonl --require-context
```

通过输出：

```text
fetch_command_jsonl_valid count=<N>
```

## 投递到 Redis Stream

先加载 staging 环境：

```bash
set -a
. deploy/environments/staging.env
set +a
```

投递到默认主流 `crawl:tasks`：

```bash
ops/scripts/enqueue-fetch-commands-via-k8s.sh /tmp/fetch-commands.jsonl
```

dry-run，只验证 Pod 内可解析，不写 Redis：

```bash
DRY_RUN=true ops/scripts/enqueue-fetch-commands-via-k8s.sh /tmp/fetch-commands.jsonl
```

投递到 debug stream：

```bash
POD="$(kubectl -n "$M3_K8S_NAMESPACE" get pods -l "$M3_LABEL_SELECTOR" -o jsonpath='{.items[0].metadata.name}')"
NODE="$(kubectl -n "$M3_K8S_NAMESPACE" get pod "$POD" -o jsonpath='{.spec.nodeName}')"

FETCH_QUEUE_STREAM="crawl:tasks:debug:${NODE}" \
ops/scripts/enqueue-fetch-commands-via-k8s.sh /tmp/fetch-commands.jsonl
```

指定用于投递的 Pod：

```bash
ENQUEUE_POD="$POD" ops/scripts/enqueue-fetch-commands-via-k8s.sh /tmp/fetch-commands.jsonl
```

## 投递后观察

查看 Redis Stream 长度和 PEL：

```bash
POD="$(kubectl -n "$M3_K8S_NAMESPACE" get pods -l "$M3_LABEL_SELECTOR" -o jsonpath='{.items[0].metadata.name}')"

kubectl -n "$M3_K8S_NAMESPACE" exec -i "$POD" -- \
  env STREAM="${FETCH_QUEUE_STREAM:-crawl:tasks}" GROUP="${FETCH_QUEUE_GROUP:-crawler-executor}" python - <<'PY'
import os
import redis

r = redis.from_url(os.environ.get("FETCH_QUEUE_REDIS_URL") or os.environ.get("REDIS_URL"), decode_responses=True)
stream = os.environ["STREAM"]
group = os.environ["GROUP"]
print("xlen", r.xlen(stream))
try:
    print("xpending", r.xpending(stream, group))
except Exception as exc:
    print("xpending_error", type(exc).__name__, exc)
PY
```

看 worker 日志：

```bash
kubectl -n "$M3_K8S_NAMESPACE" logs -l "$M3_LABEL_SELECTOR" --since=10m --tail=500 \
  | grep -E 'fetch_queue_response_observed|p1_crawl_attempt_published|retry_exhausted|deadline_expired|paused' || true
```

看 M4 / 队列指标：

```bash
kubectl -n "$M3_K8S_NAMESPACE" exec "$POD" -- python - <<'PY'
import urllib.request

metrics = urllib.request.urlopen("http://127.0.0.1:9410/metrics", timeout=3).read().decode()
for line in metrics.splitlines():
    if line.startswith((
        "crawler_fetch_queue_events_total",
        "crawler_policy_current_version",
        "crawler_fetch_paused_total",
        "crawler_fetch_deadline_expired_total",
        "crawler_fetch_retry_terminal_total",
        "crawler_kafka_publish_total",
        "crawler_storage_upload_total",
    )):
        print(line)
PY
```

## 最小规模化建议

1. 先用 debug stream 做 10-50 条 smoke，确认 `crawl_attempt`、对象存储和 PEL 清空。
2. 主流 `crawl:tasks` 首批控制在 100-500 条，观察 Kafka publish、Object Storage、PEL、错误率和 pacing 指标。
3. 每个批次使用新的 `job_id`；同批次不要重复 `job_id + canonical_url`。
4. 为批次设置 `deadline_at`，避免 backlog 积压后继续抓过期任务。
5. 对高风险站点先通过 `policy_scope_id` 或 `politeness_key` 配合 M4 policy 降低速度或 pause。
6. 不要把 outlinks、解析结果或重抓决策写回本仓库队列；这些仍归第六类。
7. 若 Kafka 或 Object Storage 异常，先暂停投递新批次；当前阶段没有本地 outbox 补偿。
