# 功能规格：Scrapy 分布式爬虫

**功能分支**：`001-scrapy-distributed-crawler`
**创建日期**：2026-04-27
**状态**：草稿
**输入来源**：`scrapy-distributed-crawler-feature.md`

## 用户场景与测试

## P0 范围

P0 对应原始文档中的“阶段 1：PoC 验证”。

P0 需要证明单个爬虫节点可以：

- 发现本机辅助 IPv4 地址；
- 将 Scrapy 出站请求绑定到这些本地地址；
- 按 Host 维度轮换或粘滞使用 IP；
- 通过 Redis 对异常的 Host/IP 组合执行冷却；
- 暴露足够指标，用于和当前 Heritrix 链路进行 24 小时对比。

P0 明确不包含生产 Kafka 扇出、PostgreSQL/ClickHouse 持久化、Terraform 自动化或多节点扩容。这些仍然是后续阶段的需求，并继续保留在本规格中。

## 已确认口径

- P0 在真实 Linux 爬虫节点上运行。
- 目标网卡暂按 `ens3` 配置，但实现必须支持通过配置调整网卡名。
- 每台节点约 44 个辅助 IP 的规模假设继续成立。
- 管理 IP 通过 `EXCLUDED_LOCAL_IPS` 固定配置，且必须支持多个管理 IP 排除。
- Redis 暂时不可用时，以爬虫继续执行任务为优先；worker 使用本地内存 fallback 维持已发现 IP 和本地冷却状态，同时记录告警或指标。
- P0 并发从保守值开始，暂定 `CONCURRENT_REQUESTS=32`、`CONCURRENT_REQUESTS_PER_DOMAIN=2`，后续根据实测逐步调优。
- P0 继续沿用原始验收目标：单节点 30 pages/sec、连续 24 小时、CPU < 50%、内存 < 4 GB。
- P0 错误率只记录，不设置硬性门槛。
- P0 可以使用公网 IP echo endpoint。
- P0 需要覆盖真实目标站点样例，例如 Wikipedia、White House 等经团队确认的公开站点。
- P0 和生产方向均忽略 robots.txt，但仍保留 politeness、并发上限和批准目标范围约束。
- IP 黑名单阈值确认：403/429/503 连续 5 次进入 Host/IP 冷却，冷却 1800 秒；captcha 单次命中立即进入 Host/IP 冷却。
- IP 选择策略确认：默认 `STICKY_BY_HOST`，`ROUND_ROBIN` 仅作为诊断模式。
- 抓取范围确认：允许发现站外链接，但不继续爬取站外链接，仅记录。
- 重爬策略确认：支持定期重爬，页面存储只保留最新快照。
- 下游解析服务设计暂不纳入当前阶段。
- Kafka 投递语义接受 at-least-once，并要求消费端幂等。
- 对象存储使用 Oracle Cloud Object Storage，bucket 名称为 `clawer_content_staging`；endpoint 后续补充。
- HTML、PostgreSQL 元数据和 ClickHouse 事件的保留周期暂不设计。
- Host 画像查询目标暂后置设计。
- 当前暂不定义 Heritrix 对比指标补充项。

### 用户故事 1 - 验证 Scrapy 多出口 IP 抓取链路（优先级：P0）

作为运维或研发人员，我需要单个爬虫节点通过多个本地出口 IP 抓取页面，以验证 Scrapy 是否可以替代当前单出口 IP 的 Heritrix 链路。

**优先级理由**：这是当前架构中风险最高的假设，会直接阻塞后续规模化扩展。

**独立测试**：在单节点上访问 IP echo endpoint，验证请求是否通过预期辅助 EIP 出口发出。

**验收场景**：

1. **假设** 爬虫节点已配置辅助 IP，**当** Scrapy worker 处理测试 URL，**则** 外部观测到的公网出口 IP 包含已配置的辅助 EIP。
2. **假设** 某个 Host/IP 组合持续失败，**当** 达到失败阈值，**则** 该组合进入冷却，后续流量选择其他可用 IP。
3. **假设** Redis 可用，**当** 多个请求访问同一 Host，**则** 配置的选择策略保持 Host/IP 映射稳定，除非该组合被拉黑。
4. **假设** Redis 暂时不可用，**当** worker 继续处理请求，**则** worker 优先继续执行爬虫任务，使用本地内存 fallback 维持已发现 IP 和本地冷却状态，并记录告警或指标。

