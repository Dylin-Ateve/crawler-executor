# 终态架构：crawler-executor

**生效日期**：2026-04-29
**文档层级**：北极星层 / 终态架构
**更新节奏**：少变；仅当系统群边界、核心契约或终态架构发生变化时更新。

## 1. 边界声明

crawler-executor 的终态边界是：

> 抓取指令进 → 原始字节落盘 + 单一 `crawl_attempt` 事件出。

本系统持有执行体本体、对象存储中属于本次抓取的原始字节、本节点短窗口运营态 / 执行安全状态、事件总线发布者身份和执行级指标。

本系统不持有 URL 队列写入侧、PG/ClickHouse 事实层、Host 画像聚合、解析任务派发、内容加工状态和业务级闭环指标。

## 2. 明确不做

下列职责不属于第二类执行系统。任何“临时内嵌更方便”的方案都必须先通过 ADR 说明边界升级或例外原因。

- 不选择 URL。
- 不决定业务优先级、业务抓取频率和重抓窗口；仅允许为防封和出口健康做短窗口执行安全 pacing / cooldown。
- 不做结构化抽取。
- 不评估内容质量。
- 不持有事实层数据库或画像存储。
- 不自动 follow 链接。
- 不向 Redis URL 队列写入任务。
- 不派发 parse-tasks。

## 3. 数据规模假设

| 阶段 | URL 总量 | 日增 URL | HTML 总量估算（压缩后） | 元数据事实 |
|---|---:|---:|---:|---:|
| 冷启动期 | 10 亿 | 5000 万 - 1 亿 | 约 50 TB | 10 亿级 |
| 稳态期 | 持续增长 | 1 亿 / 日 | 日增约 5 TB | 日增 1 亿级 |

架构推论：

- HTML 字节必须进入对象存储，不能直接放入 RDBMS。
- 本系统以事件发布者身份输出抓取事实，不作为下游事实层数据库。
- 稳态目标约为每节点 30-50 pages/sec，依赖水平扩展和多出口 IP。

## 4. 终态架构图

```text
              +------------------------+
              |      控制平面          |
              |  策略配置 / 干预指令   |
              +-----------+------------+
                          |
                          v
              +------------------------+
              | 第六类：调度与决策      |
              | Streams 队列写入 / 参数 |
              +-----------+------------+
                          |
                          | 抓取指令（URL + 参数）
                          v
   +--------------------------------------------------+
   | crawler-executor（第二类）                       |
   | DaemonSet / hostNetwork / Scrapy workers         |
   |                                                  |
   | IP 轮换 / Politeness / Retry / 健康检查 / 指标   |
   +--------------+---------------------+-------------+
                  |                     |
                  | HTML 原始字节        | crawl_attempt 事件
                  v                     v
        +------------------+     +--------------------+
        | 对象存储          |     | 事件总线（Kafka）   |
        | gzip 快照         |     | 单一 attempt 事实   |
        +------------------+     +----+-----------+---+
                                      |           |
                                      v           v
                                第三类内容加工   第五类画像与状态
```

## 5. 终态数据流

1. 第六类写入 Redis / Valkey Streams 队列并下发抓取参数。
2. crawler-executor 只读消费 URL。
3. 入口处执行 canonical URL 归一化，生成 `url_hash`。
4. 创建 `attempt_id`，按 host-aware sticky-pool / adaptive egress policy 选择本地出口 IP。
5. 发起 HTTP 请求；Scrapy 内部 retry 归属同一个 `attempt_id`。
6. 判断响应类型：
   - 200 HTML：计算 `content_sha256`，生成 `snapshot_id`，gzip 后上传对象存储。
   - 非 HTML：不写对象存储，标记 `content_result=non_snapshot`、`storage_result=skipped`。
   - fetch 失败：标记 `fetch_result=failed`，后续结果为 skipped。
7. 发布单一 `crawl_attempt` 事件，无论成功、失败或跳过均发布。
8. 本地或 TTL 更新短窗口执行安全状态，如 `(host, ip)` backoff、IP cooldown、host slowdown，并以指标形式暴露执行态。
9. 第三类订阅事件后按 `storage_key` 自取内容。
10. 第五类订阅事件并投影事实层、Host/Site 画像与审计记录。

