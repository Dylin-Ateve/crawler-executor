# 快速开始：P0 Scrapy 分布式爬虫 PoC

本文档定义 P0 的预期验证流程。

当前 P0 收尾状态见 `p0-validation-report.md`。截至 2026-04-27，核心出口链路与 Step 6 Redis 黑名单 TTL 均已验证通过，Step 9/10 稳定性测试后置。

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
- `REDIS_URL`：Redis 认证连接串，真实环境必须包含用户名和密码。
- `VALKEY_CLI`：Valkey 8.1 集群客户端，默认 `valkey-cli`。

## 本地准备

P0 代码位于仓库根目录下的 `src/crawler/`。建议在目标 Linux 爬虫节点上使用 Python 3.12 虚拟环境运行；当前代码保持 Python 3.9+ 兼容，方便本地做基础检查。

先确认 Python 版本。若低于 Python 3.9，需要先安装新版 Python；否则 Scrapy 和本项目依赖可能无法安装。

```bash
python3 --version
```

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

如果看到 `Directory '.' is not installable. File 'setup.py' not found.`，通常说明 pip 版本过旧。请先在虚拟环境内执行：

```bash
python -m pip install --upgrade pip setuptools wheel
```

如果目标节点暂时无法升级 pip，拉取包含 `setup.py` 的最新代码后，可直接走旧 pip 兼容路径：

```bash
python -m pip install -e ".[dev]"
```

如果 pip 版本较新但受 `pyproject.toml` build isolation 影响，可以在已安装 `setuptools` 和 `wheel` 后禁用 PEP 517：

```bash
python -m pip install --no-use-pep517 -e ".[dev]"
```

如果节点无法访问 PyPI，需要先配置内部 PyPI 镜像或离线 wheel 包，再执行安装。

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
| `REDIS_URL` | Redis 认证连接串，密码必须 URL encode；TLS 用 6379，非 TLS 用 7379 | `redis://crawler:CHANGE_ME_URL_ENCODED@redis-host:6379/0` |
| `CRAWL_INTERFACE` | 扫描辅助 IP 的网卡 | `ens3` |
| `EXCLUDED_LOCAL_IPS` | 管理 IP 排除列表，多个用逗号分隔 | `10.0.12.196,10.0.12.197` |
| `IP_SELECTION_STRATEGY` | IP 选择策略 | `STICKY_BY_HOST` |
| `CONCURRENT_REQUESTS` | 全局并发起步值 | `32` |
| `CONCURRENT_REQUESTS_PER_DOMAIN` | 单域名并发起步值 | `2` |
| `PROMETHEUS_PORT` | 指标端口 | `9410` |
| `FORCE_CLOSE_CONNECTIONS` | P0 多出口验证时关闭 HTTP keep-alive | `true` |
| `VALKEY_CLI` | Valkey 客户端命令或绝对路径 | `valkey-cli` |

## P0 验证 Runbook

### Redis 认证连接串格式

真实环境必须使用 Redis 用户名和密码认证，`REDIS_URL` 格式为：

```bash
REDIS_URL='redis://<username>:<url-encoded-password>@<host>:<port>/<db>'
```

示例：

```bash
REDIS_URL='redis://crawler:CHANGE_ME_URL_ENCODED@redis-host:6379/0'
```

如果密码包含 `@`、`:`、`/`、`#`、`%`、`&`、`!` 等特殊字符，必须先做 URL encode。只有密码、没有用户名的 Redis 旧式认证格式不作为本项目默认配置。

Tip：Valkey 连接端口按部署约定区分，使用 TLS 时采用 `6379`，不使用 TLS 时采用 `7379`。

仓库提供了密码编码工具，输入时不会回显原始密码：

```bash
deploy/scripts/encode-redis-password.py
```