### 用户故事 2 - 可靠持久化抓取结果（优先级：P1）

作为数据平台负责人，我需要将抓取到的 HTML 可靠存储，并向下游系统投递元数据，以确保 worker、数据库或消费者故障时抓取结果不丢失。

**优先级理由**：规模化抓取如果没有持久化存储和可重放元数据，会带来不可接受的数据丢失风险。

**独立测试**：抓取样例 URL，将压缩 HTML 写入对象存储，向 Kafka 发布元数据，并验证消费者可重放写入 PostgreSQL 和 ClickHouse。

### 用户故事 3 - 规模化运维分布式抓取（优先级：P2）

作为运维人员，我需要 Kubernetes 部署、健康检查、指标和告警，以便爬虫可跨多节点扩展并安全发布。

**优先级理由**：生产流量扩容前必须先具备分布式抓取行为的可观测性。

**独立测试**：部署小规模 DaemonSet，观察指标并执行滚动发布，验证队列、lag、错误和 IP 健康面板。

### 用户故事 4 - 分析 Host 抓取画像（优先级：P2）

作为分析或运维人员，我需要 Host 级抓取画像，以识别慢响应、被封、高错误率或外链增长异常的 Host。

**优先级理由**：Host 画像是明确业务能力，也会反向指导抓取策略调优。

**独立测试**：按 Host 查询近期 crawl events，验证成功率、延迟分位、错误分布、出口 IP 表现和 outlink 数量。

## 边界场景

- Redis 在请求调度或 IP 黑名单查询期间不可用。
- 对象存储上传成功后 Kafka 不可用。
- HTTP 响应成功后对象存储上传失败。
- 目标 Host 对所有本地 IP 都进入黑名单。
- Host 以 HTTP 200 返回 CAPTCHA 页面。
- 冷启动 URL 规模超过 Redis 内存预期。
- PostgreSQL 分区大小超过计划上限。
- 源站对整个子网或 ASN 限流。

## 需求

### 功能需求

- **FR-001**：新抓取链路必须使用 Scrapy worker 抓取页面，而不是继续使用 Heritrix。
- **FR-002**：系统必须支持将出站请求绑定到本地辅助 IP。
- **FR-003**：系统必须支持 Host 感知的 IP 选择，并在持续失败后执行冷却。
- **FR-003a**：P0 必须支持 `STICKY_BY_HOST` IP 选择策略，并可以将 `ROUND_ROBIN` 作为诊断模式。
- **FR-003b**：P0 必须将 Host/IP 黑名单状态存储在 Redis 中，并通过 TTL 自动恢复。
- **FR-003c**：P0 必须暴露请求数、状态码计数、响应延迟、活跃 IP 数和黑名单数量指标。
- **FR-003d**：P0 必须提供可重复执行的命令或脚本，用于验证外部观测到的出口 IP 分布。
- **FR-003e**：Redis 暂时不可用时，P0 必须优先继续执行抓取任务，并使用本地内存 fallback 维持短期 IP 健康状态。
- **FR-004**：系统必须先将压缩 HTML 写入对象存储，再发布下游元数据。
- **FR-005**：系统必须向 Kafka topic 发布页面元数据、抓取事件和解析任务。
- **FR-006**：系统必须将页面元数据和抓取日志持久化到 PostgreSQL 分区表。
- **FR-007**：系统必须将抓取事件写入 ClickHouse，用于 Host 画像分析。
- **FR-008**：系统必须暴露吞吐、失败、队列深度、Kafka lag 和 IP 健康等运维指标。
- **FR-009**：系统必须支持跨爬虫节点的 Kubernetes 部署。
- **FR-010**：系统必须基于 canonical URL 计算 `url_hash` 和 `dedupe_key`；canonicalization 必须忽略 fragment、query 参数顺序、Host 大小写、默认端口和尾斜杠等差异。
- **FR-011**：系统允许发现站外链接，但不得继续爬取站外链接；站外链接仅作为页面 outlink 记录。
- **FR-012**：下游解析服务设计暂不纳入当前阶段，相关消息契约后置。
- **FR-013**：系统必须支持定期重爬，页面存储策略为只保留最新快照。
- **FR-014**：生产方向确认忽略 robots.txt，但必须保留 politeness、并发上限和批准目标范围约束。

