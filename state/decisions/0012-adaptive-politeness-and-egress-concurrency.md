# ADR-0012: 自适应 Politeness 与出口并发控制边界

**状态**：已接受
**日期**：2026-04-30

## 背景

004 目标集群资源准备过程中识别到：当前 crawler-executor 已具备 Redis Streams 只读消费、对象存储和 `crawl_attempt` producer 基础，但生产上线前还缺少面向大出口 IP 池的防封和并发控制模型。

业务侧没有承诺对单一 host 的最大请求速率，因此本系统不能把问题简化为“配置一个静态 per-host rate cap”。真正的运行目标是：

- 在有限出口 IP 下尽量提高有效抓取吞吐。
- 避免单个出口 IP、单个 host、单个 ASN 分桶被快速打坏。
- 根据 429、CAPTCHA / challenge、反爬 200 页、连接失败、timeout、5xx 等反馈动态退避。
- 不把本地调速能力扩展成 URL 选择、优先级重排或长期 Host / ASN 画像事实。

该能力会触碰既有边界：

- ADR-0003 要求 Redis 队列写入侧归第六类，本系统只读消费，不写 URL 队列。
- 架构文档旧表述默认“按 Host 粘性选择出口 IP”，容易被理解为 `host -> 1 IP` 的静态模型。
- P2 Redis Streams 的 PEL 语义要求不能无限预读后把 pending 当成本地调度队列。

## 决策

生产方向采用 **自适应 Politeness + 出口并发控制**，而不是静态 per-host rate cap。

### 1. IP 选择策略

`STICKY_BY_HOST` 保留为 P0 / staging / 历史验证策略，不作为生产终态默认。

生产方向采用 host-aware sticky pool：

```text
host -> K 个候选 egress identity
```

worker 在该候选池内轮转或择优选择出口，避免单 host 锁死到一个 IP，同时保持源站视角下的可控分散度。

源站可见的出口身份应优先使用 public egress IP；如果第一版缺少 private IP 到 public IP 的映射表，可暂用 bind private IP 作为近似 key，但日志、指标和后续任务必须保留补齐映射的空间。

### 2. Scrapy 并发模型

新 spec 应优先复用 Scrapy downloader slot 机制，第一层最小实现为：

```python
request.meta["download_slot"] = f"{host}@{egress_identity}"
```

`CONCURRENT_REQUESTS_PER_DOMAIN` 不再作为单 host 生产并发的主要上限。单 host 的有效并发由 sticky-pool 大小、per-(host, ip) pacer、per-IP token / cooldown、host 级退避和全局并发共同决定。

### 3. 反馈维度

软封禁和退避必须按维度区分，不得混成“有错就退避”：

| 信号模式 | 触发维度 | 行为 |
|---|---|---|
| 同一 `(host, egress_ip)` 突发 429 / CAPTCHA / challenge | `(host, egress_ip)` | 指数退避或拉长 pacer 间隔。 |
| 同一 `egress_ip` 在多个 host 上集中出现 challenge | `egress_ip` | IP 级 cooldown / token 收缩。 |
| 同一 `host` 在多个 egress IP 上集中出现 challenge | `host` | host 级整体降速。 |
| 同一 `host` 在同一 ASN / CIDR 分桶内集中出现 challenge | `(host, asn)` 或 `(host, cidr)` | ASN / CIDR 分桶软上限；先作为 P2 能力。 |

HTTP 429、明确 CAPTCHA / challenge、HTTP 200 但 body 是反爬页、连接失败、timeout、5xx 的权重和退避维度应可配置，不得一概等价。

### 4. 允许的执行态写入

ADR-0003 仍然有效：crawler-executor 不得向 URL 队列写入新任务，不得 enqueue outlinks，不得维护第六类 URL 去重，不得重排第六类业务优先级。

为实现短窗口执行安全，允许 crawler-executor 写入以下运行态，但必须满足 TTL、命名空间隔离和非事实化约束：

- `(host, egress_ip)` 短窗口 backoff / next-allowed-at。
- `egress_ip` 短窗口 cooldown。
- `host` 短窗口 soft slowdown。
- `(host, asn)` / `(host, cidr)` 短窗口 soft limit。
- 执行态 heartbeat / 指标辅助状态。

这些写入只能用于执行层安全控制，不得表达 URL 选择、抓取优先级、重抓窗口、去重结果或长期画像事实。长期 Host / IP / ASN 画像仍归第五类。

### 5. PEL 与本地延迟边界

本地 pacer / delayed buffer 必须有容量上限和时间上限。

worker 不得无限 `XREADGROUP` 后把不 eligible 的消息长期留在本地 delayed buffer；当本地 buffer 达到上限时，worker 必须停止读取新消息。新 spec 必须定义：

- `local_buffer_capacity`。
- `max_local_delay_seconds`。
- buffer 满时的 `XREADGROUP` 停止规则。
- delayed 消息与 PEL / reclaim 的观测方式。

该规则防止 Redis Streams PEL 被误用为不可见的本地调度队列。

### 6. ASN / CIDR 边界

执行器可以做轻量 ASN / CIDR 观测：

- metrics 按 ASN / CIDR 分桶聚合 challenge rate、soft-ban rate、5xx rate。
- 可选启用 `(host, asn)` 短窗口软上限。

执行器不得自动切换云厂商、切换 ASN、购买 / 释放 IP 段或沉淀长期 ASN 画像事实。这些属于运维、控制平面或第五类画像职责。

## 备选方案

- **静态 per-host rate cap**：不采纳为主模型。业务侧没有提供单 host 最大请求速率承诺，静态值只能作为 fallback，不能承担生产自适应防封目标。
- **继续 `STICKY_BY_HOST = host -> 1 IP`**：不采纳为生产方向。大 IP 池下会结构性浪费出口资源，单 host 并发被锁死。
- **由第六类完全负责 host-aware 混排，执行器不做本地防封**：不采纳。上游混排有价值，但执行器仍需防止局部高并发、IP 信誉受损和反馈滞后。
- **执行器全局重排 URL 或写回延迟队列**：不采纳。会把第六类调度职责带回第二类，违反 ADR-0003 / ADR-0010。
- **把 Host / ASN 画像事实放入本仓库**：不采纳。长期画像和事实层归第五类。

## 后果

- 好处：把生产目标从静态合规限速转为观测驱动的防封闭环。
- 好处：在大 IP 池下，sticky-pool 能提升单 host 可用并发，同时比全随机更可控。
- 好处：对 `(host, ip)`、`ip`、`host`、`host, asn` 的不同退避语义做出明确分层，降低过度退避或退避不足的风险。
- 好处：保留 ADR-0003 / ADR-0010 的职责边界，避免第二类重新变成调度系统或事实层。
- 代价：实现复杂度高于静态 `DOWNLOAD_DELAY` / `CONCURRENT_REQUESTS_PER_DOMAIN`。
- 代价：需要新增指标、验证脚本和 PEL / local buffer 边界测试。
- 代价：如果缺少 private-to-public egress 映射，第一版只能用 bind IP 近似出口身份，指标解释需要谨慎。

## 关联

- ADR-0003
- ADR-0004
- ADR-0006
- ADR-0010
- ADR-0011
- `.specify/memory/architecture.md`
- `state/roadmap.md`
- 待新建 spec：自适应 Politeness 与出口并发控制
