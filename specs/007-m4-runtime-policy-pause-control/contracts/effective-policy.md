# 契约：M4 Effective Policy

**状态**：草案  
**适用 spec**：`007-m4-runtime-policy-pause-control`  
**生产者**：M4 第一版为本地文件 / ConfigMap；未来为控制平面或第六类输出的 effective policy  
**消费者**：crawler-executor

## 设计原则

- 本契约描述已经解析好的 effective policy，不描述控制平面原始策略。
- executor 不实现策略优先级、策略合并、Host/Site 成员关系解析。
- 第一版只做精确匹配。
- 策略文件不得包含凭据。

## 示例

```json
{
  "schema_version": "1.0",
  "version": "policy-20260503-001",
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
        "paused": false,
        "host_ip_min_delay_ms": 5000,
        "sticky_pool_size": 3,
        "max_retries": 1
      }
    },
    {
      "scope_type": "policy_scope_id",
      "scope_id": "policy-scope-paused-001",
      "policy": {
        "paused": true,
        "pause_reason": "manual_pause"
      }
    }
  ]
}
```

## 匹配规则

对单条 Fetch Command，executor 按以下顺序精确匹配：

```text
policy_scope_id -> politeness_key -> host_id -> site_id -> tier -> default_policy
```

要求：

- 每个 `scope_type + scope_id` 在文档中最多出现一次。
- 如果重复出现，整个策略版本非法，必须拒绝加载。
- 不支持正则、通配符、URL pattern、标签表达式。
- `default_policy` 必须存在。

## 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema_version` | string | 是 | 第一版固定 `1.0`。 |
| `version` | string | 是 | 策略版本。 |
| `generated_at` | string | 是 | ISO-8601 UTC 时间。 |
| `default_policy` | object | 是 | 默认策略。 |
| `scope_policies` | array | 否 | 作用域策略。 |

## Policy 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `enabled` | boolean | 否 | `false` 第一版等价于暂停。 |
| `paused` | boolean | 否 | 是否暂停新请求。 |
| `pause_reason` | string | 否 | pause 原因。 |
| `egress_selection_strategy` | string | 否 | `STICKY_POOL` 等现有策略。 |
| `sticky_pool_size` | integer | 否 | sticky-pool K。 |
| `host_ip_min_delay_ms` | integer | 否 | `(host, egress_identity)` 最小间隔。 |
| `host_ip_jitter_ms` | integer | 否 | pacing jitter。 |
| `download_timeout_seconds` | integer | 否 | 下载超时。 |
| `max_retries` | integer | 否 | fetch 层重试 / 投递预算。 |
| `max_local_delay_seconds` | integer | 否 | 本地 delayed buffer 最大等待时间。 |

## 校验失败行为

策略加载失败时：

1. 不覆盖当前策略。
2. 继续使用 last-known-good。
3. 若没有 LKG，使用 bootstrap default policy。
4. 记录结构化日志和指标。
5. 不退出 worker。