### 非功能需求

- **NFR-001**：P0 应验证单节点能否在 CPU 低于 50%、内存低于 4 GB 的条件下，连续 24 小时维持 30 pages/sec，匹配原始 PoC 验收目标。
- **NFR-001a**：P0 24 小时运行错误率只记录，不设置硬性门槛。
- **NFR-002**：系统应支持稳态 1 亿页面/日的目标，具体以基础设施容量评估为准。
- **NFR-003**：在目标吞吐下，单节点资源使用应低于 70% CPU 和 8 GB 内存。
- **NFR-004**：抓取结果投递应采用 at-least-once 语义，并要求消费者具备幂等能力。
- **NFR-005**：Host 和 IP 失败状态应在 5 秒内跨 worker 传播。
- **NFR-006**：生产扩容必须受批准目标范围、politeness、并发上限和内部合规口径约束；robots.txt 不作为强制阻断。

### 关键实体

- **URL Task**：进入抓取队列的 URL，包含优先级、范围、去重键、重试状态和发现来源。
- **Page Snapshot**：一次成功抓取的页面快照，包含 URL 标识、抓取时间、状态、内容元数据、存储键和 outlink 数量。
- **Crawl Event**：一次请求尝试，包含耗时、出口 IP、状态或错误、重试次数和下载字节数。
- **Host Profile**：Host 级聚合行为，包括成功率、延迟、错误、outlinks 和 IP 健康状态。
- **IP Health State**：本地出口 IP 在 Host 维度和全局维度的健康状态，包括失败、冷却和恢复。

## 成功标准

- **SC-001**：PoC 能通过外部 endpoint 观测并验证辅助 EIP 已被用于出站请求。
- **SC-002**：P0 单节点在 CPU 低于 50%、内存低于 4 GB 的条件下连续 24 小时维持 30 pages/sec；若未达成，必须记录明确瓶颈。
- **SC-003**：HTML 在对应元数据对下游消费者可见之前，已经写入对象存储。
- **SC-004**：Host 画像查询目标暂后置设计，不作为 P0/P1 的进入门槛。
- **SC-005**：Kubernetes 滚动发布、健康检查和指标在小规模节点池验证完成后，再进入全量迁移。

## 假设

- PoC 和灰度发布期间，原 Heritrix 链路仍保持可用。
- 爬虫节点上已具备辅助私网 IP 到 EIP 的映射。
- Oracle Cloud Object Storage 是 HTML 内容的事实存储源，bucket 名称暂定为 `clawer_content_staging`。
- Kafka 作为缓冲和扇出层使用，不作为长期事实存储。

## 澄清记录

- 2026-04-27：基于 `scrapy-distributed-crawler-feature.md` 创建初稿；详细计划前仍有未澄清问题。
- 2026-04-27：P0 范围按原始实施计划中的单节点 PoC 处理。生产存储、分析、IaC 和多节点发布延后到后续阶段。
- 2026-04-27：确认 P0 在真实 Linux 爬虫节点运行；目标网卡暂按 `ens3`，但必须可配置；每节点约 44 个辅助 IP 的规模假设继续成立。
- 2026-04-27：确认 Redis 短暂不可用时以爬虫任务继续执行为优先，使用本地内存 fallback。
- 2026-04-27：确认 P0 并发从保守值开始，暂定 `CONCURRENT_REQUESTS=32`、`CONCURRENT_REQUESTS_PER_DOMAIN=2`，后续逐步调优。
- 2026-04-27：确认 P0 错误率只记录不设门槛；公网 echo endpoint 可用于验证；真实目标站点可包含 Wikipedia、White House 等经团队确认的公开站点。
- 2026-04-27：确认 P0 和生产方向均忽略 robots.txt，但保留 politeness、并发上限和批准目标范围约束。
- 2026-04-27：确认站外链接只记录不爬取；定期重爬只保留最新快照；下游解析服务、保留周期和 Host 画像查询目标暂后置。
- 2026-04-27：确认 Kafka 采用 at-least-once + 消费端幂等；对象存储使用 Oracle Cloud Object Storage，bucket 为 `clawer_content_staging`，endpoint 待补充。
- 2026-04-27：确认 `url_hash` 基于 canonical URL 计算，并忽略 fragment、query 参数顺序、Host 大小写、默认端口和尾斜杠等差异。
