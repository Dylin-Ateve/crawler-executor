# 快速开始：P1 抓取内容可靠持久化与元数据投递

本文档定义 P1 的预期验证流程。P1 依赖 P0 已验证的 Scrapy worker、出口 IP middleware、Valkey 黑名单和 Prometheus 指标。

## 前置条件

- P0 核心验证已完成。
- 目标节点可以访问 Oracle Cloud Object Storage。
- 目标节点可以访问 Kafka。
- Kafka 集群所在子网 / NSG / Security List 需要允许爬虫节点子网到 `TCP 9092` 的入站流量；已验证爬虫节点 `10.0.12.196` 需要 Kafka 侧放通 `10.0.12.0/24` 或更精确的 `/32`。
- 已确认 Kafka 采用 at-least-once，消费端负责幂等。
- 下游解析服务暂不纳入 P1。

## 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `OCI_OBJECT_STORAGE_BUCKET` | 对象存储 bucket | `clawer_content_staging` |
| `OCI_OBJECT_STORAGE_NAMESPACE` | OCI namespace | `axfwvgxlpupm` |
| `OCI_OBJECT_STORAGE_REGION` | OCI region | `us-phoenix-1` |
| `OCI_OBJECT_STORAGE_ENDPOINT` | 对象存储 endpoint | `https://objectstorage.us-phoenix-1.oraclecloud.com` |
| `OCI_AUTH_MODE` | OCI SDK 认证模式 | `api_key` 或 `instance_principal` |
| `OCI_CONFIG_FILE` | OCI SDK 配置文件 | `~/.oci/config` |
| `OCI_PROFILE` | OCI SDK profile | `DEFAULT` |
| `OBJECT_STORAGE_PROVIDER` | 存储提供方 | `oci` |
| `CONTENT_COMPRESSION` | 内容压缩格式 | `gzip` |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka broker 列表 | `bootstrap-clstr-hcpqnx0ycdc2ds5o.kafka.us-phoenix-1.oci.oraclecloud.com:9092` |
| `KAFKA_SECURITY_PROTOCOL` | Kafka 安全协议 | `SASL_SSL` |
| `KAFKA_SASL_MECHANISM` | Kafka SASL 机制 | `SCRAM-SHA-512` |
| `KAFKA_USERNAME` | Kafka 用户名 | 环境变量注入 |
| `KAFKA_PASSWORD` | Kafka 密码 | 环境变量注入 |
| `KAFKA_SSL_CA_LOCATION` | Kafka CA 路径 | `/etc/pki/tls/certs/ca-bundle.crt` |
| `KAFKA_BATCH_SIZE` | Kafka batch size | `100` |
| `KAFKA_TOPIC_PAGE_METADATA` | 页面元数据 topic | `crawler.page-metadata.v1` |

## Step 0：确认配置

```bash
export OBJECT_STORAGE_PROVIDER="oci"
export OCI_OBJECT_STORAGE_BUCKET="clawer_content_staging"
export OCI_OBJECT_STORAGE_NAMESPACE="axfwvgxlpupm"
export OCI_OBJECT_STORAGE_REGION="us-phoenix-1"
export OCI_OBJECT_STORAGE_ENDPOINT="https://objectstorage.us-phoenix-1.oraclecloud.com"
export OCI_AUTH_MODE="api_key"
export OCI_CONFIG_FILE="${HOME}/.oci/config"
export OCI_PROFILE="DEFAULT"

export KAFKA_BOOTSTRAP_SERVERS="bootstrap-clstr-hcpqnx0ycdc2ds5o.kafka.us-phoenix-1.oci.oraclecloud.com:9092"
export KAFKA_SECURITY_PROTOCOL="SASL_SSL"
export KAFKA_SASL_MECHANISM="SCRAM-SHA-512"
export KAFKA_USERNAME="<ENV_VAR_REFERENCE>"
export KAFKA_PASSWORD="<ENV_VAR_REFERENCE>"
export KAFKA_SSL_CA_LOCATION="/etc/pki/tls/certs/ca-bundle.crt"
export KAFKA_BATCH_SIZE="100"
export KAFKA_TOPIC_PAGE_METADATA="crawler.page-metadata.v1"
```

