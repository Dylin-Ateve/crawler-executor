# 快速开始：P0 Scrapy 分布式爬虫 PoC

本文档定义 P0 的预期验证流程。

## 前置条件

- 已准备一台 Linux 爬虫节点，目标网卡上配置了辅助私网 IPv4 地址。
- 目标网卡暂按 `ens3` 配置；如果实际网卡不同，通过 `CRAWL_INTERFACE` 覆盖。
- 单节点约 44 个辅助 IP 的规模假设继续成立。
- 每个辅助私网 IP 均有对应公网 EIP。
- 爬虫节点可以访问 Redis。
- 测试 URL 集已确认可用于 PoC 流量，可包含公网 echo endpoint、Wikipedia、White House 等经团队确认的公开目标。
- 至少有一个 IP echo endpoint 可用于出口验证。

## 配置输入

- `CRAWL_INTERFACE`：需要扫描的网卡，默认 `ens3`。
- `EXCLUDED_LOCAL_IPS`：从抓取出口中排除的主管理 IP，支持多个值。
- `IP_SELECTION_STRATEGY`：正常 PoC 使用 `STICKY_BY_HOST`，诊断时可使用 `ROUND_ROBIN`。
- `IP_FAILURE_THRESHOLD`：默认 `5`。
- `IP_COOLDOWN_SECONDS`：默认 `1800`。
- `CONCURRENT_REQUESTS`：P0 起步值暂定 `32`，后续逐步调优。
- `CONCURRENT_REQUESTS_PER_DOMAIN`：P0 起步值暂定 `2`，后续逐步调优。
- `REDIS_URL`：Redis 连接串。

## 本地准备

P0 代码位于仓库根目录下的 `src/crawler/`。建议在目标 Linux 爬虫节点上使用 Python 3.12 虚拟环境运行；当前代码保持 Python 3.9+ 兼容，方便本地做基础检查。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

如果只做语法检查，可以不安装 Scrapy，使用：

```bash
PYTHONPYCACHEPREFIX=/tmp/crawler-pycache PYTHONPATH=src/crawler python3 -m compileall src/crawler tests
```

## 环境变量配置

仓库提供了环境变量示例文件：`deploy/examples/p0.env.example`。正式运行前建议复制一份到节点本地并按实际环境修改。

```bash
cp deploy/examples/p0.env.example /tmp/crawler-p0.env
vi /tmp/crawler-p0.env
set -a
source /tmp/crawler-p0.env
set +a
```

最少需要确认以下变量：

| 变量 | 说明 | 示例 |
|------|------|------|
| `REDIS_URL` | Redis 连接串 | `redis://localhost:6379/0` |
| `CRAWL_INTERFACE` | 扫描辅助 IP 的网卡 | `ens3` |
| `EXCLUDED_LOCAL_IPS` | 管理 IP 排除列表，多个用逗号分隔 | `10.0.12.196,10.0.12.197` |
| `IP_SELECTION_STRATEGY` | IP 选择策略 | `STICKY_BY_HOST` |
| `CONCURRENT_REQUESTS` | 全局并发起步值 | `32` |
| `CONCURRENT_REQUESTS_PER_DOMAIN` | 单域名并发起步值 | `2` |
| `PROMETHEUS_PORT` | 指标端口 | `9410` |

## P0 验证 Runbook

### Step 0：确认节点网络

在目标 Linux 爬虫节点上确认目标网卡和辅助 IP：

```bash
ip addr show "${CRAWL_INTERFACE:-ens3}"
```

预期结果：

- 能看到主管理 IP。
- 能看到多个辅助私网 IP。
- `EXCLUDED_LOCAL_IPS` 中的 IP 不应作为爬取出口使用。

如果网卡名不是 `ens3`，更新：

```bash
export CRAWL_INTERFACE="<实际网卡名>"
```

### Step 1：确认 Redis 可访问

```bash
redis-cli -u "$REDIS_URL" ping
```

预期结果：

```text
PONG
```

如果 Redis 暂时不可用，P0 worker 仍应优先继续执行任务并使用本地 fallback，但黑名单跨进程共享能力会受影响。正式 24 小时稳定性测试前，应恢复 Redis。

