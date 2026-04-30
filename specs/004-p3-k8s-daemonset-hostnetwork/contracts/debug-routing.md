# Debug Stream 路由契约：P3 crawler-executor

本文档定义 M3 第一版精准调试的 Redis Stream、consumer group、consumer name 和 Fetch Command 上下文命名规则。目标是把调试流量定向到指定 node / pod，同时让发布到正式 Kafka topic 的 `crawl_attempt` 可以被第五类按 `tier=debug` 过滤或标记。

## 命名规则

| 对象 | 生产命名 | debug 命名 | 说明 |
|---|---|---|---|
| stream | `crawl:tasks` | `crawl:tasks:debug:<node_name>` | `<node_name>` 使用 K8s Downward API 的 `NODE_NAME` 原值。 |
| consumer group | `crawler-executor` | `crawler-executor-debug:<node_name>` | 每个 debug node 独立 group，避免不同 node 的调试 PEL 混用。 |
| consumer | `${NODE_NAME}-${POD_NAME}` | `${NODE_NAME}-${POD_NAME}-debug` | 便于从 Redis PEL 反查 node / pod。 |
| attempt tier | 由第六类生产任务设置 | `debug` | debug Fetch Command 必须显式携带。 |

约束：

- debug stream 必须与生产 stream 隔离，不得向 `crawl:tasks` 写入调试任务。
- debug consumer group 必须与生产 group 隔离，不得复用 `crawler-executor`。
- debug consumer name 必须包含 node 与 pod 身份，并带 `-debug` 后缀。
- `NODE_NAME`、`POD_NAME` 来源必须是 K8s Downward API；不得在 ConfigMap 中为所有 pod 静态写同一个 consumer。
- M3 第一版采用每 node 单 pod，因此 node 级 debug stream 可以精确落到该 node 的唯一 crawler pod；若未来同 node 多 pod，需要扩展到 pod 级 stream。

## ConfigMap 字段

| key | 映射环境变量 | 建议值 |
|---|---|---|
| `crawler_debug_mode` | `CRAWLER_DEBUG_MODE` | `false` |
| `debug_fetch_queue_stream_template` | `DEBUG_FETCH_QUEUE_STREAM_TEMPLATE` | `crawl:tasks:debug:{node_name}` |
| `debug_fetch_queue_group_template` | `DEBUG_FETCH_QUEUE_GROUP_TEMPLATE` | `crawler-executor-debug:{node_name}` |
| `debug_fetch_queue_consumer_template` | `DEBUG_FETCH_QUEUE_CONSUMER_TEMPLATE` | `${NODE_NAME}-${POD_NAME}-debug` |
| `debug_attempt_tier` | `DEBUG_ATTEMPT_TIER` | `debug` |

T030 才实现 debug 模式切换逻辑；T012 只固定命名契约。

## Fetch Command 上下文

写入 debug stream 的 Fetch Command 必须满足：

| 字段 | 要求 |
|---|---|
| `url` | 目标 URL。 |
| `canonical_url` | 规范化 URL。 |
| `job_id` | 必须可识别为 debug 任务，建议格式 `debug:<node_name>:<ticket_or_session>`。 |
| `command_id` | 建议格式 `debug:<node_name>:<sequence>`。 |
| `trace_id` | 必须关联一次调试会话，建议格式 `debug:<node_name>:<yyyyMMddHHmmss>`。 |
| `tier` | 必须为 `debug`。 |

debug `crawl_attempt` 仍发布到正式 `KAFKA_TOPIC_CRAWL_ATTEMPT`。下游第五类必须按 `tier=debug` 过滤、隔离或标记，不得把 debug attempt 当作普通生产事实投影。

## 切换与恢复

目标集群调试时应采用以下配置切换原则：

1. 只让目标 node / pod 进入 `CRAWLER_DEBUG_MODE=true`。
2. debug 模式下运行时配置应等价于：
   - `FETCH_QUEUE_STREAM=crawl:tasks:debug:<NODE_NAME>`
   - `FETCH_QUEUE_GROUP=crawler-executor-debug:<NODE_NAME>`
   - `FETCH_QUEUE_CONSUMER=${NODE_NAME}-${POD_NAME}-debug`
3. 调试结束后恢复：
   - `CRAWLER_DEBUG_MODE=false`
   - `FETCH_QUEUE_STREAM=crawl:tasks`
   - `FETCH_QUEUE_GROUP=crawler-executor`
   - `FETCH_QUEUE_CONSUMER=${NODE_NAME}-${POD_NAME}`
4. 恢复生产前必须确认目标 debug stream 无未解释的 PEL，或明确接受其后续清理策略。

## 验证要求

后续 T030-T032 / T040 必须验证：

- 目标 node 只消费 `crawl:tasks:debug:<node_name>`。
- 非目标 node 不消费该 debug stream。
- debug `crawl_attempt` 保留 `tier=debug`、`job_id`、`trace_id`。
- 调试结束后 pod 恢复生产 stream / group / consumer 命名。