## 6. 能力边界纲领

### 6.1 多出口 IP

- 启动时发现节点本地辅助 IPv4 池。
- 生产方向默认采用 host-aware sticky-pool；P0 / staging 可保留 `STICKY_BY_HOST` 历史策略。
- 选择时避开本节点短窗口不可用 IP，并遵守 `(host, ip)` pacing、IP cooldown、host slowdown 等执行安全状态。
- 当某 Host / 出口池短窗口不可用时，本系统只允许有界本地延迟；是否业务级放弃、延后或重排仍由第六类决定。

### 6.2 IP 健康检查

- 本系统持有短窗口执行运营态，用于本节点避开短期不可用 IP，并区分 `(host, ip)`、`ip`、`host`、`host, asn/cidr` 不同退避维度。
- 长期画像事实归第五类持有。
- 失败信号包括 HTTP 拒绝类状态码、连接级失败、超时、5xx 和明确 CAPTCHA / challenge / 反爬页特征。

### 6.3 Politeness

- 支持全局并发、sticky-pool、per-(host, ip) pacer、单 IP token / cooldown、host 级降速、请求间隔、随机抖动、重试边界、下载超时和 UA 策略。
- 显式忽略 `robots.txt`，但必须保留合理并发和请求间隔。
- 静态 `DOWNLOAD_DELAY` / `CONCURRENT_REQUESTS_PER_DOMAIN` 只能作为 fallback；生产方向采用观测驱动的自适应防封闭环。
- 运行时参数终态由控制平面按 `tier` / `site_id` / `host_id` / `politeness_key` / `policy_scope_id` 等执行策略作用域下发；本系统只保留兜底默认值。
- `policy_scope_id` 是控制平面或第六类解析后的 opaque identifier；本系统不维护策略分组成员关系。

### 6.4 调度

- Redis / Valkey Streams consumer group 是当前已接受的第六类 Fetch Command 下发载体。
- 本系统不使用 Scrapy 外置 scheduler / dupefilter 方案，不接管 URL 去重、优先级或调度状态。
- 本系统只读消费，不写入新 URL，不维护跨节点去重过滤器。
- 本系统允许写入 TTL、命名空间隔离的短窗口执行安全状态，但不得表达 URL 选择、优先级、重抓窗口、去重结果或长期画像事实。
- 页面链接发现不进入本系统队列。

### 6.5 存储

- HTML 原始字节写入对象存储。
- 对象 key 按时间分区、哈希前缀打散、每次抓取保留独立快照。
- 本系统不主动删除旧对象；生命周期策略由运维或后续阶段定义。
- gzip 压缩语义通过对象 metadata 和事件字段表达，不通过 HTTP `Content-Encoding` 表达。

### 6.6 事件总线

- 本系统只发布单一 `crawl_attempt` 事件类型。
- 事件代表一次 attempt 的完整事实。
- `crawl_logs`、`page_snapshots`、`pages_latest` 是消费端投影，不是本系统并列事件。
- 投递语义为 at-least-once，下游按 `attempt_id` 幂等去重。

### 6.7 可观测性

本系统暴露执行层运营指标：

- 抓取速率与 HTTP 结果分布。
- 响应时间分布。
- 本地 IP 池规模、不可用 IP 数、sticky-pool 命中率、per-(host, ip) backoff、IP cooldown、host slowdown。
- challenge / soft-ban / 5xx rate 按 host、egress IP、可选 ASN / CIDR 分桶聚合。
- Redis、对象存储、事件总线依赖健康度。
- 节点本地出站缓冲水位。

Host 画像、业务级闭环指标和事实层看板归第五类。

### 6.8 部署形态

终态部署约束：

- DaemonSet 或等价节点级部署。
- Pod 必须能 bind 宿主机辅助 IPv4 地址，优先 `hostNetwork`。
- 爬虫节点通过 node label / taint 隔离。
- 暴露 liveness / readiness / Prometheus 指标端点。
- 外部依赖连接信息通过环境变量或 secret 注入，敏感凭据禁止入库。
- 事件总线短暂不可用时应具备节点本地持久化缓冲能力。

