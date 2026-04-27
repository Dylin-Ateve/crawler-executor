# P0 实施拆解

## 目标

验证 `scrapy-distributed-crawler-feature.md` 中风险最高的架构假设：单个爬虫节点上的 Scrapy worker 可以可靠地使用多个本地辅助 IP 作为出站源地址，并能自动冷却异常的 Host/IP 组合。

## P0 范围内

- 单节点 Scrapy worker。
- 本地网卡 IPv4 发现。
- 通过 Scrapy request metadata 绑定源 IP。
- Host 感知的 IP 选择。
- 基于 Redis 的失败计数和黑名单 TTL。
- 用于 echo endpoint 和受控 URL 验证的最小 spider。
- Prometheus 指标和本地运行证据。
- 针对已批准目标的 24 小时稳定性测试。

## P0 范围外

- 分布式 scrapy-redis scheduler。
- 对象存储上传。
- Kafka 发布。
- PostgreSQL 和 ClickHouse 消费者。
- K8s DaemonSet。
- Terraform 和 cloud-init 自动化。
- 完整 Host 画像分析。

## 实现模块

| 模块 | 职责 |
|------|------|
| `ip_pool.py` | 发现本地 IP，过滤排除 IP，按 Host 和策略选择 IP |
| `health.py` | 分类失败，更新 Redis 失败计数，维护黑名单 TTL |
| `middlewares.py` | 写入 `bindaddress`，记录已选 IP，并在响应/异常时更新健康状态 |
| `metrics.py` | 暴露请求、延迟、状态码、活跃 IP 和黑名单指标 |
| `spiders/egress_validation.py` | 驱动受控 PoC URL 集，并收集外部观测结果 |

## 落地步骤

1. 构建本地 Scrapy 项目骨架。
2. 实现纯 IP 发现和选择逻辑，并补充单元测试。
3. 增加 Redis 健康状态基础能力和阈值测试。
4. 接入 Scrapy middleware，并验证 `Request.meta["bindaddress"]`。
5. 使用低并发执行 echo endpoint 验证。
6. 逐步提升到 P0 目标并发。
7. 执行 24 小时稳定性测试。
8. 产出 P0 证据报告，并决策是否进入 P1。

## P0 准入/退出标准

只有满足以下条件才进入 P1：

- 外部观测到多个预期公网 EIP。
- 黑名单 TTL 行为无需重启 worker 即可生效。
- worker 在 24 小时运行中保持稳定。
- 资源使用和吞吐接近文档目标，或未达标瓶颈已明确且可修复。
