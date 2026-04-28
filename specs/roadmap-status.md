# 总体规划状态：Scrapy 分布式爬虫系统

**对照来源**：`scrapy-distributed-crawler-feature.md`  
**更新日期**：2026-04-28  
**当前阶段**：P0/P1 核心链路已验证，生产级分布式能力未完成。

## 总览

| 原始规划模块 | 当前状态 | 说明 |
|--------------|----------|------|
| Scrapy 框架替换 | 部分完成 | 已建立 Scrapy 项目、middleware、spider、pipeline；尚未替换完整生产调度与部署。 |
| 多出口 IP 轮换 | 部分完成 | 单节点真实 Linux + 多辅助 IP + EIP 映射已验证；K8s DaemonSet/hostNetwork 形态未验证。 |
| IP 健康检查与黑名单 | 部分完成 | Valkey/Redis 失败计数、TTL 黑名单、Prometheus 指标已验证；captcha、全局 IP 健康和恢复试探策略仍需扩展。 |
| Politeness 策略 | 部分完成 | 已忽略 robots.txt，并保留并发、延迟、重试配置；AutoThrottle、UA 随机化和生产调优未完成。 |
| 分布式调度 | 未完成 | 尚未接入 scrapy-redis scheduler、跨节点 URL 队列和去重。 |
| HTML 对象存储 | 完成 P1 切片 | OCI Object Storage 写入、读取、gzip 校验和失败保护已验证；生命周期策略未配置。 |
| Kafka 中间缓冲 | 部分完成 | `page-metadata` producer 和失败记录已验证；`crawl-events`、`parse-tasks`、DLQ、消费者和 lag 监控未完成。 |
| PostgreSQL 元数据 | 未完成 | pages/crawl_logs 分区表、pg_partman、consumer 均未实现。 |
| ClickHouse Host 画像 | 未完成 | crawl_events 表、写入链路和画像查询未实现。 |
| 下游 Python 解析服务 | 未完成 | P1 明确后置。 |
| K8s 部署 | 未完成 | DaemonSet、hostNetwork、liveness/readiness、镜像构建未实现。 |
| Terraform / cloud-init 自动化 | 未完成 | 节点、辅助 IP、EIP、安全规则自动化未实现。 |
| Prometheus 指标 | 部分完成 | 已有请求、耗时、IP、黑名单、存储、Kafka producer 指标；集群级队列、lag、资源面板未完成。 |
| Grafana / 告警 | 未完成 | 尚未配置看板和告警规则。 |
| 24 小时稳定性与 Heritrix 对比 | 未完成 | P0 已决定后置，不阻塞 P1。 |

## 原始目标完成度

| 目标 | 状态 | 当前证据 |
|------|------|----------|
| 更换爬虫框架为 Scrapy | 部分完成 | Scrapy worker、spider、middleware、pipeline 已实现并通过真实节点验证。 |
| 多出口 IP 轮换 | 部分完成 | P0 Step 5a/5b 验证多本地 IP 与多个公网 EIP；长期稳定性后置。 |
| 可控 Politeness 策略 | 部分完成 | 支持并发、单域名并发、延迟、重试和 robots 关闭；生产参数未压测。 |
| 大规模持久化存储 | 部分完成 | HTML 写入对象存储和 Kafka metadata producer 已完成；PG/CH 持久化未完成。 |
| Host 画像分析能力 | 未完成 | 当前只记录基础指标和 outlink 计数，未实现 ClickHouse 聚合查询。 |
| 可运维 K8s 化部署 | 未完成 | 当前仍是目标节点脚本验证，未进入 K8s/IaC。 |

## 原始实施计划对照

### 阶段 1：PoC 验证

| 事项 | 状态 | 备注 |
|------|------|------|
| 单节点 hostNetwork DaemonSet bind 辅助 IP | 未完成 | 已验证真实 Linux 单节点 bindaddress，但不是 K8s hostNetwork。 |
| 最小化 Scrapy：多 IP 轮换 + Redis 黑名单 | 完成 | P0 已实现并验证。 |
| ifconfig.me / echo endpoint 多 IP 生效 | 完成 | httpbin/ip 等 echo endpoint 已验证。 |
| 24 小时 vs 单 IP Heritrix 对比 | 未完成 | 后置，未作为进入 P1 的阻塞项。 |
| 单节点稳定 30 pages/sec | 未完成 | 尚未做稳定吞吐压测。 |

