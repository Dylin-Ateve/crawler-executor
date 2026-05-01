# 实施计划：M3a 自适应 Politeness 与出口并发控制

**分支**：`005-m3a-adaptive-politeness-egress-concurrency`
**日期**：2026-04-30
**规格文档**：`specs/005-m3a-adaptive-politeness-egress-concurrency/spec.md`

## 摘要

005 在 P2 只读消费与 P1 `crawl_attempt` producer 已验证的基础上，补齐生产上线前必须具备的防封和出口并发控制能力。核心变化是把 P0 / 历史回退口径的 `STICKY_BY_HOST = host -> 1 IP` 和静态 `DOWNLOAD_DELAY` / `CONCURRENT_REQUESTS_PER_DOMAIN`，演进为 host-aware sticky-pool、per-(host, egress_identity) downloader slot、短窗口 pacer、IP cooldown、host slowdown、软封禁反馈和本地有界 delayed buffer。

005 不恢复 004 的 K8s DaemonSet 部署验证；它为 004 恢复提供功能前置条件。

## 技术上下文

**语言/版本**：Python 3.9+
**主要依赖**：Scrapy、Redis / Valkey client、Prometheus client、Kafka client、OCI SDK
**存储**：Redis / Valkey 存短窗口执行安全状态；OCI Object Storage 和 Kafka 沿用 P1 / P2
**测试**：pytest、Redis 集成测试、可控 HTTP test server、目标节点验证脚本
**目标平台**：Linux crawler node；后续 004 恢复后运行在 K8s `hostNetwork` pod
**项目类型**：抓取执行数据管道
**性能目标**：不承诺 30-50 pages/sec 压测收口；本阶段验证在大 IP 池下策略正确、状态有界、可观测
**约束**：不写 URL 队列；不重排第六类业务优先级；不持有长期 Host / IP / ASN 画像；`crawl_attempt` 发布成功后才 `XACK`
**规模/范围**：按单 node 50-70 个本地出口 IPv4 设计；sticky-pool K 可配置

## 门禁检查

| 门禁 | 来源 | 结果 | 说明 |
|---|---|---|---|
| 章程门禁 | `.specify/memory/constitution.md` | 通过 | 先沉淀 ADR-0012，再创建 005。 |
| 产品门禁 | `.specify/memory/product.md` | 通过 | 005 只做短窗口执行安全控制，不做业务级调度决策。 |
| 架构门禁 | `.specify/memory/architecture.md` | 通过 | 符合 host-aware sticky-pool、自适应 politeness、短窗口状态和只读队列边界。 |
| 决策门禁 | `state/decisions/` | 通过 | 遵守 ADR-0003、ADR-0004、ADR-0006、ADR-0010、ADR-0012。 |
| 路线图对齐 | `state/roadmap.md` | 通过 | 对应 M3a；004 暂停，005 完成后再恢复。 |

## 项目结构

### 文档

```text
specs/005-m3a-adaptive-politeness-egress-concurrency/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── runtime-env.md
│   ├── redis-execution-state.md
│   └── metrics.md
└── tasks.md
```

### 预期源码 / 测试结构

```text
src/crawler/crawler/
├── egress_identity.py          # egress identity 映射、hash、候选池输入
├── egress_policy.py            # sticky-pool 与出口选择
├── fetch_safety_state.py       # Redis 短窗口执行安全状态
├── politeness.py               # pacer、backoff、delayed buffer
├── response_signals.py         # soft-ban / challenge / 反爬页信号归一化
├── metrics.py                  # 新增执行安全指标
├── middlewares.py              # LocalIpRotationMiddleware / response feedback 集成
└── spiders/fetch_queue.py      # delayed buffer 与 XREADGROUP 反压集成

deploy/scripts/
├── run-m3a-sticky-pool-validation.sh
├── run-m3a-pacer-validation.sh
├── run-m3a-soft-ban-feedback-validation.sh
├── run-m3a-delayed-buffer-validation.sh
└── run-m3a-redis-boundary-validation.sh

tests/
├── unit/
└── integration/
```

**结构决策**：优先新增小模块，避免把 sticky-pool、pacer、Redis 状态和 response classifier 全部塞进现有 middleware。现有 `LocalIpRotationMiddleware` 可作为集成点，但不承担全部策略复杂度。

