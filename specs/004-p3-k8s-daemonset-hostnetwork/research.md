# 研究：P3 K8s DaemonSet + hostNetwork 生产部署基础

## 1. 部署控制器选择

### 选项 A：DaemonSet + hostNetwork

优点：

- 与节点级出口 IP 资源一一对应，每个 crawler node 默认一个 pod。
- node 增减时 worker 自动跟随。
- `hostNetwork` 允许 Scrapy bind 宿主机辅助 IPv4。
- PEL、consumer name 与 node/pod 可直接关联，便于调试。

代价：

- 不适合按副本数弹性扩缩容。
- 需要节点 label / taint / toleration 管理。
- hostNetwork 会提高端口冲突和网络隔离要求。

当前结论：采纳。M3 使用专用 node pool + DaemonSet + `hostNetwork: true`。

### 选项 B：Deployment + hostNetwork

优点：

- 滚动更新和副本数管理常规。
- 便于局部扩大副本数。

代价：

- 无法天然表达“每 node 一个 pod”。
- 同 node 多 pod 可能争抢同一出口 IP 池。
- 调度结果不稳定，不利于节点级精确调试。

当前结论：不采纳为 M3 主形态。

### 选项 C：StatefulSet

优点：

- pod identity 稳定。
- 便于固定 consumer name。

代价：

- 仍不能天然绑定 node 级出口资源。
- 与每 node 一个 worker 的目标不匹配。

当前结论：不采纳。

## 2. 更新策略

### 选项 A：RollingUpdate maxUnavailable=1

优点：

- K8s 原生滚动，操作简单。
- 支持 `kubectl rollout status`，staging / production 验证步骤一致。
- 一次最多下线一个 node worker，风险可控。

代价：

- 滚动期间仍可能出现少量重复抓取或 PEL 接管窗口。
- 如果配置错误，需要依赖 rollout 状态、日志和 PEL 指标快速发现。

当前结论：按 ADR-0013 采纳。

### 选项 B：OnDelete

优点：

- 低频手动滚动最可控。
- 可以逐 node 排查 IP 池、PEL、Kafka 发布和对象存储行为。

代价：

- 更新需要人工或运维脚本逐 pod 删除。
- 自动化程度低，容易与 staging / production 等价操作流程不一致。

当前结论：已被 ADR-0013 替代，不作为当前默认。

## 3. 关停参数关系

M3 选择 ADR-0011 的 PEL 可恢复姿态，而不是严格 drain 完成后退出。

必须公式化：

```text
FETCH_QUEUE_CLAIM_MIN_IDLE_MS >= terminationGracePeriodSeconds * 1000 + safety_margin_ms
```

原因：

- 目标节点验证显示，若退出耗时超过 claim idle，退出中的 worker 可能自 reclaim 或重复处理同一 PEL。
- claim idle 必须大于 kubelet 给 pod 的终止窗口，避免滚动期间过早接管。

`FETCH_QUEUE_BLOCK_MS=1000` 是为了缩短空队列阻塞读对 SIGTERM 的响应延迟；代价是 Redis 轮询更频繁。

`FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS` 在 M3 第一版中主要用于日志与指标，不承诺强制终止 Scrapy in-flight 下载。

## 4. 健康检查口径

候选项：

| 探针 | 方案 | 结论 |
|---|---|---|
| liveness | 检查 Python 进程 / reactor / metrics endpoint 存活 | 采纳 |
| liveness | 包含 Redis / Kafka / OCI 依赖探测 | 不采纳，依赖抖动会造成错误重启 |
| readiness | 检查 worker 初始化完成、最近消费循环心跳 | 采纳 |
| readiness | 任一外部依赖不可达即失败 | 不采纳，会放大全集群依赖抖动 |

外部依赖健康通过 Prometheus 指标和告警承接：

- Redis read / ack / reclaim 失败。
- Kafka publish failure。
- OCI put_object / get_object failure。
- PEL count、consumer idle、队列积压。

## 5. IP 池发现

### 选项 A：启动时扫描宿主机 IPv4 + 排除列表

优点：

- 与真实 node 网络状态一致。
- 避免维护每 node 大量 ConfigMap 条目。
- 对 50-70 个 IP 的节点更低运维成本。

代价：

- 运行期 NIC 变化不会自动感知。
- 需要明确 `CRAWL_INTERFACE` / interface 过滤语义。

当前结论：采纳。运行期 NIC 变化通过重启 pod 生效。

### 选项 B：每 node 显式 ConfigMap IP 列表

优点：

- 完全可控，可审计。
- 适合严格变更流程。

代价：

- 50-70 IP × 多 node 维护成本高。
- 容易与实际网卡状态漂移。

当前结论：不作为第一版主形态；可作为 debug override。

## 6. 调试流量与事件污染

M3 采用 debug stream + 正式 topic + `tier=debug` 标记：

```text
crawl:tasks:debug:<node_name> -> crawler pod -> crawler.crawl-attempt.v1(tier=debug)
```

理由：

- 保持完整链路，能验证对象存储、Kafka、下游过滤和 PEL。
- 不需要为第二类临时切 topic。
- 第五类可以按 `tier=debug` 过滤或单独标记。

风险：

- 下游第五类必须明确过滤 / 标记规则，否则 debug attempt 会污染生产事实。
- Debug Fetch Command 必须带可识别 `job_id` / `trace_id` 前缀。

## 7. 紧急停抓形态

DaemonSet 没有 replicas 概念，不应依赖 scale-to-zero。

备选：

- 删除 DaemonSet：破坏性大，不采纳。
- 修改 nodeSelector 使 pod 不匹配：会触发 pod 驱逐，适合集群级下线，不适合作为常规停抓。
- 应用层 pause flag：采纳。worker 停止读取新消息，不清空 PEL，保留进程和指标端点。

M3 只定义最小 pause flag，不实现完整控制平面。

## 8. Secret / Config 分层

Secret：

- Redis 密码或完整 `FETCH_QUEUE_REDIS_URL`。
- Kafka SASL 用户名、密码、TLS 敏感材料。
- OCI API key；若使用 instance principal，则不注入 API key。

ConfigMap：

- stream / group / consumer 模板。
- 并发、timeout、claim idle、drain、IP 排除列表。
- metrics port、日志级别、debug stream 开关、pause flag。

镜像不得内嵌真实凭据。
