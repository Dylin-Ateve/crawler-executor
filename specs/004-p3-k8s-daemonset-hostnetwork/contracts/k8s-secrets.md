# K8s Secret 契约：P3 crawler-executor

本文档定义 M3 第一版 K8s 部署所需 Secret 名称、key、引用方式和禁止入库边界。所有真实 Secret 值必须由目标集群侧创建；仓库、镜像、ConfigMap、DaemonSet 模板和验证日志不得包含真实凭据。

## Secret 命名

| Secret 名称 | 用途 | 是否必需 | 备注 |
|---|---|---|---|
| `crawler-executor-redis` | Redis / Valkey 连接串 | 必需 | 队列消费和 P0 IP 健康状态可引用同一 Redis，也可在目标集群中拆分。 |
| `crawler-executor-kafka` | Kafka SASL 凭据 | 必需 | 仅保存用户名和密码；broker、topic、协议参数属于 ConfigMap。 |
| `crawler-executor-oci-api-key` | OCI API key 模式凭据 | 条件必需 | 仅当 `OCI_AUTH_MODE=api_key` 时使用；`instance_principal` 模式不得挂载该 Secret。 |

## `crawler-executor-redis`

| Secret key | 映射环境变量 | 是否必需 | 说明 |
|---|---|---|---|
| `fetch_queue_redis_url` | `FETCH_QUEUE_REDIS_URL` | 必需 | Redis Streams Fetch Command 队列连接串；包含用户名或密码时必须只走 Secret。 |
| `redis_url` | `REDIS_URL` | 必需 | P0 IP health / blacklist Redis 连接串。第一版可以与 `fetch_queue_redis_url` 相同，但保留独立 key，避免后续拆分时修改应用契约。 |

约束：

- `FETCH_QUEUE_REDIS_URL` 与 `REDIS_URL` 不得写入 ConfigMap。
- 若目标集群确认队列 Redis 与 IP health Redis 是同一实例，也应在 Secret 中显式提供两个 key，避免依赖应用内 fallback 行为。
- 连接串中的密码必须 URL encode。

## `crawler-executor-kafka`

| Secret key | 映射环境变量 | 是否必需 | 说明 |
|---|---|---|---|
| `username` | `KAFKA_USERNAME` | 必需 | Kafka SASL 用户名。 |
| `password` | `KAFKA_PASSWORD` | 必需 | Kafka SASL 密码。 |

约束：

- `KAFKA_BOOTSTRAP_SERVERS`、`KAFKA_SECURITY_PROTOCOL`、`KAFKA_SASL_MECHANISM`、`KAFKA_SSL_CA_LOCATION`、`KAFKA_TOPIC_CRAWL_ATTEMPT` 属于 ConfigMap，不放入 Secret。
- `KAFKA_SSL_CA_LOCATION` 是容器内 CA 路径；如需自定义 CA bundle，证书内容应通过单独 ConfigMap 或集群基础镜像提供。除非 CA 私有且被安全团队要求保密，否则不作为本 Secret 的一部分。

## `crawler-executor-oci-api-key`

`instance_principal` 是 M3 推荐生产模式。只有在非 OCI instance principal 环境，或目标集群明确无法使用 instance principal 时，才使用本 Secret。

| Secret key | 挂载路径 | 是否必需 | 说明 |
|---|---|---|---|
| `config` | `/var/run/secrets/oci/config` | `api_key` 模式必需 | OCI SDK config 文件。文件内 `key_file` 必须指向同一 Secret volume 中的私钥路径。 |
| `oci_api_key.pem` | `/var/run/secrets/oci/oci_api_key.pem` | `api_key` 模式必需 | OCI API 私钥。 |

配套 ConfigMap / env：

| 环境变量 | 建议值 | 说明 |
|---|---|---|
| `OCI_AUTH_MODE` | `instance_principal` 或 `api_key` | 生产优先 `instance_principal`。 |
| `OCI_CONFIG_FILE` | `/var/run/secrets/oci/config` | 仅 `api_key` 模式设置。 |
| `OCI_PROFILE` | `DEFAULT` | 仅 `api_key` 模式设置。 |

约束：

- `OCI_OBJECT_STORAGE_BUCKET`、`OCI_OBJECT_STORAGE_NAMESPACE`、`OCI_OBJECT_STORAGE_REGION`、`OCI_OBJECT_STORAGE_ENDPOINT` 属于 ConfigMap。
- `instance_principal` 模式下不得把本地 OCI config、API 私钥或个人 profile 打入镜像。
- `api_key` 模式下，Secret volume 应只读挂载，文件权限由 K8s 默认 Secret volume 控制；应用无需在启动时改写 Secret 文件。

## DaemonSet 引用草案

后续 `deploy/k8s/` 模板应采用显式 `secretKeyRef`，不要使用 `envFrom` 整体注入，以避免无关 key 进入进程环境。

```yaml
env:
  - name: FETCH_QUEUE_REDIS_URL
    valueFrom:
      secretKeyRef:
        name: crawler-executor-redis
        key: fetch_queue_redis_url
  - name: REDIS_URL
    valueFrom:
      secretKeyRef:
        name: crawler-executor-redis
        key: redis_url
  - name: KAFKA_USERNAME
    valueFrom:
      secretKeyRef:
        name: crawler-executor-kafka
        key: username
  - name: KAFKA_PASSWORD
    valueFrom:
      secretKeyRef:
        name: crawler-executor-kafka
        key: password
```

`api_key` 模式的 OCI Secret 通过 volume 挂载：

```yaml
volumes:
  - name: oci-api-key
    secret:
      secretName: crawler-executor-oci-api-key
      optional: true
volumeMounts:
  - name: oci-api-key
    mountPath: /var/run/secrets/oci
    readOnly: true
```

## 禁止入库清单

以下内容不得进入 git、镜像 layer、ConfigMap、manifest 明文或验证日志：

- Redis / Valkey 用户名密码、完整连接串。
- Kafka SASL 用户名、密码或等价 token。
- OCI API 私钥、OCI config 中的用户 OCID / tenancy OCID / fingerprint / key path 组合。
- 任何目标集群生成的短期 session token。

## 验证要求

T007 完成后，后续 T027 / manifest 阶段必须验证：

- DaemonSet 模板只引用上述 Secret 名称和 key。
- `kubectl apply --dry-run=server` 不需要真实 Secret 值即可校验 manifest 结构。
- 仓库中不存在真实 Redis URL、Kafka 密码、OCI 私钥或目标集群 token。