### 6.9 环境等价性

production 与 staging 是物理隔离的两套目标环境，但 staging 的定位是 production 功能验证的等价镜像环境。

终态约束：

- staging 必须复刻 production 的功能策略、部署形态、运行参数语义和操作流程。
- staging 与 production 只允许在资源定位、资源规模和物理拓扑上不同，例如 kube context、对象存储 / Kafka / Redis 端点、节点数量、机器规格、网卡名、本地出口 IP 数量和环境级 hash salt / Redis prefix。
- namespace、workload 名称、node label key、taint / toleration 策略、ConfigMap / Secret key 契约和验证步骤应尽量保持一致。若必须不同，必须在对应增量 spec 或 ADR 中说明原因、验证影响和回收条件。
- 所有准备在 production 验证的功能项和步骤，必须先能在 staging 以同一流程复刻执行；不能把 staging 降级为历史 fallback 或 P0 策略验证环境。
- `STICKY_BY_HOST` 等历史策略只能作为显式回退验证口径，不得作为 staging 默认。

### 6.10 镜像与发布

本系统进入 K8s / DaemonSet 验证前，必须具备可重复构建、可追踪版本、可回滚的容器镜像发布流程。

终态约束：

- 仓库必须提供容器镜像构建入口，镜像不得内嵌 Redis / Kafka / OCI 等真实凭据。
- 镜像 tag 必须能追溯到代码版本，推荐使用 git commit SHA 或发布版本号；不得长期依赖 `latest` 作为部署输入。
- staging 和 production 使用同一镜像构建产物或同一构建流程产出的等价镜像；环境差异通过 ConfigMap / Secret / env 注入，不通过改代码或改镜像表达。
- K8s manifest 中的 `image` 必须在部署前显式替换为目标 registry / tag。
- 镜像构建、推送、ConfigMap 渲染、DaemonSet image 更新和回滚命令必须形成可审计 SOP，并先在 staging 验证。

## 7. `crawl_attempt` 事件模型纲领

`crawl_attempt` 是本系统对外的唯一抓取事实事件。

事件必须表达：

- 标识：`attempt_id`、`url_hash`、canonical URL、Host ID、Site ID。
- fetch 结果：`fetch_result`、`status_code`、错误类型、响应耗时、出口 IP、retry 次数。
- content 结果：`content_result`、content type、是否快照。
- storage 结果：`storage_result`、`storage_key`、`storage_etag`、`snapshot_id`、`compressed_size`。
- 内容指纹：快照场景下的 `content_sha256`。

可见性顺序：

- HTML 字节上传成功后，才允许发布 `storage_result=stored`。
- 对象存储上传失败时仍发布事件，但 `storage_result=failed`，且不携带任何可读取对象引用。
- 非 HTML 响应不写对象存储，发布 `storage_result=skipped`。
- fetch 阶段失败也发布事件。

具体 schema 暂由 `specs/002-p1-content-persistence/contracts/crawl-attempt.schema.json` 承载，后续迁移至系统群契约仓库。

## 8. ID 体系约束

- `attempt_id`：一次抓取意图的幂等键；Scrapy 内部 retry 归属同一 `attempt_id`。
- `url_hash`：基于 canonical URL 的逻辑页面标识。
- `snapshot_id`：仅快照场景存在，区分同一 URL 多次抓取的独立对象。
- `content_sha256`：SHA-256 on 未压缩 HTML body，仅在 HTML 快照场景成立；概念上对应上层架构文档 10.7 的 Raw 指纹在 HTML 快照上下文里的落地。
- 上游若提供 `host_id`、`site_id`、`tier`、`politeness_key` 或 `policy_scope_id`，必须随 `crawl_attempt` 透传，避免下游反查映射；缺失时事件仍携带 canonical host 作为执行事实。

## 9. 演进债务与依赖

跨阶段债务由 `state/roadmap.md` 跟踪；会影响多个 feature 的技术决策需沉淀到 `state/decisions/`。

