# 研究记录：M3a 自适应 Politeness 与出口并发控制

## 1. Sticky-pool 选择算法

**决策**：采用稳定 hash / rendezvous hash 生成 `host -> K egress_identity` 候选池。

**理由**：

- 同一 host 的候选池在进程重启后稳定，便于排障和指标解释。
- IP 池新增 / 删除时，只影响部分 host，不会全量洗牌。
- K 可按环境调优：小 K 更保守，大 K 更偏吞吐。

**被拒绝方案**：

- `host -> 1 IP`：大 IP 池利用率差，单 host 并发被锁死。
- 全随机 IP：吞吐更高但不可控，源站视角下更像异常散射。
- 第六类完全负责 host 混排：上游混排仍有价值，但执行器必须能处理局部反馈和出口健康。

## 2. Scrapy downloader slot

**决策**：第一版使用 `request.meta["download_slot"] = f"{host}@{egress_identity}"`，把 Scrapy slot 从 host 维度扩展到 `(host, egress_identity)` 维度。

**理由**：

- 复用 Scrapy 原生 slot / delay / concurrency 机制，侵入面小。
- 单 host 可以在 K 个 egress identity 上形成 K 个 slot，避免被 `CONCURRENT_REQUESTS_PER_DOMAIN` 锁死。
- 与 ADR-0012 一致，先不重写 Scrapy scheduler。

**注意**：

- `CONCURRENT_REQUESTS_PER_DOMAIN` 仍可能作为 fallback 或保护阈值存在，但不能作为生产主并发模型。
- `DOWNLOAD_DELAY` 可作为基础 fallback；真实 pacing 应来自 `(host, egress_identity)` 状态。

## 3. Pacer 与 delayed buffer

**决策**：pacer 在 Fetch Command 已读入后、真正发起 Scrapy Request 前判断 eligible；不 eligible 的消息进入本地 delayed buffer。

**理由**：

- 只有读到 Fetch Command 后才能知道 URL host 与调度上下文。
- Redis Streams 没有原生 negative ack / release pending 语义。
- 本地 buffer 能在不写回第六类队列的前提下等待短窗口 pacing。

**边界**：

- buffer 必须有容量上限，达到上限时停止 `XREADGROUP`。
- buffer 必须有最大等待时间，超限时记录指标和日志，不发布虚假 `crawl_attempt`，不 `XACK`。
- worker 停机时，buffer 中未执行消息留 PEL，由后续 reclaim。

**被拒绝方案**：

- 写回延迟队列：会把第六类调度职责带回第二类。
- 立即发布 skipped / deferred attempt：没有真实抓取，不应污染 `crawl_attempt` 事实。
- 无限本地 buffer：会把 PEL 变成不可见调度队列。

## 4. Soft-ban 信号分类

**决策**：将 response / exception 归一化为 `FeedbackSignal`，再映射到不同退避维度。

第一版信号：

| 信号 | 来源 | 默认维度 | 说明 |
|---|---|---|---|
| `http_429` | HTTP status | `(host, egress_identity)` | 强防封信号。 |
| `captcha_challenge` | body pattern / title / header | `(host, egress_identity)`，聚合后可触发 IP / host | 强防封信号。 |
| `anti_bot_200` | HTTP 200 body pattern | `(host, egress_identity)`，聚合后可触发 IP / host | 需要可配置 pattern，避免误判。 |
| `timeout` | download exception | `(host, egress_identity)` | 中等权重，避免把网络抖动等同封禁。 |
| `connection_failed` | download exception | `egress_identity` 或 `(host, egress_identity)` | 需区分本地出口故障与源站连接失败。 |
| `http_5xx` | HTTP status | `(host, egress_identity)` | 低到中等权重，避免源站故障导致过度 cooldown。 |

**理由**：

- 同一 `(host, ip)` 出现 429 / challenge 多数是该出口访问该 host 过密。
- 同一 IP 跨 host 出现 challenge 更像 IP 信誉受损。
- 同一 host 跨 IP 出现 challenge 更像源站全局收紧。

## 5. Redis 执行态

**决策**：使用 Redis / Valkey 保存 TTL 短窗口执行安全状态，前缀默认 `crawler:exec:safety`。

**理由**：

- P2 已有 Redis 依赖；执行态可以跟队列 Redis 共用或独立配置。
- 多 worker / 重启后需要短窗口状态继续生效。
- TTL 和命名空间隔离能守住 ADR-0003 / ADR-0010 边界。

**边界**：

- 不写 URL queue / scheduler queue / dupefilter / priority。
- 不存长期 Host / IP / ASN profile。
- key 内建议使用 host hash 和 egress identity hash，指标可按 hash 聚合，排障需要原始映射时从日志或当前进程内上下文关联。

## 6. ASN / CIDR

**决策**：005 第一版把 ASN / CIDR 作为 P2 控制能力：先支持指标分桶和可选 soft limit，不做云资源自动化。

**理由**：

- 自动切换 ASN / IP 段属于运维、控制平面或云资源编排，不属于第二类执行器。
- 轻量分桶观测能帮助发现“同一 ASN 对某 host 集中受限”的风险。
- MaxMind GeoLite2-ASN 或等价静态映射可后续接入，不阻塞 P1 能力。

## 7. Public egress IP 映射

**决策**：优先使用 public egress IP 作为 `egress_identity`；如果当前目标节点无法提供 private-to-public 映射，第一版允许使用 bind private IP 近似。

**理由**：

- 源站真实看到的是 public egress IP，长期必须以 public 身份为准。
- 目标 OKE 节点当前已能看到大量本地 IPv4，但不一定能在 pod 内拿到 EIP 映射。
- 为了不阻塞 M3a，可以先用 bind IP，但必须通过 `egress_identity_type` 暴露局限。

## 8. 参数化策略

**决策**：005 先通过 env / ConfigMap 参数化，不实现控制平面运行时下发。

**理由**：

- 控制平面属于 M4；005 的目标是补齐生产前功能缺口。
- env / ConfigMap 足以支撑目标节点验证和 004 恢复。
- 参数命名应为后续控制平面字段预留稳定语义。
