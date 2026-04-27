# 研究记录：Scrapy 分布式爬虫

## 待研究决策

- Scrapy `bindaddress` 在 Kubernetes `hostNetwork` 下的行为。
- scrapy-redis 针对 Host 分桶和优先级队列的定制方式。
- Redis 黑名单、去重和溢出策略的数据结构。
- Kafka producer 可靠性配置和本地磁盘缓冲策略。
- PostgreSQL 分区策略和保留策略。
- ClickHouse Host 画像 schema 和 materialized view 设计。
- 云厂商辅助 IP 与 EIP 绑定机制。
- Oracle Cloud Object Storage endpoint 和认证方式。

## 决策记录

| 主题 | 决策 | 理由 | 替代方案 |
|------|------|------|----------|
| P0 边界 | 仅做单节点 Scrapy 出口 IP PoC | 在进入存储和编排工作前，先隔离验证风险最高的网络假设 | 先构建完整 Kafka/PG/CH 链路会用更多变量掩盖网络不确定性 |
| IP 选择 | 先实现 `STICKY_BY_HOST`，保留 `ROUND_ROBIN` 作为诊断模式 | Host 粘滞映射能降低单 Host 出口抖动，同时仍能在不同 Host 间分散 IP | 纯随机选择对目标站点表现更嘈杂 |
| 黑名单状态 | Redis key + TTL 维护 Host/IP 冷却 | 匹配目标架构，并让恢复行为自动发生 | 本地内存状态无法验证共享行为 |
| 指标 | 在爬虫进程内暴露 Prometheus endpoint | 成本低，后续 K8s 阶段可复用 | 仅在运行后解析日志不足以支持实时验证 |
| Redis 降级 | Redis 短暂不可用时继续执行抓取任务，并使用本地内存 fallback | P0 以爬虫执行任务优先，避免 Redis 短故障直接停止 worker | Redis 不可用即停止 worker 会降低 PoC 连续运行可用性 |
| P0 起步并发 | 暂定 `CONCURRENT_REQUESTS=32`、`CONCURRENT_REQUESTS_PER_DOMAIN=2` | 先从保守值开始，降低对目标站点压力，再按观测逐步调优 | 直接使用较高并发可能放大封禁和误判风险 |
| robots.txt | P0 和生产方向均忽略 robots.txt | 用户确认该方向；同时必须保留 politeness 和批准目标范围 | 强制遵守 robots.txt 不符合当前项目目标 |
| 对象存储 | Oracle Cloud Object Storage，bucket `clawer_content_staging` | 用户确认云存储方向，endpoint 后续补充 | S3/COS/OSS 暂不作为当前目标 |