## 关键设计约束

### 1. 出口身份与 sticky-pool

- `egress_identity` 是源站视角的出口身份 key，优先 public egress IP。
- 第一版若缺少 public 映射，可以使用 bind private IP，必须暴露 `egress_identity_type=bind_ip`。
- sticky-pool 采用稳定 hash / rendezvous hash 选择 K 个候选身份，减少 IP 池变动导致的全量洗牌。
- 选择时先过滤 IP cooldown，再考虑 `(host, egress_identity)` backoff 和 host slowdown。

### 2. Scrapy slot 与 pacer

- Request 的 `download_slot` 必须扩展到 `(host, egress_identity)`。
- pacer 在实际发起下载前生效，控制同一 `(host, egress_identity)` 的最小请求间隔。
- `CONCURRENT_REQUESTS_PER_DOMAIN` 保留为 fallback，不再作为生产单 host 主并发上限。

### 3. Local delayed buffer

- 已从 Redis Stream 读入但暂未 eligible 的消息进入本地 delayed buffer。
- buffer 有容量上限和最大等待时间。
- buffer 满时停止 `XREADGROUP`，避免把 PEL 误用为隐藏调度队列。
- delayed 消息未执行或未成功发布 `crawl_attempt` 时不得 `XACK`。

### 4. Redis 执行态

- 允许写入 `EXECUTION_STATE_REDIS_PREFIX` 下的 TTL 状态。
- 不允许写 URL queue、outlink queue、scheduler queue、dupefilter、priority 或 profile key。
- Redis 执行态写入失败时，应记录指标；不得伪造成功抓取事实。

### 5. Soft-ban feedback

- 429 / challenge 优先触发 `(host, egress_identity)` backoff。
- 同一 egress identity 跨 host 集中 challenge 触发 IP cooldown。
- 同一 host 跨 egress identity 集中 challenge 触发 host slowdown。
- ASN / CIDR 第一版先做指标和可选 soft limit，不自动切换云资源。

## 复杂度跟踪

| 例外项 | 必要原因 | 未采纳更简单方案的原因 |
|---|---|---|
| sticky-pool 而非 host -> 1 IP | 大 IP 池下需要提升单 host 可用并发，同时保持可控分散度 | `STICKY_BY_HOST` 会结构性浪费 IP 池 |
| downloader slot 切到 host@ip | 复用 Scrapy 原生 slot，降低侵入性 | 重写调度器更复杂，也容易触碰第六类边界 |
| 本地 delayed buffer | Redis Streams 已读消息会进入 PEL，pacer 必须有本地等待位置 | 写回延迟队列会违反 ADR-0003，直接失败会制造虚假 crawl_attempt |
| Redis TTL 执行态 | 多 worker / 多进程需要短窗口状态共享和重启后有限保留 | 仅内存状态无法支撑 worker 重启和同 node 多进程场景 |
| soft-ban 多维度退避 | 不同封禁信号含义不同，混合退避会过度或不足 | “有错就退避”无法解释 IP 池枯竭或单 host 降速 |

## 实施阶段

1. 规格与契约：收口 runtime env、Redis key、metrics 契约和验证口径。
2. 纯逻辑层：实现 egress identity、sticky-pool、pacer、feedback classifier 的单元可测模块。
3. Redis 执行态：实现 TTL 状态读写、key namespace 和边界审计。
4. Scrapy 集成：将出口选择、download_slot、pacer、delayed buffer 接入 fetch queue spider / middleware。
5. 指标与验证脚本：补齐 Prometheus 指标、Redis key diff、PEL / buffer 验证脚本。
6. 文档收口：更新 004 恢复条件和现状层，准备恢复 K8s 部署验证。

## 后续计划约束

- 005 完成后，004 的 ConfigMap 必须从生产默认中移除 `IP_SELECTION_STRATEGY=STICKY_BY_HOST`，改用 005 的生产策略参数。
- 若 005 实现发现必须写入非 TTL 状态或长期画像事实，必须先新增 ADR，再继续。
- 若 private-to-public egress 映射短期无法提供，目标验证报告必须明确指标中的出口身份是 bind private IP 近似值。