将输出结果填入 `REDIS_URL` 的密码位置。整条 `REDIS_URL` 建议使用单引号包裹，避免 shell 对特殊字符做解释。

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
"${VALKEY_CLI:-valkey-cli}" -u "$REDIS_URL" ping
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
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
python -m pytest
```

预期结果：

- 单元测试和 middleware smoke test 全部通过。
- 当前基线为 `21 passed`。

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
export P0_VALIDATION_REPEAT="1"
deploy/scripts/run-egress-validation.sh /tmp/egress-seeds.txt
```

预期结果：

- 日志中出现 `p0_egress_observed`。
- `local_ip` 显示本地绑定的辅助 IP。
- `observed_ip` 显示公网侧观测到的 EIP。
- 非 200 响应也会输出 `p0_egress_observed`，用于记录状态码、绑定 IP 和外部观测结果。
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

### Step 5a：多出口覆盖诊断

如果 Step 4 只看到单个出口 IP，这是正常的：`STICKY_BY_HOST` 会让同一 Host 尽量复用同一出口。要诊断多出口覆盖，可以临时切到 `ROUND_ROBIN` 并重复请求 echo endpoint：

```bash
export IP_SELECTION_STRATEGY="ROUND_ROBIN"
export CONCURRENT_REQUESTS="8"
export CONCURRENT_REQUESTS_PER_DOMAIN="1"
export P0_VALIDATION_REPEAT="30"
export FORCE_CLOSE_CONNECTIONS="true"
deploy/scripts/run-egress-validation.sh /tmp/egress-seeds.txt
```

预期结果：

- 日志中出现多个不同的 `local_ip`。
- `observed_ip` 应对应多个公网 EIP。
- 如果多个 `local_ip` 仍只对应一个 `observed_ip`，先确认 `FORCE_CLOSE_CONNECTIONS=true` 已生效；否则 HTTP keep-alive 可能复用第一次建立的连接，掩盖不同 `bindaddress` 的实际效果。
- 诊断结束后，将 `IP_SELECTION_STRATEGY` 改回 `STICKY_BY_HOST`。

当前已验证结果：

- 44 次 `httpbin.org/ip` 请求可覆盖 40+ 个本地辅助 IP。
- `FORCE_CLOSE_CONNECTIONS=true` 时，外部可观测到多个公网 EIP。
- 该步骤证明 Scrapy `bindaddress`、本地辅助 IP 轮换、OCI EIP 映射链路均已打通。
- 该步骤不代表生产吞吐能力，因为关闭 keep-alive 会显著增加 TCP/TLS 建连成本。

### Step 5b：生产形态 keep-alive 验证

多出口覆盖验证通过后，需要切回生产预期形态：`STICKY_BY_HOST` + keep-alive。该步骤验证的是稳定性和吞吐，不要求同一个 Host 覆盖多个公网 EIP。

```bash
cat >/tmp/egress-httpbin-only.txt <<'EOF'
https://httpbin.org/ip
EOF

export IP_SELECTION_STRATEGY="STICKY_BY_HOST"
export FORCE_CLOSE_CONNECTIONS="false"
export CONCURRENT_REQUESTS="32"
export CONCURRENT_REQUESTS_PER_DOMAIN="2"
export P0_VALIDATION_REPEAT="100"

deploy/scripts/run-egress-validation.sh /tmp/egress-httpbin-only.txt 2>&1 | tee /tmp/p0-5b-sticky-keepalive.log
```

统计：

```bash
grep -o 'local_ip=[^ ]*' /tmp/p0-5b-sticky-keepalive.log | sort -u
grep -o 'observed_ip=[^ ]*' /tmp/p0-5b-sticky-keepalive.log | sort -u
grep -E "downloader/request_count|elapsed_time_seconds|response_status_count|retry/count" /tmp/p0-5b-sticky-keepalive.log
```

预期结果：

- 同一个 Host 在 `STICKY_BY_HOST` 下倾向于固定一个 `local_ip`。
- `observed_ip` 可以只有一个，这是生产粘滞策略下的正常现象。
- 相比 Step 5a，整体耗时应明显降低。
- 不应出现大量异常、重试或内存持续增长。

当前已验证结果：