当前已知债务：

- D-DEBT-1：URL 归一化库 Python 实现先由本系统持有，待契约仓库提供官方实现后迁移。
- D-DEBT-2：事件 topic 与 schema 在契约仓库就绪后迁入契约托管。
- D-DEBT-3：Politeness 从静态 settings 默认值迁移到自适应防封闭环，并最终由控制平面运行时覆盖。
- D-DEBT-4：`content_sha256` 当前只覆盖 HTML 快照场景；如上层要求所有响应统一 Raw 指纹，需扩展独立字段。
- D-DEP-1：短窗口执行安全状态与第五类 Host / IP / ASN 长期画像事实的切分契约待回填。

## 10. 系统级验收标准

### 功能性

1. 单节点能稳定使用节点实际可用出口 IP 池轮换抓取，不以 P0 的 44 个 IP 作为终态上限。
2. 被封或疑似受损的 `(host, ip)`、IP、host 在配置时间内进入对应退避 / 冷却，恢复期试探机制正常。
3. HTML 完整落盘到对象存储，无字节丢失。
4. 每次抓取尝试均有 `crawl_attempt` 事件，无论成功失败。
5. 快照场景事件携带 `storage_key`、`storage_etag`、`content_sha256` 和 `snapshot_id`。
6. 对象存储不可用时发布 `storage_result=failed`，不暴露不存在对象的引用。
7. 事件总线不可用时节点本地缓冲不超过告警阈值。

### 性能

1. 稳态集群吞吐目标：不低于 1 亿页面 / 日。
2. 冷启动集群吞吐目标：不低于 5000 万页面 / 日。
3. 单节点目标：30-50 pages/sec。
4. P95 端到端延迟（请求发起到字节落盘和事件投递确认）低于 5 秒。

### 可运维

1. 新节点可自动加入抓取池。
2. DaemonSet 或等价部署支持滚动更新。
3. 关键告警 5 分钟内触发。
4. 敏感凭据不入库。

## 11. 架构风险

| 风险 | 影响 | 对策 |
|---|---|---|
| 整段 VPC 子网被源站封禁 | 单节点所有 IP 同时失效 | 长期分散 region / 云厂商 / ASN；执行层提供 ASN / CIDR 分桶观测和短窗口软上限 |
| 冷启动 URL 规模压垮 Redis | 第六类队列写入和本系统消费受阻 | 与第六类协同分片、磁盘队列和反压协议 |
| 对象存储小文件性能问题 | 上传、列举或生命周期操作变慢 | 路径前缀打散，超热场景再评估批量打包 |
| 事件总线短暂不可用 | 发布失败、本地缓冲堆积 | 节点本地 queue、重试、高水位告警 |
| 对象存储上传失败 | 下游无法读取快照 | 发布 `storage_result=failed` 事件，不携带对象引用 |
| 高并发且忽略 robots | 被封概率和合规风险上升 | 保留自适应 politeness、sticky-pool、软封禁反馈、UA 策略和控制平面停抓 |
| Redis 单点故障 | 队列读取中断或短窗口状态丢失 | Redis 高可用、本地 fallback、事实判定归第五类 |
| 职责渗透回流 | 第二类边界失真 | 通过 Architecture Gate 和 ADR Gate 阻断 |
| 法律 / ToS 风险 | 法律纠纷 | 法务评估、公开数据优先、紧急停抓通道 |

## 12. 对应上层架构文档

本文件服从《企业级内容生产系统群设计》：

- 第八章：系统群边界与第二类职责。
- 第九章：胶水层、事实层与执行层切分。
- 第十章：ID 体系、Host/Site、Raw 指纹。
- 第十一章：控制平面、策略下发、审计与干预。

当本文件与上层架构文档出现张力时，以上层架构为准；本仓库通过 ADR 记录修订诉求。

## 13. 参考资料

- Scrapy 官方文档：https://docs.scrapy.org/
- K8s `hostNetwork` 与 DaemonSet 最佳实践
- 云厂商 EIP / 共享带宽包文档
- 上层架构文档：《企业级内容生产系统群设计》
