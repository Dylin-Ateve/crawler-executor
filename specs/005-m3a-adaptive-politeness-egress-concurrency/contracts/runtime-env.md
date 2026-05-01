# 运行参数契约：M3a 自适应 Politeness 与出口并发控制

本文档定义 005 新增或重解释的非敏感运行参数。真实凭据仍按 004 / P2 Secret 契约注入。

## 出口身份与选择

| 环境变量 | 建议值 | 说明 |
|---|---|---|
| `EGRESS_SELECTION_STRATEGY` | `STICKY_POOL` | production / staging 默认。允许 `STICKY_BY_HOST` 仅用于 P0 / 显式回退。 |
| `STICKY_POOL_SIZE` | `4` | 每个 host 的候选出口身份数量 K。 |
| `EGRESS_IDENTITY_SOURCE` | `auto` | `public_ip`、`bind_ip`、`auto`。第一版缺少映射时 fallback 到 bind IP。 |
| `EGRESS_IDENTITY_MAP_FILE` | 空 | 可选 private-to-public IP 映射文件路径。 |
| `EGRESS_IDENTITY_HASH_SALT` | 环境填写 | 用于 host / identity hash 的非敏感 salt；不得是凭据。 |
| `ALLOW_BIND_IP_AS_EGRESS_IDENTITY` | `true` | 是否允许缺少 public 映射时使用 bind IP 近似。 |

## Pacing 与 backoff

| 环境变量 | 建议值 | 说明 |
|---|---:|---|
| `HOST_IP_MIN_DELAY_MS` | `2000` | 同一 `(host, egress_identity)` 请求启动最小间隔。 |
| `HOST_IP_JITTER_MS` | `500` | pacing jitter 上限。 |
| `HOST_IP_BACKOFF_BASE_MS` | `5000` | `(host, egress_identity)` 指数退避基础值。 |
| `HOST_IP_BACKOFF_MAX_MS` | `300000` | `(host, egress_identity)` 最大退避。 |
| `HOST_IP_BACKOFF_MULTIPLIER` | `2.0` | 指数退避倍数。 |
| `IP_COOLDOWN_SECONDS` | `1800` | egress identity cooldown 时长。 |
| `HOST_SLOWDOWN_SECONDS` | `600` | host 级 slowdown 时长。 |
| `HOST_SLOWDOWN_FACTOR` | `3.0` | host slowdown 下对 delay / backoff 的乘数。 |

## Local delayed buffer

| 环境变量 | 建议值 | 说明 |
|---|---:|---|
| `LOCAL_DELAYED_BUFFER_CAPACITY` | `100` | 本地 delayed Fetch Command 容量上限。 |
| `MAX_LOCAL_DELAY_SECONDS` | `300` | 单条 delayed 消息最大等待时间。 |
| `LOCAL_DELAYED_BUFFER_POLL_MS` | `500` | recheck eligible 的轮询间隔。 |
| `STOP_READING_WHEN_DELAYED_BUFFER_FULL` | `true` | buffer 满时停止 `XREADGROUP`。生产必须为 `true`。 |

## Soft-ban 信号

| 环境变量 | 建议值 | 说明 |
|---|---:|---|
| `SOFT_BAN_WINDOW_SECONDS` | `300` | soft-ban 信号聚合窗口。 |
| `HOST_IP_SOFT_BAN_THRESHOLD` | `2` | `(host, ip)` 维度触发 backoff 的阈值。 |
| `IP_CROSS_HOST_CHALLENGE_THRESHOLD` | `3` | 同 IP 跨 host 触发 cooldown 的阈值。 |
| `HOST_CROSS_IP_CHALLENGE_THRESHOLD` | `3` | 同 host 跨 IP 触发 slowdown 的阈值。 |
| `HTTP_429_WEIGHT` | `3` | 429 信号权重。 |
| `CAPTCHA_CHALLENGE_WEIGHT` | `5` | CAPTCHA / challenge 信号权重。 |
| `ANTI_BOT_200_WEIGHT` | `4` | HTTP 200 反爬页信号权重。 |
| `HTTP_5XX_WEIGHT` | `1` | 5xx 信号权重。 |
| `TIMEOUT_WEIGHT` | `1` | timeout 信号权重。 |
| `CHALLENGE_BODY_PATTERNS` | 空 | 逗号分隔 pattern id 或简化正则；不得写入真实响应样本。 |
| `ANTI_BOT_200_PATTERNS` | 空 | 逗号分隔 pattern id 或简化正则。 |

## Redis 执行态

| 环境变量 | 建议值 | 说明 |
|---|---|---|
| `EXECUTION_STATE_REDIS_URL` | 空 | 可选；为空时复用 `REDIS_URL`，不得使用 Fetch Queue URL 除非明确允许。 |
| `EXECUTION_STATE_REDIS_PREFIX` | `crawler:exec:safety` | 所有 005 Redis 状态必须位于此前缀下。 |
| `EXECUTION_STATE_MAX_TTL_SECONDS` | `86400` | 所有执行态 key 最大 TTL。 |
| `EXECUTION_STATE_WRITE_ENABLED` | `true` | 是否启用 Redis 执行态写入；本地开发可关闭。 |
| `EXECUTION_STATE_FAIL_OPEN` | `true` | 状态写入失败时是否继续抓取并记录指标；生产默认 fail open，避免 Redis 抖动阻断全量抓取。 |

## ASN / CIDR

| 环境变量 | 建议值 | 说明 |
|---|---|---|
| `ASN_OBSERVABILITY_ENABLED` | `false` | 是否启用 ASN / CIDR 指标分桶。 |
| `ASN_DATABASE_PATH` | 空 | 可选 MaxMind GeoLite2-ASN 或等价数据库路径。 |
| `HOST_ASN_SOFT_LIMIT_ENABLED` | `false` | 是否启用 `(host, asn)` 短窗口 soft limit。第一版可只做指标。 |

## 生产配置约束

- production / staging profile 不得把 `EGRESS_SELECTION_STRATEGY` 设为 `STICKY_BY_HOST`。
- `STOP_READING_WHEN_DELAYED_BUFFER_FULL` 在 production 必须为 `true`。
- 所有正则 / pattern 参数必须可审计，不能包含真实凭据或敏感样本。
- `EXECUTION_STATE_REDIS_PREFIX` 必须与 URL 队列 key 前缀隔离。