### 阶段 2：核心爬虫开发

| 事项 | 状态 | 备注 |
|------|------|------|
| IP 轮换 middleware | 完成 | `LocalIpRotationMiddleware` 已实现。 |
| 健康检查 middleware | 部分完成 | HTTP 失败和黑名单验证完成；captcha/全局策略需扩展。 |
| UA 随机化 | 未完成 | 尚未接入。 |
| 重试 | 部分完成 | Scrapy retry 配置已存在；与 IP 切换策略仍需生产化验证。 |
| 对象存储上传 + Kafka 投递 | 完成 P1 切片 | 仅 HTML + `page-metadata` producer，不含其他 topics。 |
| scrapy-redis 集成 | 未完成 | 当前不是分布式队列模式。 |
| Prometheus 指标暴露 | 部分完成 | 单 worker 指标已可用，集群级指标未完成。 |

### 阶段 3：存储与下游

| 事项 | 状态 | 备注 |
|------|------|------|
| PostgreSQL 集群 + pg_partman | 未完成 | 尚未建表和 consumer。 |
| ClickHouse 集群 | 未完成 | 尚未建表和写入链路。 |
| Kafka consumer 写 PG/CH/DLQ | 未完成 | P1 明确不做 consumer。 |
| 对象存储生命周期策略 | 未完成 | P1 不删除旧对象，P2/P后续处理。 |

### 阶段 4：自动化与规模化

| 事项 | 状态 | 备注 |
|------|------|------|
| Terraform 节点 + 辅助 IP + EIP | 未完成 | 未开始。 |
| cloud-init 节点初始化 | 未完成 | 未开始。 |
| 5 台灰度观察 | 未完成 | 未开始。 |
| 扩至全量并关闭 Heritrix | 未完成 | 未开始。 |

### 阶段 5：观测与调优

| 事项 | 状态 | 备注 |
|------|------|------|
| Grafana 看板 | 未完成 | 未开始。 |
| 告警规则 | 未完成 | 未开始。 |
| Host 画像报表 | 未完成 | 依赖 ClickHouse。 |
| 反爬反馈调优 | 未完成 | 依赖长期运行数据。 |

### 阶段 6：迁移收尾

| 事项 | 状态 | 备注 |
|------|------|------|
| 旧 Heritrix 数据迁移评估 | 未完成 | 未开始。 |
| 旧服务下线 | 未完成 | 未开始。 |
| 文档归档与团队培训 | 未完成 | 当前仍处研发验证阶段。 |

## 当前已完成的可验收链路

1. Scrapy 单节点多出口 IP PoC。
2. Valkey/Redis 黑名单 TTL 验证。
3. Prometheus 单 worker 指标暴露。
4. canonical URL 和 `url_hash` 契约。
5. HTML gzip 写入 OCI Object Storage。
6. Object Storage 写入后读取与 gzip 解压校验。
7. Kafka `page-metadata` producer。
8. 对象存储失败时不发布 metadata。
9. Kafka 失败时保留对象并记录发布失败。

## 未完成的关键生产能力

1. scrapy-redis 分布式调度与去重。
2. PostgreSQL pages/crawl_logs 分区表与 consumer。
3. ClickHouse crawl_events 与 Host 画像查询。
4. `crawl-events`、`parse-tasks`、DLQ topic 和相关消费者。
5. 本地 outbox / Kafka 故障补偿队列。
6. K8s DaemonSet + hostNetwork 部署。
7. Terraform/cloud-init 自动化辅助 IP 与 EIP。
8. Grafana 看板、告警和运维 SOP。
9. 24 小时稳定性压测、30-50 pages/sec 单节点目标验证。
10. Heritrix 基线对比和迁移收尾。

## 下一阶段建议

推荐优先进入消费者与 metadata 索引阶段，而不是先做 K8s/IaC。原因是当前 producer 链路已经能产生对象和 Kafka 消息，但没有 metadata 落库，无法形成“最新快照索引”和后续解析任务入口。

建议新开 `003` spec：

- Kafka `page-metadata` consumer。
- PostgreSQL `pages` 表与最新快照语义。
- 幂等写入：基于 `url_hash` / `snapshot_id`。
- 对象存储 `storage_key` 可读取校验。
- 为 P2/P3 的 ClickHouse 和解析服务保留契约。
