# 快速开始：P2 第六类队列只读消费与多 worker 运行形态

本文档定义 003 的验证流程。验证脚本默认使用隔离的临时 Redis Stream，避免误读或污染真实 `crawl:tasks`；如需验证真实队列，可显式设置 `FETCH_QUEUE_STREAM=crawl:tasks`。

## 前置条件

- P0 单节点 Scrapy 多出口 IP PoC 已验证。
- P1 `crawl_attempt` producer 已通过 T055 验证。
- Redis / Valkey 测试实例可用。
- Kafka 与 OCI Object Storage 配置沿用 P1。

## 环境变量

| 变量 | 说明 | 示例 |
|---|---|---|
| `FETCH_QUEUE_BACKEND` | 队列后端 | `redis_streams` |
| `FETCH_QUEUE_REDIS_URL` | Redis / Valkey 连接串 | `redis://user:pass@127.0.0.1:6379/0` |
| `FETCH_QUEUE_STREAM` | Redis Stream key | `crawl:tasks` |
| `FETCH_QUEUE_GROUP` | Consumer group | `crawler-executor` |
| `FETCH_QUEUE_CONSUMER` | Consumer name | `worker-1` |
| `FETCH_QUEUE_READ_COUNT` | 单次读取数量 | `10` |
| `FETCH_QUEUE_BLOCK_MS` | 阻塞读取时间，禁止永久阻塞 | `5000` |
| `FETCH_QUEUE_MAX_DELIVERIES` | 最大投递次数 | `3` |
| `FETCH_QUEUE_CLAIM_MIN_IDLE_MS` | `XAUTOCLAIM` 最小 idle 时间 | `60000` |

## Step 1：写入测试抓取指令

命令：

```bash
deploy/scripts/p2-enqueue-fetch-commands.sh /tmp/p2-fetch-commands.jsonl
```

结果：

- 测试队列出现 3 条有效抓取指令。
- 每条有效指令包含 `url`、`job_id`、`canonical_url`。
- 写入动作模拟第六类，不由 crawler-executor worker 执行。

## Step 2：单 worker 消费验证

命令：

```bash
deploy/scripts/run-p2-queue-consumer-validation.sh
```

结果：

- worker 消费队列消息。
- 成功 HTML 发布 `storage_result=stored`。
- 非 HTML 发布 `storage_result=skipped`。
- 不可达 URL 发布 `fetch_result=failed`、`storage_result=skipped`。

## Step 3：多 worker 消费验证

命令：

```bash
deploy/scripts/run-p2-multi-worker-validation.sh
```

结果：

- 两个 worker 同时消费同一队列。
- 10 条消息正常 ack 路径下产生 10 条 `crawl_attempt`。
- 不重复处理已确认消费的消息。

## Step 4：只读边界验证

命令：

```bash
deploy/scripts/run-p2-readonly-boundary-validation.sh
```

结果：

- 抓取含 outlinks 的 HTML 页面后，Redis 队列无 executor 写入的新 URL。
- 只出现队列协议必需的 ack / pending / consumer 状态变化。
- 无 crawler-executor 写入第六类 URL 去重 key。

## Step 5：无效消息验证

命令：

```bash
deploy/scripts/run-p2-invalid-command-validation.sh
```

结果：

- 非法 JSON、缺少 URL、不支持 URL schema 均被记录。
- worker 不崩溃。
- 指标记录 invalid command。

## 结果记录表

| 项目 | 目标 | 实测 | 结论 |
|---|---|---|---|
| 单 worker 消费 | 有效队列指令产生 `crawl_attempt` | 待实现后填写 | 待验证 |
| 多 worker 消费 | 正常 ack 路径无重复处理 | 待实现后填写 | 待验证 |
| 只读边界 | executor 不写 URL 队列 / 不 enqueue outlinks | 待实现后填写 | 待验证 |
| fetch failed | 连接级失败发布 `fetch_result=failed` | 待实现后填写 | 待验证 |
| 无效消息 | 记录错误且 worker 不崩溃 | 待实现后填写 | 待验证 |
| attempt 幂等 | 同一 `job_id + canonical_url` 生成相同 `attempt_id` | 待实现后填写 | 待验证 |
