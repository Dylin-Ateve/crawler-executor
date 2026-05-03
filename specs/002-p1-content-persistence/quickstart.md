# 快速开始：P1 抓取内容可靠持久化与 crawl_attempt 投递

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
| `KAFKA_SSL_CA_LOCATION` | Kafka CA 路径 | `/etc/ssl/certs/ca-certificates.crt` |
| `KAFKA_BATCH_SIZE` | Kafka batch size | `100` |
| `KAFKA_TOPIC_CRAWL_ATTEMPT` | 抓取 attempt topic | `crawler.crawl-attempt.v1` |
| `KAFKA_TOPIC_PAGE_METADATA` | P1 第一版已验证 topic，兼容参考 | `crawler.page-metadata.v1` |
| `KAFKA_FLUSH_TIMEOUT_MS` | Kafka 单次 publish flush 上限 | `130000` |

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
export KAFKA_SSL_CA_LOCATION="/etc/ssl/certs/ca-certificates.crt"
export KAFKA_BATCH_SIZE="100"
export KAFKA_TOPIC_CRAWL_ATTEMPT="crawler.crawl-attempt.v1"
export KAFKA_FLUSH_TIMEOUT_MS="130000"
```

说明：当前容器镜像基于 `python:3.11-slim`，默认使用 `/etc/ssl/certs/ca-certificates.crt`。如果后续基础镜像切换为 Oracle Linux / RHEL 系列，需要通过 `KAFKA_SSL_CA_LOCATION` 显式指定容器内实际文件。

## Step 1：对象存储 smoke test

预期脚本：

```bash
deploy/scripts/p1-object-storage-smoke.sh
```

预期结果：

- 可以写入测试对象。
- 可以读取测试对象并完成 gzip 解压校验。
- P1 对象按 `.gz` 归档文件保存，不设置 HTTP `Content-Encoding: gzip`，避免 OCI SDK 或 HTTP 客户端自动解压导致读取语义不一致；压缩格式通过对象 metadata 和 Kafka `compression` 字段表达。
- 测试对象使用 `smoke/p1/` 前缀，P1 不执行删除；后续清理由 P2 或人工运维处理。

## Step 2：Kafka smoke test

预期脚本：

```bash
deploy/scripts/p1-kafka-smoke.sh
```

预期结果：

- `crawl_attempt` topic 可写入测试消息。
- 消息 key 为 `attempt_id`。
- 消息中包含 `fetch_result`、`content_result`、`storage_result`。

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
- `crawl_attempt` Kafka 消息引用的 `storage_key` 可读取。
- 成功 HTML 分支应满足 `fetch_result=succeeded`、`content_result=html_snapshot_candidate`、`storage_result=stored`。
- `content_sha256` 与未压缩内容一致。
- 非 HTML 资源不会写对象存储，但会发布 `crawl_attempt`，且 `storage_result=skipped`。

## Step 4：对象存储失败验证

通过不存在的 bucket 模拟上传失败。脚本会临时覆盖 `OCI_OBJECT_STORAGE_BUCKET`，不会修改当前 shell 之外的配置。

```bash
deploy/scripts/run-p1-storage-failure-validation.sh /tmp/p1-seeds.txt
```

预期结果：

- 发布 `crawl_attempt`。
- `storage_result=failed`。
- 不携带可用 `snapshot_id/storage_key` 快照语义。
- 日志和指标包含失败原因。
- 消费端不应从该事件投影 `page_snapshots`。

## Step 5：Kafka 失败记录验证

临时配置不可达 Kafka broker。脚本默认使用 `127.0.0.1:1` 作为失败 broker，并将 `KAFKA_DELIVERY_TIMEOUT_MS` 缩短到 `6000`、`KAFKA_FLUSH_TIMEOUT_MS` 缩短到 `8000`，避免等待过久；如需覆盖失败验证参数，使用 `P1_FAILURE_KAFKA_*` 环境变量。

```bash
deploy/scripts/run-p1-kafka-failure-validation.sh /tmp/p1-seeds.txt
```

预期结果：

- HTML 已写入对象存储。
- Kafka 发布失败会记录结构化日志和指标。
- P1 不实现本地 outbox，不验证本地持久重放。
- 脚本输出 `Step T038 验证通过：对象已写入，Kafka 发布失败被记录。`

## P1 结果记录表

| 项目 | 目标 | 实测 | 结论 |
|------|------|------|------|
| 对象存储写入 | HTML 压缩后可写入并读取 | 2026-04-29 T055：`p1_object_storage_smoke_ok`，key=`smoke/p1/object-storage-smoke-20260429T085147Z.txt.gz` | 通过 |
| Kafka attempt 发布 | attempt 完成后发布 `crawl_attempt` | 2026-04-29 T055：`p1_kafka_smoke_ok`，topic=`crawler.crawl-attempt.v1`，key 为 `attempt_id` | 通过 |
| 成功快照引用 | 成功 HTML 事件包含可读取 `storage_key` | 2026-04-29 T055：`storage_result=stored`，`p1_storage_object_verify_ok`，`verified_uncompressed_size=92443` | 通过 |
| 上传失败保护 | 上传失败发布 `storage_result=failed` 的 `crawl_attempt` | 2026-04-29 T055：`p1_storage_upload_failed` 后发布 `storage_result=failed` | 通过 |
| Kafka 失败记录 | Kafka 故障后记录日志和指标 | 2026-04-29 T055：`p1_kafka_publish_failed`，对象已写入且可读取 | 通过 |
| 非 HTML 跳过 | 非 HTML 不写对象存储但发布 skipped attempt | 2026-04-29 skipped 补充验证：favicon 发布 `storage_result=skipped`，reason=`non_html_content` | 通过 |
| 幂等键 | `attempt_id` 用于 attempt 去重，`snapshot_id` 用于成功快照去重 | 2026-04-29 T055：Kafka key 与日志均使用 `attempt_id`，成功快照含 `snapshot_id` | 通过 |

## 真实环境验证记录

### 2026-04-29 T055 目标节点验证

结果：通过。

```text
p1_kafka_smoke_ok
topic=crawler.crawl-attempt.v1
key=77d1ac3bdf379bdf4b24601e6bc6c63d0d99c7adeeabc770f040f1106ea4d6dd:attempt:1777452706598