### Step 2：安装依赖并运行基础检查

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
```

预期结果：

- 单元测试和 middleware smoke test 全部通过。
- 当前基线为 `20 passed`。

### Step 3：准备验证 URL

复制示例 seed 文件并替换为批准目标：

```bash
cp deploy/examples/egress-seeds.example.txt /tmp/egress-seeds.txt
vi /tmp/egress-seeds.txt
```

建议第一轮只保留公网 echo endpoint，例如：

```text
https://api.ipify.org?format=json
https://httpbin.org/ip
```

第二轮再加入经团队确认的公开目标，例如 Wikipedia、White House 等。

### Step 4：低风险出口验证

先使用保守并发运行：

```bash
export CONCURRENT_REQUESTS="8"
export CONCURRENT_REQUESTS_PER_DOMAIN="1"
deploy/scripts/run-egress-validation.sh /tmp/egress-seeds.txt
```

预期结果：

- 日志中出现 `p0_egress_observed`。
- `local_ip` 显示本地绑定的辅助 IP。
- `observed_ip` 显示公网侧观测到的 EIP。
- 多次运行后，外部观测 EIP 应覆盖多个预期出口。

如果只看到单个 EIP：

- 检查辅助 IP 是否已正确绑定到网卡。
- 检查 EIP 是否已和辅助私网 IP 一一绑定。
- 检查是否误把可用辅助 IP 放进了 `EXCLUDED_LOCAL_IPS`。
- 可临时设置 `LOCAL_IP_POOL` 显式指定本地 IP 做诊断。

### Step 5：显式 IP 池诊断

当自动发现辅助 IP 未打通时，可先跳过网卡扫描，手动指定 IP 池：

```bash
export LOCAL_IP_POOL="10.0.12.201,10.0.12.202"
deploy/scripts/run-egress-validation.sh /tmp/egress-seeds.txt
```

预期结果：

- 请求只从 `LOCAL_IP_POOL` 中选择本地 IP。
- 如果仍无法看到对应公网 EIP，优先排查云网络/EIP 绑定。

### Step 6：Redis 黑名单验证

运行一轮抓取后检查 Redis 健康状态：

```bash
deploy/scripts/inspect-ip-health.sh
```

也可以直接查看 key：

```bash
redis-cli -u "$REDIS_URL" --scan --pattern "${REDIS_KEY_PREFIX:-crawler}:blacklist:*"
redis-cli -u "$REDIS_URL" --scan --pattern "${REDIS_KEY_PREFIX:-crawler}:fail:*"
```

预期结果：

- 正常 200 响应不应持续产生黑名单。
- 当目标返回 403/429/503 连续达到阈值时，应出现 `crawler:blacklist:<host>:<ip>` key。
- 黑名单 key 应有 TTL，并在冷却结束后自动消失。

检查 TTL：

```bash
redis-cli -u "$REDIS_URL" ttl "<blacklist-key>"
```

### Step 7：指标验证

启动 spider 后，在节点上检查 Prometheus 指标：

```bash
curl -s "http://127.0.0.1:${PROMETHEUS_PORT:-9410}/metrics" | grep crawler_
```

预期至少看到：

- `crawler_requests_total`
- `crawler_response_duration_seconds`
- `crawler_ip_active_count`
- `crawler_ip_blacklist_count`

### Step 8：小规模真实目标验证

将 `/tmp/egress-seeds.txt` 更新为 echo endpoint + 少量批准公开目标，例如：

```text
https://api.ipify.org?format=json
https://www.wikipedia.org/
https://www.whitehouse.gov/
```

使用 P0 起步并发：

```bash
export CONCURRENT_REQUESTS="32"
export CONCURRENT_REQUESTS_PER_DOMAIN="2"
deploy/scripts/run-egress-validation.sh /tmp/egress-seeds.txt
```

预期结果：

- worker 稳定运行。
- 真实目标站点响应状态、延迟和错误会进入日志与指标。
- 错误率只记录，不作为 P0 硬门槛。

### Step 9：短时稳定性测试

正式 24 小时前，先跑 10 分钟或 1 小时：

```bash
export P0_SOAK_DURATION="10m"
deploy/scripts/run-p0-soak.sh /tmp/egress-seeds.txt
```

预期结果：

- 进程无异常退出。
- CPU、内存没有持续无界增长。
- Redis key 和指标正常更新。

### Step 10：24 小时 P0 稳定性测试

```bash
export P0_SOAK_DURATION="24h"
export CONCURRENT_REQUESTS="32"
export CONCURRENT_REQUESTS_PER_DOMAIN="2"
deploy/scripts/run-p0-soak.sh /tmp/egress-seeds.txt
```

需要记录：

- 平均 pages/sec。
- CPU 使用率。
- 内存使用。
- 错误率。
- 黑名单数量和黑名单比例。
- 观测到的公网 EIP 分布。
- Redis 短暂不可用时是否继续执行任务。

## 出口验证命令

准备 seed 文件。示例文件位于 `deploy/examples/egress-seeds.example.txt`，正式运行前需要替换为团队批准的 echo endpoint 或受控目标。

```bash
export REDIS_URL="redis://localhost:6379/0"
export CRAWL_INTERFACE="ens3"
export EXCLUDED_LOCAL_IPS="10.0.12.196"
export IP_SELECTION_STRATEGY="STICKY_BY_HOST"
export CONCURRENT_REQUESTS="32"
export CONCURRENT_REQUESTS_PER_DOMAIN="2"

