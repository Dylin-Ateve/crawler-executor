# 实施计划：Scrapy 分布式爬虫

**分支**：`001-scrapy-distributed-crawler`
**日期**：2026-04-27
**规格文档**：`specs/001-scrapy-distributed-crawler/spec.md`

## 摘要

P0 实现单节点 Scrapy PoC，用于验证本地辅助 IP 出口能力。实现范围聚焦一个窄但接近生产形态的切片：IP 发现、Scrapy downloader middleware、Redis 黑名单/冷却、有边界的抓取配置、Prometheus 指标和可重复执行的验证脚本。

P0 产物不是最终分布式爬虫，而是进入 Kafka、PostgreSQL、ClickHouse、K8s、Terraform 等规模化工作前必须完成的验证点。

## 技术上下文

**语言/版本**：P0 使用 Python 3.12
**主要依赖**：Scrapy、Twisted、redis-py、prometheus-client、netifaces 或 psutil
**存储**：P0 使用 Redis 存储黑名单和计数器；除非显式开启，否则 P0 不做页面持久化
**测试**：纯逻辑使用 pytest，Scrapy 集成 smoke test，外加 24 小时 PoC 运行
**目标平台**：一台真实 Linux 爬虫节点，节点上辅助私网 IP 已映射到 EIP；目标网卡暂按 `ens3`，但通过配置覆盖
**项目类型**：分布式爬虫与数据管道
**性能目标**：P0 目标为连续 24 小时 30 pages/sec，CPU < 50%，内存 < 4 GB
**约束**：必须将出站请求绑定到本地源地址；必须避免对 Host 施加无边界压力；robots.txt 不作为强制阻断
**规模/范围**：单节点、约 44 个辅助 IP、受控 URL 集、外部 IP echo 验证、有限真实目标站点验证

## 章程检查

- 规格先行：P0 通过；更大生产范围仍有待澄清事项。
- 运维安全：默认并发从保守值开始，目标 Host 必须受控，P0 通过。
- 数据可靠性：P0 不涉及页面持久化；P1 存储链路前必须补齐。
- 增量交付：通过，当前按阶段推进。
- 可度量验收：P0 已有明确的 24 小时吞吐和资源目标。

## P0 架构

```text
seed URLs / echo URLs（种子 URL / 回显 URL）
        |
        v
Scrapy Spider（抓取入口）
        |
        v
Downloader Middleware（下载中间件）
  - 本地 IP 发现
  - host -> 本地 IP 选择
  - Request.meta["bindaddress"]
        |
        v
Internet target / IP echo endpoint（目标站点 / 出口回显 endpoint）
        |
        v
Health Middleware（健康检查中间件）
  - 状态码/错误分类
  - Redis 失败计数
  - Redis 黑名单 TTL
        |
        v
Prometheus 指标 + 本地运行日志
```

## P0 实施策略

1. 在 `src/crawler/` 下创建标准 Scrapy 项目。
2. 将 IP 发现能力实现为独立工具，并配套单元测试。
3. 优先实现支持 `STICKY_BY_HOST` 的 `LocalIpRotationMiddleware`。
4. 实现基于 Redis TTL 黑名单的 `IpHealthCheckMiddleware`。
5. 增加最小 spider，支持读取 seed URL 文件并记录外部观测到的出口 IP。
6. 增加 metrics endpoint，暴露请求总数、状态码总数、延迟、活跃 IP 数和黑名单数量。
7. 封装单节点运行命令，支持裸机或 host-network 容器执行。
8. 使用 IP echo endpoint 和小规模允许目标集执行受控验证。
9. 执行 24 小时测试，并与当前 Heritrix 基线对比。

## P0 运行参数

| 参数 | 暂定值 | 说明 |
|------|--------|------|
| `CRAWL_INTERFACE` | `ens3` | 目标节点网卡名暂按 `ens3`，必须支持配置覆盖 |
| `EXCLUDED_LOCAL_IPS` | 多值配置 | 用于排除一个或多个管理 IP |
| `IP_SELECTION_STRATEGY` | `STICKY_BY_HOST` | `ROUND_ROBIN` 仅作为诊断模式 |
| `IP_FAILURE_THRESHOLD` | `5` | 403/429/503 连续失败阈值 |
| `IP_COOLDOWN_SECONDS` | `1800` | Host/IP 冷却时间 |
| `CONCURRENT_REQUESTS` | `32` | P0 起步值，后续逐步调优 |
| `CONCURRENT_REQUESTS_PER_DOMAIN` | `2` | P0 起步值，后续逐步调优 |
| `ROBOTSTXT_OBEY` | `False` | P0 和生产方向均忽略 robots.txt |

## P1/P2 已确认方向

- 站外链接允许发现，但不继续爬取，仅记录。
- 支持定期重爬，页面存储只保留最新快照。
- 下游解析服务设计暂不纳入当前阶段。
- Kafka 接受 at-least-once 投递语义，并要求消费端幂等。
- 对象存储使用 Oracle Cloud Object Storage，bucket 名称为 `clawer_content_staging`，endpoint 后续补充。
- HTML、PostgreSQL 元数据、ClickHouse 事件保留周期暂不设计。
- Host 画像查询目标暂后置设计。
- 当前暂不定义 Heritrix 对比指标补充项。

## P0 暂不处理事项

- scrapy-redis 分布式调度和 URL 去重。
- Kafka 消息发布。
- 对象存储 pipeline。
- PostgreSQL 和 ClickHouse 消费者。
- K8s DaemonSet 发布。
- Terraform/cloud-init EIP 自动化。
- 完整 Host 画像分析查询。

## P0 验收门禁

- Gate 1：worker 启动并发现至少两个可用本地 IP。当前已通过，指标显示活跃本地 IP 数为 43。
- Gate 2：外部 echo endpoint 观测到多个预期 EIP。当前已通过，Step 5a 诊断确认多个公网 EIP。
- Gate 3：Host/IP 黑名单可以通过 Redis TTL 进入并退出冷却。当前暂未验证，需后续人为构造连续 403/429/503 或 captcha 场景。
- Gate 4：metrics endpoint 可以报告抓取计数和 IP 健康。当前已通过，Step 7 已确认。
- Gate 5：24 小时运行达成目标，或输出明确瓶颈报告。当前后置，Step 9/10 暂未执行。
- Gate 6：错误率完成记录即可，不设置硬性通过阈值。当前已按验证日志记录。

## 项目结构

### 文档

```text
specs/001-scrapy-distributed-crawler/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
└── tasks.md
```

### 源码

```text
src/
├── crawler/
│   ├── crawler/
│   │   ├── middlewares.py
│   │   ├── ip_pool.py
│   │   ├── health.py
│   │   ├── metrics.py
│   │   ├── settings.py
│   │   └── spiders/
│   └── scrapy.cfg
tests/
├── unit/
└── integration/
deploy/
├── docker/
└── scripts/
infra/
```

**结构决策**：P0 使用单个 Python/Scrapy 项目。后续阶段可增加 `consumers/`、`schemas/`、`deploy/k8s/` 和 `infra/terraform/`。

## 复杂度跟踪

| 例外项 | 必要原因 | 未采纳更简单方案的原因 |
|--------|----------|------------------------------|
| P0 引入 Redis | 需要验证目标架构中的共享黑名单语义 | 纯内存黑名单无法证明跨 worker 冷却模型 |
| P0 引入 Prometheus 指标 | 需要与 Heritrix 对比，并支撑 24 小时验收门禁 | 仅分析日志不足以支撑持续运行中的实时观察 |
