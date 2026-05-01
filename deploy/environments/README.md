# 环境 Profile 说明

本目录保存 M3 / M3a 验证与部署规划使用的可 `source` 环境 profile。

## production.env

`production.env` 记录当前 OCI / OKE production 候选环境：

- node pool：`scrapy-node-pool`
- subnet：`subnetCollection`
- node label：`scrapy-egress=true`
- 第一轮验证不启用 taint
- `CRAWL_INTERFACE=enp0s5`
- 预期每 node IPv4 数量：`60-70`
- M3a 策略：`EGRESS_SELECTION_STRATEGY=STICKY_POOL`
- 历史兼容字段 `IP_SELECTION_STRATEGY` 同步设为 `STICKY_POOL`

## staging.env

`staging.env` 是 production 功能验证的等价镜像环境，运行在物理隔离的 staging 集群中：

- namespace、workload 名称、node label key 与操作流程和 production 保持一致
- `CRAWL_INTERFACE=ens3`
- node label：`scrapy-egress=true`
- 预期每 node IPv4 数量：`50-60`
- M3a 策略：`EGRESS_SELECTION_STRATEGY=STICKY_POOL`
- Redis 执行态写入启用，但 prefix 隔离为 `crawler:exec:safety:staging`

## 凭据边界

这些文件只允许保存非敏感配置和占位符。Redis、Kafka、OCI 等真实凭据必须在目标 K8s 集群中通过 Secret 创建，不得提交到仓库。

## 使用示例

```bash
set -a
source deploy/environments/staging.env
set +a

deploy/scripts/run-m3-k8s-daemonset-audit.sh
```

应用 ConfigMap 时，必须从当前环境 profile 渲染，不要直接 apply `deploy/k8s/base/configmap.yaml`：

```bash
set -a
source deploy/environments/staging.env
set +a

deploy/scripts/render-k8s-configmap-from-env.sh | kubectl -n "$M3_K8S_NAMESPACE" apply -f -
```
