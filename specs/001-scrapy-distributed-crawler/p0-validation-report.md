# P0 验证收尾报告

**日期**：2026-04-27
**范围**：单节点 Scrapy 多出口 IP PoC
**结论**：P0 核心出口链路与 Redis 黑名单 TTL 触发链路已完成验证。短时和 24 小时稳定性测试、Heritrix 对比、Redis 故障注入作为后置增强项，不再阻塞进入 P1。

## 验证环境

- 目标系统：Oracle Linux Server 8.10。
- Python：目标节点最终使用 Python 3.9.25。
- Scrapy：2.13.4。
- 目标网卡：暂按 `ens3` 配置。
- 出口 IP：节点上约 44 个辅助私网 IP，并映射到公网 EIP。
- Redis：要求使用 `redis://<username>:<url-encoded-password>@<host>:<port>/<db>` 认证连接串。

## 已完成验证

| 步骤 | 目标 | 结果 | 状态 |
|------|------|------|------|
| Step 4 | 低风险出口验证 | `httpbin.org/ip` 返回 200，日志输出 `p0_egress_observed`，可看到本地绑定 IP 和公网观测 IP | 通过 |
| Step 5a | 多出口覆盖诊断 | `ROUND_ROBIN` + `FORCE_CLOSE_CONNECTIONS=true` 下，44 次 `httpbin.org/ip` 请求覆盖 40+ 个本地辅助 IP，并观测到多个公网 EIP | 通过 |
| Step 5b | 生产形态 keep-alive 验证 | `STICKY_BY_HOST` + keep-alive 下，100 次请求均 200，固定 `local_ip=10.0.13.47`、`observed_ip=161.153.93.183`，耗时约 16.5 秒，无 retry | 通过 |
| Step 6 | Redis/Valkey 黑名单 TTL 验证 | Valkey 8.1 上连续 5 次请求 `https://httpbin.org/status/503`，触发 `crawler-executor:blacklist:httpbin.org:10.0.15.67`，reason 为 `HTTP_503`，TTL 约 1800 秒 | 通过 |
| Step 7 | Prometheus 指标验证 | 已看到 `crawler_requests_total`、`crawler_response_duration_seconds`、`crawler_ip_active_count=43`、`crawler_ip_blacklist_count=0` | 通过 |
| Step 8 | 小规模真实目标验证 | 30 次请求均 200，耗时约 2.12 秒，内存约 69 MB | 通过 |

## 后置验证

| 步骤 | 项目 | 当前处理 |
|------|------|----------|
| Step 9 | 短时稳定性测试 | 本轮收尾暂时跳过，后续恢复 |
| Step 10 | 24 小时 P0 稳定性测试 | 本轮收尾暂时跳过，后续恢复 |
| Heritrix 对比 | 吞吐、资源和错误记录对比 | 等 Step 9/10 数据补齐后再做 |
| Redis 故障降级 | Redis 短暂不可用时本地 fallback 行为 | 暂未做故障注入 |
| 黑名单自动退出观察 | TTL 到期后 key 自动消失并可重新选择该 Host/IP | 当前已验证 TTL 为正数，自动过期可在冷却窗口结束后补充观察 |

## 关键判断

- Scrapy `Request.meta["bindaddress"]` 与本机辅助 IP 绑定链路成立。
- OCI 辅助私网 IP 到公网 EIP 的映射在真实节点上可被公网 echo endpoint 观测到。
- `Connection: close` 只作为多出口覆盖诊断手段使用；生产形态应保持 keep-alive，并依赖 `STICKY_BY_HOST` 降低连接重建成本。
- 指标服务只在 Scrapy 进程运行期间可访问；短任务结束后 `/metrics` 没有输出是预期现象。
- P0 目前可以支撑进入下一轮设计讨论，但正式扩大到 P1 存储与 Kafka 前，建议至少补一次短时稳定性测试。

## 后续待办

1. 在 Step 6 冷却窗口结束后观察黑名单 key 是否自动消失。
2. 执行 Step 9：10 分钟或 1 小时短时 soak，记录 pages/sec、CPU、内存、错误率和 Redis key 变化。
3. 视 Step 9 结果决定是否执行 Step 10：24 小时稳定性测试。
4. 补齐 Heritrix 对比摘要，用于后续容量评估和发布策略，而不是阻塞 P1 规格拆解。

## P0 收尾决定

- P0 以“核心通路验证完成”收尾：本地辅助 IP 出口、Host 粘滞、诊断轮换、Redis/Valkey 黑名单 TTL、Prometheus 指标和小规模真实目标均已跑通。
- Step 9/10 稳定性测试不再作为当前进入 P1 的阻塞项；后续可在 P1 开发期间作为并行压测补充。
- Heritrix 对比依赖稳定性数据，暂不在当前收尾中展开。
- P1 从 `specs/002-p1-content-persistence/` 开始，聚焦对象存储、Kafka 元数据投递和消费端幂等契约。