- 100 次 `httpbin.org/ip` 请求均返回 200。
- `STICKY_BY_HOST` 下同一 Host 固定到 `local_ip=10.0.13.47`。
- 外部观测公网出口固定为 `observed_ip=161.153.93.183`，符合 Host 粘滞预期。
- 100 次请求耗时约 16.5 秒，未出现 retry。

### Step 6：Redis 黑名单验证

当前状态：已验证。2026-04-27 在 Valkey 8.1 集群上使用 `https://httpbin.org/status/503` 连续触发 5 次 503，Valkey 中出现 `crawler-executor:blacklist:httpbin.org:10.0.15.67`，reason 为 `HTTP_503`，TTL 约 1800 秒。历史测试中还存在未过期的 `crawler-executor:blacklist:httpbin.org:10.0.13.47`，TTL 约 1767 秒。

目标 Valkey 集群为 Valkey 8.1，客户端验证统一使用 `valkey-cli`。Step 6 测试脚本允许回显包含密码的 `REDIS_URL`，便于现场排查特殊字符、URL encode 和认证问题。

推荐直接运行 Step 6 专用脚本。脚本会：

- 使用 `valkey-cli -u "$REDIS_URL" ping` 验证认证连接。
- 临时请求 `https://httpbin.org/status/503`，并关闭 Scrapy retry，让 503 直接进入健康状态统计。
- 达到 `IP_FAILURE_THRESHOLD` 后检查 `${REDIS_KEY_PREFIX}:blacklist:*`。
- 打印黑名单 key、reason 和 TTL。

```bash
export VALKEY_CLI="valkey-cli"
export IP_FAILURE_THRESHOLD="5"
export IP_COOLDOWN_SECONDS="1800"
export RETRY_ENABLED="false"
export CONCURRENT_REQUESTS="1"
export CONCURRENT_REQUESTS_PER_DOMAIN="1"
export P0_VALIDATION_REPEAT="5"

deploy/scripts/run-step6-valkey-blacklist-validation.sh
```

如果需要改用其他会返回 403/429/503 的目标：

```bash
export P0_STEP6_URL="https://httpbin.org/status/429"
deploy/scripts/run-step6-valkey-blacklist-validation.sh
```

运行一轮抓取后检查 Redis 健康状态：

```bash
deploy/scripts/inspect-ip-health.sh
```

也可以直接查看 key：

```bash
"${VALKEY_CLI:-valkey-cli}" -u "$REDIS_URL" --scan --pattern "${REDIS_KEY_PREFIX:-crawler}:blacklist:*"
"${VALKEY_CLI:-valkey-cli}" -u "$REDIS_URL" --scan --pattern "${REDIS_KEY_PREFIX:-crawler}:fail:*"
```

预期结果：

- 正常 200 响应不应持续产生黑名单。
- 当目标返回 403/429/503 连续达到阈值时，应出现 `crawler:blacklist:<host>:<ip>` key。
- 黑名单 key 应有 TTL，并在冷却结束后自动消失。

检查 TTL：

```bash
"${VALKEY_CLI:-valkey-cli}" -u "$REDIS_URL" ttl "<blacklist-key>"
```

### Step 7：指标验证

Prometheus 指标服务运行在 Scrapy 进程内，只在 spider 运行期间可访问。前面的短验证通常几秒内结束，如果在 spider 结束后执行 curl，`/metrics` 不会有输出。

建议用一个较长验证任务或短时 soak 保持进程运行，然后在另一个终端检查指标。

终端 A：

```bash
export IP_SELECTION_STRATEGY="STICKY_BY_HOST"
export FORCE_CLOSE_CONNECTIONS="false"
export CONCURRENT_REQUESTS="32"
export CONCURRENT_REQUESTS_PER_DOMAIN="2"
export P0_VALIDATION_REPEAT="10000"

deploy/scripts/run-egress-validation.sh /tmp/egress-httpbin-only.txt
```

终端 B：

```bash
curl -s "http://127.0.0.1:${PROMETHEUS_PORT:-9410}/metrics" | grep crawler_
```

