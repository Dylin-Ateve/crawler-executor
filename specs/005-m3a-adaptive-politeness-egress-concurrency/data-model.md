# 数据模型：M3a 自适应 Politeness 与出口并发控制

本文档描述 005 内部执行态模型。所有模型均属于短窗口运行态，不是第五类长期事实层。

## 1. EgressIdentity

执行器用于表示源站可见出口身份的逻辑 key。

| 字段 | 说明 |
|---|---|
| `identity` | 出口身份值。优先 public egress IP；fallback 为 bind private IP。 |
| `identity_hash` | 指标和 Redis key 使用的稳定 hash。 |
| `identity_type` | `public_ip`、`bind_ip`、`unknown`。 |
| `bind_ip` | 本地绑定 IPv4。 |
| `public_ip` | 可选，private-to-public 映射存在时填写。 |
| `interface` | 来源网卡，例如 `enp0s5`。 |
| `asn` | 可选，ASN 分桶。 |
| `cidr` | 可选，CIDR 分桶。 |
| `status` | `active`、`cooling_down`、`excluded`。 |

约束：

- `identity_hash` 不得用于长期画像事实。
- 当 `identity_type=bind_ip` 时，验证报告必须说明这是 public 出口身份的近似值。

## 2. StickyPoolAssignment

host 到候选出口身份集合的稳定映射。

| 字段 | 说明 |
|---|---|
| `host` | canonical host。 |
| `host_hash` | Redis key / metrics label 使用的稳定 hash。 |
| `pool_size_requested` | 配置的 K。 |
| `pool_size_actual` | 实际可用候选数量。 |
| `candidate_identity_hashes` | 候选出口身份 hash 列表。 |
| `selection_strategy` | `sticky_pool`、`sticky_by_host`、`round_robin` 等。 |
| `generated_at_ms` | 生成时间。 |

约束：

- production profile 必须使用 `sticky_pool`。
- `sticky_by_host` 仅用于 P0 / staging / 回退。

## 3. HostIpPacerState

`(host, egress_identity)` 维度的短窗口 pacing / backoff 状态。

| 字段 | 说明 |
|---|---|
| `host_hash` | host hash。 |
| `identity_hash` | egress identity hash。 |
| `next_allowed_at_ms` | 下一次允许启动请求的时间。 |
| `min_delay_ms` | 当前最小间隔。 |
| `backoff_level` | 指数退避级别。 |
| `last_signal` | 最近反馈信号。 |
| `last_started_at_ms` | 最近一次请求启动时间。 |
| `last_updated_at_ms` | 状态更新时间。 |
| `ttl_seconds` | Redis TTL。 |

状态转换：

```text
eligible -> request_started -> success -> eligible
eligible -> request_started -> soft_ban_signal -> backoff
backoff -> now >= next_allowed_at -> eligible
```

## 4. EgressCooldownState

单个出口身份的短窗口 cooldown。

| 字段 | 说明 |
|---|---|
| `identity_hash` | egress identity hash。 |
| `reason` | `cross_host_challenge`、`connection_failure`、`manual` 等。 |
| `cooldown_until_ms` | 冷却结束时间。 |
| `trigger_count` | 当前窗口触发次数。 |
| `window_started_at_ms` | 统计窗口开始时间。 |
| `last_updated_at_ms` | 更新时间。 |
| `ttl_seconds` | Redis TTL。 |

状态转换：

```text
active -> threshold_reached -> cooling_down
cooling_down -> now >= cooldown_until -> probe_allowed
probe_allowed -> success -> active
probe_allowed -> soft_ban_signal -> cooling_down
```

## 5. HostSlowdownState

host 级整体降速状态。

| 字段 | 说明 |
|---|---|
| `host_hash` | host hash。 |
| `reason` | `multi_ip_challenge`、`manual` 等。 |
| `slowdown_factor` | 对 min delay / backoff 的乘数。 |
| `slowdown_until_ms` | 降速结束时间。 |
| `trigger_count` | 当前窗口触发次数。 |
| `last_updated_at_ms` | 更新时间。 |
| `ttl_seconds` | Redis TTL。 |

