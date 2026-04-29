# 任务：P0 Scrapy 分布式爬虫 PoC

**输入**：`spec.md`、`plan.md`、`.specify/memory/product.md`、`.specify/memory/architecture.md`
**范围**：仅覆盖 P0 单节点 PoC

## 阶段 1：P0 初始化

- [x] T001 在 `src/crawler/` 下创建 Python/Scrapy 项目骨架。
- [x] T002 增加 Scrapy、Redis client、Prometheus client、IP 发现库和 pytest 的依赖定义。
- [x] T003 创建配置模块，覆盖 `CRAWL_INTERFACE`、`EXCLUDED_LOCAL_IPS`、IP 策略、Redis URL、冷却阈值和 Scrapy 并发配置。
- [x] T004 在 `specs/001-scrapy-distributed-crawler/quickstart.md` 中补充本地运行说明。

## 阶段 2：IP 与 Redis 基础行为

- [x] T005 [P] 在 `src/crawler/crawler/ip_pool.py` 中实现本地 IPv4 发现。
- [x] T006 [P] 在 `tests/unit/test_ip_pool.py` 中增加 IP 发现过滤逻辑单元测试。
- [x] T007 在 `src/crawler/crawler/ip_pool.py` 中实现 Host/IP 选择逻辑。
- [x] T008 [P] 在 `tests/unit/test_ip_pool.py` 中增加 `STICKY_BY_HOST` 和 `ROUND_ROBIN` 选择策略单元测试。
- [x] T009 在 `src/crawler/crawler/health.py` 中实现 Redis 黑名单与失败计数辅助逻辑。
- [x] T010 [P] 在 `tests/unit/test_health.py` 中增加黑名单 key 格式和阈值行为单元测试。
- [x] T010a [P] 在 `src/crawler/crawler/contracts/canonical_url.py` 中独立抽象 canonical URL 契约。
- [x] T010b [P] 在 `tests/unit/test_canonical_url.py` 中增加 canonical URL 契约单元测试。

## 阶段 3：Scrapy Middleware 切片

- [x] T011 在 `src/crawler/crawler/middlewares.py` 中实现 `LocalIpRotationMiddleware`。
- [x] T012 在 `src/crawler/crawler/middlewares.py` 中实现 `IpHealthCheckMiddleware`。
- [x] T013 在 `src/crawler/crawler/settings.py` 中配置 Scrapy downloader middleware 顺序。
- [x] T014 在 `src/crawler/crawler/spiders/egress_validation.py` 中增加最小验证 spider。
- [x] T015 在 `tests/integration/test_egress_middleware.py` 中增加 middleware metadata 绑定集成 smoke test。

## 阶段 4：可观测性

- [x] T016 在 `src/crawler/crawler/metrics.py` 中实现 Prometheus 指标。
- [x] T017 暴露请求总数、状态码总数、响应耗时、活跃 IP 数和黑名单数量。
- [x] T018 增加运行日志，输出 echo endpoint 观测到的出口 IP。

## 阶段 5：P0 验证脚本

- [x] T019 在 `deploy/scripts/run-egress-validation.sh` 中创建 echo endpoint 验证脚本。
- [x] T020 在 `deploy/scripts/inspect-ip-health.sh` 中创建 Redis 黑名单 key 检查脚本。
- [x] T021 在 `deploy/scripts/run-p0-soak.sh` 中创建 24 小时 PoC 运行命令。
- [x] T022 在 `specs/001-scrapy-distributed-crawler/quickstart.md` 中记录预期 PoC 证据和结果表。

## 阶段 6：P0 退出评审

- [x] T023 收集验证运行中观测到的 EIP 分布。
- [x] T024 收集 Step 4、Step 5a、Step 5b、Step 7、Step 8 的 P0 验证结果。
- [x] T025 Step 6 Redis 黑名单 TTL 端到端验证。
- [x] T026 Step 9/10 短时与 24 小时稳定性测试当前后置，不作为进入 P1 的阻塞项。
- [x] T027 Heritrix 基线对比当前后置，等待后续稳定性数据再补。
- [x] T028 已决定基于 P0 核心通路验证结果进入 P1 存储与 Kafka 规格拆解。

## 依赖与执行顺序

- 阶段 1 阻塞所有实现工作。
- 阶段 2 阻塞 Scrapy middleware 行为。
- 阶段 3 阻塞真实出口验证。
- 阶段 4 和阶段 5 可在阶段 3 完成后推进。
- 阶段 6 是进入 P1 规划前的 P0 门禁。