预期至少看到：

- `crawler_requests_total`
- `crawler_response_duration_seconds`
- `crawler_ip_active_count`
- `crawler_ip_blacklist_count`

如果仍无输出，先检查端口是否正在监听：

```bash
ss -ltnp | grep "${PROMETHEUS_PORT:-9410}"
```

如果没有监听，说明 spider 进程已经结束，或 Prometheus extension 没有启动。

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

当前状态：按本轮 P0 收尾安排暂时跳过，后续需要恢复执行。

正式 24 小时前，先跑 10 分钟或 1 小时：

```bash
export IP_SELECTION_STRATEGY="STICKY_BY_HOST"
export FORCE_CLOSE_CONNECTIONS="false"
export CONCURRENT_REQUESTS="32"
export CONCURRENT_REQUESTS_PER_DOMAIN="2"
export P0_SOAK_DURATION="10m"
deploy/scripts/run-p0-soak.sh /tmp/egress-seeds.txt
```

预期结果：

- 进程无异常退出。
- CPU、内存没有持续无界增长。
- Redis key 和指标正常更新。

### Step 10：24 小时 P0 稳定性测试

当前状态：按本轮 P0 收尾安排暂时跳过，后续需要恢复执行。

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
export REDIS_URL='redis://crawler:CHANGE_ME_URL_ENCODED@redis-host:6379/0'
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
export REDIS_URL='redis://crawler:CHANGE_ME_URL_ENCODED@redis-host:6379/0'
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
5. 人为触发失败阈值，验证黑名单冷却行为。当前 Step 6 已通过。
6. 验证指标已暴露且可以被抓取。
7. 执行 24 小时稳定性测试，并与当前 Heritrix 基线对比吞吐和资源使用。当前 Step 9/10 后置。

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
| 发现可用本地 IP 数 | >= 2 | Prometheus `crawler_ip_active_count=43`；Step 5a 日志覆盖 40+ 个本地辅助 IP | 通过 |
| 外部观测 EIP 数 | >= 2 | Step 5a 在 `FORCE_CLOSE_CONNECTIONS=true` 下观测到多个公网 EIP | 通过 |
| 生产形态 keep-alive | `STICKY_BY_HOST` 下稳定复用连接 | Step 5b 100 次 `httpbin.org/ip` 均 200，固定 `local_ip=10.0.13.47`、`observed_ip=161.153.93.183`，耗时约 16.5 秒 | 通过 |
| 黑名单 TTL 生效 | 是 | Step 6 使用 5 次 503 触发 Valkey 黑名单，key 为 `crawler-executor:blacklist:httpbin.org:10.0.15.67`，reason 为 `HTTP_503`，TTL 约 1800 秒 | 通过 |
| 指标暴露 | 请求、延迟、活跃 IP、黑名单数量可观测 | Step 7 已看到 `crawler_requests_total`、`crawler_response_duration_seconds`、`crawler_ip_active_count=43`、`crawler_ip_blacklist_count=0` | 通过 |
| 小规模真实目标 | Wikipedia、White House 等批准目标可抓取并记录状态 | Step 8 30 次请求均 200，耗时约 2.12 秒，内存约 69 MB | 通过 |
| 24 小时平均吞吐 | >= 30 pages/sec | 暂时跳过 Step 9/10 | 后置 |
| CPU 使用率 | < 50% | 暂时跳过 Step 9/10，未采集 | 后置 |
| 内存使用 | < 4 GB | 小规模验证约 69 MB；24 小时未采集 | 部分验证，长期后置 |
| 错误率 | 仅记录，不设硬阈值 | Step 8 为 0；Step 5a 诊断中有 1 次 502 重试，属于记录项 | 已记录 |
| Redis 短暂不可用降级 | 继续执行任务，使用本地 fallback | 暂未执行 Redis 故障注入 | 后置 |

## 待补充输入

- 云厂商和节点网络配置。
- 测试目标 URL。
- Redis endpoint。
- Oracle Cloud Object Storage endpoint。
