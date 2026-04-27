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