约束：

- host slowdown 不能表达业务抓取频率决策，只能表达执行安全退避。
- 不得在该状态中存长期 Host 画像字段。

## 6. HostAsnSoftLimitState

可选 P2 控制能力；005 第一版可只输出指标。

| 字段 | 说明 |
|---|---|
| `host_hash` | host hash。 |
| `asn` | ASN 编号。 |
| `cidr` | 可选 CIDR 分桶。 |
| `limit_factor` | 对该分桶的降速系数。 |
| `limit_until_ms` | soft limit 结束时间。 |
| `last_updated_at_ms` | 更新时间。 |
| `ttl_seconds` | Redis TTL。 |

## 7. FeedbackSignal

从 response / exception / body pattern 归一化出的短窗口反馈。

| 字段 | 说明 |
|---|---|
| `signal_type` | `http_429`、`captcha_challenge`、`anti_bot_200`、`timeout`、`connection_failed`、`http_5xx`、`success`。 |
| `host` | canonical host。 |
| `host_hash` | host hash。 |
| `identity_hash` | egress identity hash。 |
| `status_code` | HTTP status，可为空。 |
| `matched_pattern` | 可选，body pattern id，不存完整 body。 |
| `weight` | 退避权重。 |
| `observed_at_ms` | 观察时间。 |
| `attempt_id` | 当前 attempt id，用于日志关联。 |

约束：

- 不得把完整响应 body 写入 Redis 执行态。
- `matched_pattern` 只记录 pattern id 或类别。

## 8. LocalDelayedFetchCommand

已读入 PEL、尚未 eligible 或尚未启动下载的本地待执行命令。

| 字段 | 说明 |
|---|---|
| `stream_message_id` | Redis Stream message id。 |
| `command_id` | Fetch Command command id。 |
| `job_id` | Fetch Command job id。 |
| `canonical_url` | canonical URL。 |
| `host` | canonical host。 |
| `host_hash` | host hash。 |
| `selected_identity_hash` | 当前选择的出口身份 hash。 |
| `eligible_at_ms` | 下一次可尝试启动时间。 |
| `read_at_ms` | 从 Redis Stream 读入时间。 |
| `delay_reason` | `host_ip_pacer`、`ip_cooldown`、`host_slowdown`、`no_candidate`。 |
| `attempt_count_local` | 本地重试选择次数，不等同 Redis `times_delivered`。 |

状态转换：

```text
read_from_stream -> delayed -> eligible -> request_scheduled
delayed -> shutdown -> remains_in_pel
delayed -> max_delay_exceeded -> alerting_and_backpressure
request_scheduled -> crawl_attempt_published -> xack
request_scheduled -> kafka_publish_failed -> remains_in_pel
```

## 9. RuntimePolicy

005 运行策略配置。

| 字段 | 默认建议 | 说明 |
|---|---:|---|
| `EGRESS_SELECTION_STRATEGY` | `STICKY_POOL` | 生产默认。 |
| `STICKY_POOL_SIZE` | `4` | 每 host 候选出口身份数量。 |
| `HOST_IP_MIN_DELAY_MS` | `2000` | `(host, ip)` 最小间隔。 |
| `HOST_IP_JITTER_MS` | `500` | pacing jitter。 |
| `HOST_IP_BACKOFF_BASE_MS` | `5000` | 指数退避基础值。 |
| `HOST_IP_BACKOFF_MAX_MS` | `300000` | `(host, ip)` 最大退避。 |
| `IP_COOLDOWN_SECONDS` | `1800` | IP cooldown 时长。 |
| `HOST_SLOWDOWN_SECONDS` | `600` | host slowdown 时长。 |
| `LOCAL_DELAYED_BUFFER_CAPACITY` | `100` | 本地 delayed buffer 上限。 |
| `MAX_LOCAL_DELAY_SECONDS` | `300` | 本地最大等待时间。 |
| `EXECUTION_STATE_MAX_TTL_SECONDS` | `86400` | Redis 执行态最大 TTL。 |

这些默认值是 005 第一版验证建议，生产上线前必须结合目标源站反馈继续调优。