说明：Oracle Linux 8 默认使用 `/etc/pki/tls/certs/ca-bundle.crt`。如果目标节点不是该路径，程序会在常见 CA bundle 路径中自动兜底；也可以通过 `KAFKA_SSL_CA_LOCATION` 显式指定实际文件。

## Step 1：对象存储 smoke test

预期脚本：

```bash
deploy/scripts/p1-object-storage-smoke.sh
```

预期结果：

- 可以写入测试对象。
- 可以读取测试对象并完成 gzip 解压校验。
- 测试对象使用 `smoke/p1/` 前缀，P1 不执行删除；后续清理由 P2 或人工运维处理。

## Step 2：Kafka smoke test

预期脚本：

```bash
deploy/scripts/p1-kafka-smoke.sh
```

预期结果：

- `page-metadata` topic 可写入测试消息。
- 消息 key 与 schema_version 可被消费端读取。

## Step 3：端到端抓取验证

准备受控 HTML URL：

```bash
cat >/tmp/p1-seeds.txt <<'EOF'
https://www.wikipedia.org/
EOF
```

预期命令：

```bash
deploy/scripts/run-p1-persistence-validation.sh /tmp/p1-seeds.txt
```

预期结果：

- 对象存储中存在压缩 HTML。
- `page-metadata` Kafka 消息引用的 `storage_key` 可读取。
- `content_sha256` 与未压缩内容一致。
- 非 HTML 资源不会写对象存储，也不会发布 Kafka 消息。

## Step 4：对象存储失败验证

通过错误 endpoint、错误 bucket 或 fake client 模拟上传失败。

预期结果：

- 不发布 `page-metadata`。
- 日志和指标包含失败原因。

## Step 5：Kafka 失败记录验证

临时配置不可达 Kafka broker。

预期结果：

- HTML 已写入对象存储。
- Kafka 发布失败会记录结构化日志和指标。
- P1 不实现本地 outbox，不验证本地持久重放。

## P1 结果记录表

| 项目 | 目标 | 实测 | 结论 |
|------|------|------|------|
| 对象存储写入 | HTML 压缩后可写入并读取 | 端到端已写入；读取校验脚本已补充，真实 smoke 待执行 | 部分通过 |
| Kafka metadata 发布 | 内容写入后发布 `page-metadata` | `crawler.page-metadata.v1` smoke 与端到端均通过 | 通过 |
| 上传失败保护 | 上传失败不发布 metadata | 待执行 | 待验证 |
| Kafka 失败记录 | Kafka 故障后记录日志和指标 | 待执行 | 待验证 |
| 幂等键 | `snapshot_id` 可用于去重 | 已生成 `url_hash:fetched_at_ms` 格式 key | 通过 |

## 真实环境验证记录

### 2026-04-28 Kafka smoke test

结果：通过。

```text
p1_kafka_smoke_ok
topic=crawler.page-metadata.v1
key=77d1ac3bdf379bdf4b24601e6bc6c63d0d99c7adeeabc770f040f1106ea4d6dd:1777366991632
```

网络前置修正：Kafka bootstrap 解析为私网地址 `10.0.4.155`，初始 TCP 连接到 `10.0.4.155:9092` 超时。放通 Kafka 侧 ingress 后验证通过。

### 2026-04-28 P1 端到端抓取验证

结果：通过，基础 producer 链路完成。

```text
url=https://www.wikipedia.org/
status=200
content_type=text/html
snapshot_id=1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:1777367044069
storage_key=pages/v1/2026/04/28/061bdbf8744ebfcd/1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b/1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:1777367044069.html.gz
```

限制说明：本次端到端验证未配置 `REDIS_URL`，因此 P0 的 `LocalIpRotationMiddleware` 与 `IpHealthCheckMiddleware` 被禁用，日志中 `local_ip=None`。该结果证明 P1 对象存储与 Kafka producer 链路通过；如需验证 P0+P1 组合链路，需要带上 P0 的 Valkey 和本地出口 IP 配置再跑一次。
