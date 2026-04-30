# 当前状态：crawler-executor

**更新日期**：2026-04-30
**对应 commit**：待下次合并后回填
**对照终态**：`.specify/memory/architecture.md`
**当前阶段**：P0 核心链路已验证；P1 `crawl_attempt` producer 已通过目标节点 T055 验证。M2 `specs/003-p2-readonly-scheduler-queue/` 已完成目标节点验证。T015c 优雅停机实现已满足 PEL 不清空与可恢复底线，但目标节点验证显示严格 "SIGTERM 后立即停止读 / claim 并在 drain 时限前退出" 未满足；按低频手动滚动、任务幂等、允许少量重复抓取的运行假设暂时接受为过渡策略。M3 `specs/004-p3-k8s-daemonset-hostnetwork/` 已启动规格草案。

## 1. 当前架构快照

```text
第六类 Fetch Command / 本地验证输入
        |
        v
Redis Streams consumer group
        |
        v
Scrapy worker
        |
        +--> 本地辅助 IP bindaddress
        +--> Valkey/Redis 短窗口黑名单
        +--> Prometheus 单 worker 指标
        +--> OCI Object Storage gzip HTML 快照
        +--> Kafka crawl_attempt producer
```

当前仍是研发验证形态，不是完整终态：

- 已通过 Redis Streams consumer group 目标节点验证；真实第六类生产队列接入仍待上游联调。
- 尚未运行 K8s DaemonSet / hostNetwork 生产部署。
- 尚未交付第五类消费端事实投影。
- 尚未完成控制平面策略运行时下发。

## 2. 模块矩阵

| 终态能力 | 当前状态 | 当前证据 / 说明 |
|---|---|---|
| Scrapy 执行框架 | 部分完成 | 已建立 Scrapy 项目、middleware、spider、pipeline；尚未进入完整生产调度与部署。 |
| 多出口 IP 轮换 | 部分完成 | 单节点真实 Linux + 多辅助 IP + EIP 映射已验证；K8s hostNetwork 形态未验证。 |
| IP 健康检查与黑名单 | 部分完成 | Valkey/Redis 失败计数、TTL 黑名单、Prometheus 指标已验证；captcha、全局 IP 健康和恢复试探策略仍需扩展。 |
| Politeness 策略 | 部分完成 | 已忽略 robots.txt，并保留并发、延迟、重试配置；AutoThrottle、UA 随机化和生产调优未完成。 |
| 分布式调度只读消费 | 完成 P2 目标节点验证；优雅停机严格语义未收口 | 003 已验证 Redis Streams consumer group 单 worker、多 worker、fetch failed、无效消息和 Kafka failure / PEL reclaim；不引入 scrapy-redis 默认 scheduler / dupefilter。只读边界脚本已覆盖 key diff 与目标 stream `XLEN` 前后不变。优雅停机目标节点验证显示当前实现不清空 PEL，但 SIGTERM 后 shutdown flag 触发较晚，退出中的 worker 仍可能继续 claim / 重复处理；当前仅按低频手动滚动、任务幂等、允许少量重复抓取的过渡策略接受。 |
| HTML 对象存储 | 完成 P1 切片 | OCI Object Storage 写入、读取、gzip 校验和失败保护已验证；生命周期策略未配置。 |
| `crawl_attempt` producer | 完成 P2 验证切片 | 目标节点验证覆盖 stored / skipped / storage failed / Kafka failure 分支；003 已补强连接级 fetch failed 事件化。 |
| 第五类事实投影 | 不属于本系统 | PostgreSQL pages/crawl_logs 等由第五类消费端承接，本仓库只保留 producer 契约。 |
| ClickHouse Host 画像 | 不属于本系统 | 已明确归第五类，当前不在本仓库实现。 |
| 下游 Python 解析服务 | 不属于本系统 | 第三类订阅事件自取 storage_key，本系统不派发 parse-tasks。 |
| K8s 部署 | 规划中 | 004 已启动 DaemonSet + hostNetwork 生产部署基础草案；manifest、探针实现、镜像构建和配置注入尚未实现。 |
| Terraform / cloud-init 自动化 | 暂不规划 | 当前不进入近期规划，后续规模化时再评估。 |
| Prometheus 指标 | 部分完成 | 已有请求、耗时、IP、黑名单、存储、Kafka producer 指标；集群级队列、lag、资源面板未完成。 |
| Grafana / 告警 | 未完成 | 尚未配置看板和告警规则。 |
| 24 小时稳定性与 Heritrix 对比 | 未完成 | P0 已决定后置，不阻塞 P1。 |

## 3. 原始目标完成度