p1_object_storage_smoke_ok
provider=oci
bucket=clawer_content_staging
key=smoke/p1/object-storage-smoke-20260429T085147Z.txt.gz
etag=c0ae8cc3-3a27-4f9a-9ba9-a4d57f8e34bb
verified_uncompressed_size=32
```

成功 HTML 端到端验证：

```text
p1_crawl_attempt_published url=https://www.wikipedia.org/ attempt_id=1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:attempt:1777452708735 storage_result=stored snapshot_id=1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:1777452709004 storage_key=pages/v1/2026/04/29/061bdbf8744ebfcd/1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b/1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:1777452709004.html.gz
p1_storage_object_verify_ok
verified_uncompressed_size=92443
```

对象存储失败验证：

```text
p1_storage_upload_failed url=https://www.wikipedia.org/
p1_crawl_attempt_published url=https://www.wikipedia.org/ attempt_id=1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:attempt:1777452710711 storage_result=failed reason=storage_upload_failed
Step T037 验证通过：对象存储失败后发布了 storage_result=failed 的 crawl_attempt。
```

Kafka 失败验证：

```text
KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:1
p1_kafka_publish_failed url=https://www.wikipedia.org/ attempt_id=1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:attempt:1777452712025 storage_result=stored snapshot_id=1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:1777452712297 storage_key=pages/v1/2026/04/29/061bdbf8744ebfcd/1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b/1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:1777452712297.html.gz
p1_storage_object_verify_ok
Step T038 验证通过：对象已写入，Kafka 发布失败被记录。
```

非 HTML skipped 补充验证：

```text
p1_response_observed url=https://www.wikipedia.org/static/favicon/wikipedia.ico status=200 content_type=image/vnd.microsoft.icon local_ip=None
p1_crawl_attempt_published url=https://www.wikipedia.org/static/favicon/wikipedia.ico attempt_id=fc4a29e2a31c137b486b2ce484a164660348a57b2f7a066b393a79e903d163d9:attempt:1777452679319 storage_result=skipped reason=non_html_content
```

限制说明：本次验证未配置 `REDIS_URL`，因此 P0 的 `LocalIpRotationMiddleware` 与 `IpHealthCheckMiddleware` 被禁用，日志中 `local_ip=None`。该结果证明 P1 对象存储与 `crawl_attempt` producer 链路通过；P0+P1 组合链路和多 worker 队列消费仍由后续 spec 验证。

### 2026-04-28 Kafka smoke test

结果：通过。

```text
p1_kafka_smoke_ok
topic=crawler.page-metadata.v1
key=77d1ac3bdf379bdf4b24601e6bc6c63d0d99c7adeeabc770f040f1106ea4d6dd:1777366991632
```

网络前置修正：Kafka bootstrap 解析为私网地址 `10.0.4.155`，初始 TCP 连接到 `10.0.4.155:9092` 超时。放通 Kafka 侧 ingress 后验证通过。

说明：以上为 P1 第一版 `page-metadata` smoke 记录。2026-04-29 T055 已重新验证 `crawler.crawl-attempt.v1`。

### 2026-04-28 Object Storage smoke test

结果：通过。

```text
p1_object_storage_smoke_ok
provider=oci
bucket=clawer_content_staging
key=smoke/p1/object-storage-smoke-20260428T093141Z.txt.gz
etag=709fa028-1e7e-4c74-8615-b39c35e43470
verified_uncompressed_size=32
```

验证说明：对象写入后可读取，读取结果可以按 gzip 解压并还原原文。对象按 `.gz` 归档文件保存，不设置 HTTP `Content-Encoding: gzip`。

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

### 2026-04-28 Object Storage 失败验证

结果：通过。

```text
OCI_OBJECT_STORAGE_BUCKET=crawler-p1-missing-bucket-20260428093716
p1_storage_upload_failed url=https://www.wikipedia.org/ storage_key=pages/v1/2026/04/28/061bdbf8744ebfcd/1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b/1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:1777369037263.html.gz
Step T037 验证通过：对象存储失败后未发布 page metadata。
```

验证说明：以上为 P1 第一版记录。2026-04-29 T055 已重新验证上传失败后发布 `storage_result=failed` 的 `crawl_attempt`。

### 2026-04-28 Kafka 失败验证

结果：通过。

```text
KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:1
KAFKA_FLUSH_TIMEOUT_MS=8000
p1_kafka_publish_failed url=https://www.wikipedia.org/ snapshot_id=1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:1777369275172 storage_key=pages/v1/2026/04/28/061bdbf8744ebfcd/1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b/1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:1777369275172.html.gz error=failed to publish page metadata key=1868061f6e5b3766a469a034e502180e366f5d73803e56553544d5a3b031f24b:1777369275172: flush timeout with 1 pending message(s)
Step T038 验证通过：对象已写入，Kafka 发布失败被记录。
```

验证说明：以上为 P1 第一版记录。2026-04-29 T055 已重新验证 Kafka 失败日志带 `attempt_id` 与 `storage_result=stored`，且对象已写入并可读取。
