# M3 K8s 基础 manifest

本目录保存 `crawler-executor` 的 M3 Kubernetes 基础模板。

不要提交真实 Secret 值。`secrets.example.yaml` 只说明必需的 Secret 名称和 key；真实 Secret 必须通过目标集群认可的密钥管理路径创建。

环境 profile 位于 `deploy/environments/`。`production.env` 用于当前 OCI / OKE production 候选环境；`staging.env` 是 production 功能验证的等价镜像环境，只允许资源定位、规模和物理拓扑不同。当前 staging 同样使用 `CRAWL_INTERFACE=enp0s5`，IP 池验证范围为 `5-5`。

DaemonSet 使用保守的初始资源配置：

- requests: `cpu=1000m`, `memory=2Gi`
- limits: `cpu=4000m`, `memory=6Gi`

资源调优需结合 `CONCURRENT_REQUESTS = min(ip_count * per_ip_concurrency, global_cap)`。production 计划使用 `60-70` 个本地 IPv4 时，必须重新评估 CPU、内存、Kafka flush 延迟、对象存储上传延迟和 gzip 压缩开销；staging 当前以每 node 5 个 IPv4 复刻功能行为。

Prometheus 发现通过 pod annotations 暴露 `:9410/metrics`。如果集群要求 `ServiceMonitor` 或 `PodMonitor`，可以在监控栈侧转换这些 annotations，不改变应用容器契约。

pause flag 同时以启动时环境变量 `CRAWLER_PAUSED` 和 ConfigMap volume 文件 `/etc/crawler/runtime/crawler_paused` 暴露。通过 patch `crawler-executor-config.data.crawler_paused` 可以在不删除 DaemonSet 的情况下暂停或恢复已有 pod；需要给 kubelet ConfigMap volume 正常传播延迟留出时间。

测试 namespace 的 apply 顺序：

```bash
kubectl apply -f configmap.yaml
kubectl apply -f <real-secrets.yaml>
kubectl apply -f daemonset.yaml
```