| 目标 | 状态 | 当前证据 |
|---|---|---|
| 更换爬虫框架为 Scrapy | 部分完成 | Scrapy worker、spider、middleware、pipeline 已实现并通过真实节点验证。 |
| 多出口 IP 轮换 | 部分完成 | P0 Step 5a/5b 验证多本地 IP 与多个公网 EIP。 |
| 可控 Politeness 策略 | 部分完成 | 支持并发、单域名并发、延迟、重试和 robots 关闭；生产参数未压测。 |
| 大规模持久化存储 | 部分完成 | HTML 写入对象存储与 `crawl_attempt` producer 已完成；消费端事实投影归第五类。 |
| Host 画像分析能力 | 不属于本系统 | 画像与事实层归第五类。 |
| 可运维 K8s 化部署 | 未完成 | 当前仍是目标节点脚本验证，未进入 K8s/IaC。 |

## 4. 原始实施计划对照

### 阶段 1：PoC 验证

| 事项 | 状态 | 备注 |
|---|---|---|
| 单节点 hostNetwork DaemonSet bind 辅助 IP | 未完成 | 已验证真实 Linux 单节点 bindaddress，但不是 K8s hostNetwork。 |
| 最小化 Scrapy：多 IP 轮换 + Redis 黑名单 | 完成 | P0 已实现并验证。 |
| echo endpoint 多 IP 生效 | 完成 | httpbin/ip 等 echo endpoint 已验证。 |
| 24 小时 vs 单 IP Heritrix 对比 | 未完成 | 后置，未作为进入 P1 的阻塞项。 |
| 单节点稳定 30 pages/sec | 未完成 | 尚未做稳定吞吐压测。 |

### 阶段 2：核心爬虫开发

| 事项 | 状态 | 备注 |
|---|---|---|
| IP 轮换 middleware | 完成 | `LocalIpRotationMiddleware` 已实现。 |
| 健康检查 middleware | 部分完成 | HTTP 失败和黑名单验证完成；captcha/全局策略需扩展。 |
| UA 随机化 | 未完成 | 尚未接入。 |
| 重试 | 部分完成 | Scrapy retry 配置已存在；与 IP 切换策略仍需生产化验证。 |
| 对象存储上传 + Kafka 投递 | 完成 P1 切片 | 已验证 HTML + `crawl_attempt` producer，覆盖成功、跳过、对象存储失败和 Kafka 失败记录。 |
| Redis Streams 队列消费 | 完成 P2 目标节点验证 | 已验证 `XREADGROUP` 只读消费、`crawl_attempt` 发布成功后 `XACK`、多 worker 正常 ack 路径和 Kafka failure / PEL reclaim。 |
| Prometheus 指标暴露 | 部分完成 | 单 worker 指标已可用，集群级指标未完成。 |

### 阶段 3：存储与下游

| 事项 | 状态 | 备注 |
|---|---|---|
| PostgreSQL 集群 + pg_partman | 不属于本系统 | 已迁出到第五类事实层。 |
| ClickHouse 集群 | 不属于本系统 | Host 画像归第五类。 |
| Kafka consumer 写 PG | 不属于本系统 | 本仓库只负责 producer 事件契约。 |
| 对象存储生命周期策略 | 未完成 | P1 不删除旧对象，后续再处理。 |

### 阶段 4：自动化与规模化

| 事项 | 状态 | 备注 |
|---|---|---|
| Terraform 节点 + 辅助 IP + EIP | 暂不规划 | 当前不进入近期规划。 |
| cloud-init 节点初始化 | 暂不规划 | 当前不进入近期规划。 |
| 5 台灰度观察 | 未完成 | 未开始。 |
| 扩至全量并关闭 Heritrix | 未完成 | 未开始。 |

### 阶段 5：观测与调优

| 事项 | 状态 | 备注 |
|---|---|---|
| Grafana 看板 | 未完成 | 未开始。 |
| 告警规则 | 未完成 | 未开始。 |
| Host 画像报表 | 不属于本系统 | 第五类输出。 |
| 反爬反馈调优 | 未完成 | 依赖长期运行数据。 |

## 5. 已知技术债

- D-DEBT-1：URL 归一化库 Python 实现先由本系统持有，后续迁移到契约仓库。
- D-DEBT-2：`crawl_attempt` schema 暂在本仓库，后续迁移到契约仓库。
- D-DEBT-3：Politeness 参数仍以 settings 默认值为主，后续接控制平面运行时下发。
- D-DEBT-4：`content_sha256` 当前只覆盖 HTML 快照场景。
- D-DEBT-5：P2 只读边界目标节点脚本已覆盖 Redis key diff 与目标 stream `XLEN` 前后对比，后续可继续补允许状态变化清单和更宽 audit pattern。
- D-DEBT-6：T015c 优雅停机当前只满足 PEL 不清空与可恢复底线；严格 "SIGTERM 后立即停止 `XREADGROUP` / `XAUTOCLAIM`、drain deadline 前退出" 未满足，后续需修正更早停机入口或调整 ADR-0009 / FR-022 的严格语义。
- D-DEP-1：host×ip 黑名单事实/缓存切分等待第五类画像契约。

## 6. 运行中的关键指标

当前已有单 worker 指标基础，尚未形成稳定生产看板：

- 请求总数、HTTP 状态码计数。
- 响应耗时。
- 活跃 IP 数、黑名单数量。
- 对象存储上传结果。
- Kafka producer 发布结果。
