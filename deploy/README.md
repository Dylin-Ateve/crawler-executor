# 部署与镜像发布

本目录只保存可复用的部署模板和脚本，不保存真实凭据。

## 镜像构建

```bash
IMAGE_REGISTRY=<registry.example.com/project> \
IMAGE_TAG=$(git rev-parse --short HEAD) \
PUSH_IMAGE=true \
deploy/scripts/build-container-image.sh
```

脚本会输出完整 `IMAGE_REF`，例如：

```text
registry.example.com/project/crawler-executor:abc1234
```

如果跳板机或 CI 不能直接访问 Docker Hub，使用内部 Python 基础镜像：

```bash
PYTHON_BASE_IMAGE=<internal-registry>/python:3.11-slim \
IMAGE_REGISTRY=<registry.example.com/project> \
IMAGE_TAG=$(git rev-parse --short HEAD) \
PUSH_IMAGE=true \
deploy/scripts/build-container-image.sh
```

## staging / production 部署口径

staging 是 production 功能验证的等价镜像环境。两者使用同一镜像构建流程和同一部署步骤；差异通过 `deploy/environments/*.env`、ConfigMap 和 Secret 注入。

```bash
set -a
source deploy/environments/staging.env
set +a

export IMAGE_REF=<registry.example.com/project/crawler-executor:abc1234>

kubectl get namespace "$M3_K8S_NAMESPACE" >/dev/null 2>&1 || kubectl create namespace "$M3_K8S_NAMESPACE"
deploy/scripts/render-k8s-configmap-from-env.sh | kubectl -n "$M3_K8S_NAMESPACE" apply -f -
deploy/scripts/render-k8s-daemonset-from-env.sh | kubectl -n "$M3_K8S_NAMESPACE" apply -f -
```

Each target namespace must contain the image pull secret referenced by `M3_IMAGE_PULL_SECRET`:

```bash
kubectl create secret docker-registry "$M3_IMAGE_PULL_SECRET" \
  --docker-server=phx.ocir.io \
  --docker-username='<tenancy-namespace>/<oci-user>' \
  --docker-password='<oci-auth-token>' \
  --docker-email='<email>' \
  -n "$M3_K8S_NAMESPACE"
```

如果 DaemonSet 已存在，只更新镜像：

```bash
export IMAGE_REF=<registry.example.com/project/crawler-executor:abc1234>
deploy/scripts/set-daemonset-image.sh
```

当前 DaemonSet 使用 `OnDelete` 更新策略。更新 template 后，需要人工删除目标 pod，由 DaemonSet 重建新 pod：

```bash
kubectl -n "$M3_K8S_NAMESPACE" delete pod <crawler-pod>
```

敏感配置必须通过目标集群 Secret 注入，不得写入镜像、ConfigMap、Git 或验证日志。
