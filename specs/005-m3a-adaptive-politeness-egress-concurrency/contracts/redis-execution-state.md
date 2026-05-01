# Redis 执行态契约：M3a 自适应 Politeness 与出口并发控制

本文档定义 005 允许写入 Redis / Valkey 的短窗口执行安全状态。该契约是 ADR-0003 / ADR-0012 的可验证翻译。

## 总原则

- 所有 key 必须位于 `EXECUTION_STATE_REDIS_PREFIX` 下，默认 `crawler:exec:safety`。
- 所有 key 必须设置 TTL，且 TTL 不得超过 `EXECUTION_STATE_MAX_TTL_SECONDS`。
- key 与 value 不得表达 URL 选择、业务优先级、重抓窗口、去重结果或长期画像事实。
- key 内优先使用 `host_hash` / `identity_hash`，避免把长期画像语义沉淀到执行层。

## 允许 key

### `(host, egress_identity)` backoff

```text
{prefix}:host_ip:{host_hash}:{identity_hash}
```

建议类型：Redis Hash。

| 字段 | 说明 |
|---|---|
| `next_allowed_at_ms` | 下一次允许请求启动时间。 |
| `min_delay_ms` | 当前最小间隔。 |
| `backoff_level` | 当前退避级别。 |
| `last_signal` | 最近信号类型。 |
| `last_updated_at_ms` | 更新时间。 |

### egress identity cooldown

```text
{prefix}:ip:{identity_hash}
```

建议类型：Redis Hash。

| 字段 | 说明 |
|---|---|
| `cooldown_until_ms` | 冷却结束时间。 |
| `reason` | 冷却原因。 |
| `trigger_count` | 当前窗口触发次数。 |
| `last_updated_at_ms` | 更新时间。 |

### host slowdown

```text
{prefix}:host:{host_hash}
```

建议类型：Redis Hash。

| 字段 | 说明 |
|---|---|
| `slowdown_until_ms` | 降速结束时间。 |
| `slowdown_factor` | 降速系数。 |
| `reason` | 降速原因。 |
| `last_updated_at_ms` | 更新时间。 |

### `(host, asn)` / `(host, cidr)` soft limit

```text
{prefix}:host_asn:{host_hash}:{asn}
{prefix}:host_cidr:{host_hash}:{cidr_hash}
```

建议类型：Redis Hash。第一版可只实现指标，不写该 key。

| 字段 | 说明 |
|---|---|
| `limit_until_ms` | soft limit 结束时间。 |
| `limit_factor` | 降速系数。 |
| `reason` | 触发原因。 |
| `last_updated_at_ms` | 更新时间。 |

### signal window counter

```text
{prefix}:signal:{dimension}:{dimension_hash}:{signal_type}
```

建议类型：Redis String 或 Hash，使用 TTL 表达窗口。

| 字段 | 说明 |
|---|---|
| `count` | 窗口内累计次数。 |
| `weight_sum` | 窗口内权重累计。 |

### consumer safety heartbeat

```text
{prefix}:consumer:{consumer_name_hash}
```

建议类型：Redis Hash。

| 字段 | 说明 |
|---|---|
| `delayed_buffer_size` | 本地 delayed buffer 当前长度。 |
| `oldest_delayed_age_seconds` | 最老 delayed 消息年龄。 |
| `last_loop_at_ms` | 最近消费循环时间。 |
| `last_updated_at_ms` | 更新时间。 |

## 禁止 key / 禁止行为

005 不得写入或创建以下语义的 key：

- URL queue / scheduler queue。
- outlink queue。
- dupefilter / seen URL set。
- priority / score / rank。
- retry window / recrawl window。
- Host / Site 长期 profile。
- ASN / CIDR 长期信誉库。
- 第五类事实层投影。

## TTL 约束

| key 类型 | 建议 TTL | 上限 |
|---|---:|---:|
| `host_ip` | `EXECUTION_STATE_MAX_TTL_SECONDS` 内按 backoff 推导 | 24h |
| `ip` | `IP_COOLDOWN_SECONDS + SOFT_BAN_WINDOW_SECONDS` | 24h |
| `host` | `HOST_SLOWDOWN_SECONDS + SOFT_BAN_WINDOW_SECONDS` | 24h |
| `host_asn` / `host_cidr` | soft limit 时长 + window | 24h |
| `signal` | `SOFT_BAN_WINDOW_SECONDS` | 24h |
| `consumer` | `READINESS_MAX_HEARTBEAT_AGE_SECONDS * 3` 或等价短 TTL | 1h |

## 审计要求

验证脚本必须记录：

- 运行前后的 Redis key diff。
- 新增 key 是否全部位于 `EXECUTION_STATE_REDIS_PREFIX`。
- 新增 key 是否全部带 TTL。
- 是否出现禁止 key pattern。
- 目标 Fetch Queue stream `XLEN` 是否未因 executor 追加消息而变化。

允许的变化仅包括：

- Redis Streams consumer group / PEL / ack 协议状态。
- 005 执行安全 prefix 下的 TTL key。
- 既有 P0 IP health key，若该验证场景显式启用兼容路径。