deploy/scripts/run-egress-validation.sh deploy/examples/egress-seeds.example.txt
```

如果目标节点的辅助 IP 发现还未打通，可以先显式传入本地 IP 池做诊断：

```bash
export LOCAL_IP_POOL="10.0.12.201,10.0.12.202"
deploy/scripts/run-egress-validation.sh deploy/examples/egress-seeds.example.txt
```

## Redis 健康状态检查

```bash
export REDIS_URL="redis://localhost:6379/0"
deploy/scripts/inspect-ip-health.sh
```

## 24 小时稳定性测试

```bash
export P0_SOAK_DURATION="24h"
export CONCURRENT_REQUESTS="32"
export CONCURRENT_REQUESTS_PER_DOMAIN="2"
deploy/scripts/run-p0-soak.sh deploy/examples/egress-seeds.example.txt
```

## PoC 验证流程

1. 准备一台配置了辅助 IP 和 EIP 的爬虫节点。
2. 启动已开启本地 IP 轮换的 Scrapy worker。
3. 抓取受控 URL 集，其中包含 IP echo endpoint。
4. 验证外部观测到的公网 IP 分布。
5. 人为触发失败阈值，验证黑名单冷却行为。
6. 验证指标已暴露且可以被抓取。
7. 执行 24 小时稳定性测试，并与当前 Heritrix 基线对比吞吐和资源使用。

## 预期 P0 证据

- 发现的本地 IP 列表，并确认管理 IP 已被排除。
- echo endpoint 输出，展示外部观测到的公网 EIP。
- Redis key 证据，展示失败计数和黑名单 TTL。
- 指标快照，包含请求数、状态码计数、延迟、活跃 IP 数和黑名单数量。
- 24 小时运行摘要，包含 pages/sec、CPU、内存、错误率、黑名单比例和瓶颈说明。
- Redis 短暂不可用场景记录：worker 优先继续执行任务，并使用本地 fallback。

## P0 结果记录表

| 项目 | 目标 | 实测 | 结论 |
|------|------|------|------|
| 发现可用本地 IP 数 | >= 2 | 待填写 | 待填写 |
| 外部观测 EIP 数 | >= 2 | 待填写 | 待填写 |
| 黑名单 TTL 生效 | 是 | 待填写 | 待填写 |
| 24 小时平均吞吐 | >= 30 pages/sec | 待填写 | 待填写 |
| CPU 使用率 | < 50% | 待填写 | 待填写 |
| 内存使用 | < 4 GB | 待填写 | 待填写 |
| 错误率 | 仅记录，不设硬阈值 | 待填写 | 待填写 |
| Redis 短暂不可用降级 | 继续执行任务，使用本地 fallback | 待填写 | 待填写 |

## 待补充输入

- 云厂商和节点网络配置。
- 测试目标 URL。
- Redis endpoint。
- Oracle Cloud Object Storage endpoint。
