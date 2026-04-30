# 任务：P2 第六类队列只读消费与多 worker 运行形态

**输入**：`spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/`
**前置条件**：P1 `crawl_attempt` producer 已通过 T055 验证；ADR-0003 已接受。

## 阶段 1：规格与研究

- [x] T001 确认第六类队列协议：Redis Streams consumer group。
- [x] T002 确认不引入 scrapy-redis 默认 scheduler / dupefilter。
- [x] T003 确认使用自定义轻量 Redis Streams consumer。
- [x] T004 固化 `contracts/redis-fetch-command.md` 消息字段。

## 阶段 2：队列消费基础

- [x] T005 在 `src/crawler/crawler/queues.py` 中定义 Fetch Command 数据结构与解析逻辑。
- [x] T006 在 `src/crawler/crawler/queues.py` 中实现队列 consumer 接口。
- [x] T007 实现 Redis / Valkey 队列读取逻辑。
- [x] T008 实现 ack / pending / reclaim 或等价消费确认逻辑。
- [x] T009 在 `src/crawler/crawler/settings.py` 中增加队列配置。
- [x] T010 增加无效消息直接丢弃处理，不让 worker 崩溃，并记录日志与指标。
- [x] T010a 实现基于 `job_id + canonical_url` 的确定性 `attempt_id` 生成逻辑。

## 阶段 3：Scrapy 集成

- [x] T011 新增或改造队列驱动 spider，从 Fetch Command 构造 Scrapy request。
- [x] T012 将 command 上下文字段映射到 request meta。
- [x] T012a 将 Fetch Command 的 `canonical_url` 作为 `url_hash` 与 `attempt_id` 输入。
- [x] T013 确保 outlinks 只统计不 enqueue。
- [x] T014 复用 P1 pipeline 发布成功 HTML、非 HTML、storage failed 和 Kafka failed 场景。
- [x] T015 实现 Scrapy errback，将 DNS / TCP / timeout 等连接级失败转为 `crawl_attempt(fetch_result=failed)`。
- [x] T015a 实现 `crawl_attempt` 发布成功后再 `XACK`。
- [x] T015b 实现可重试失败不 ack、超过最大投递次数后发布终态失败再 ack。
- [ ] T015c 实现 ADR-0009 / FR-022 优雅停机语义，按子任务拆解（当前实现满足 PEL 不清空与可恢复底线；目标节点验证发现严格 "SIGTERM 后立即停止 `XREADGROUP` / `XAUTOCLAIM` 并在 drain 时限前退出" 未满足，按低频手动滚动、任务幂等、允许少量重复抓取的运行假设暂时接受为过渡策略）：
  - [x] T015c-1 在 `src/crawler/crawler/queues.py` 增加共享停机标志：`RedisStreamsFetchConsumer` 暴露 `request_shutdown()` 与 `is_shutting_down` 属性；`read()` 在停机态下不再发起 `XREADGROUP` 与 `XAUTOCLAIM`，立即返回空列表；`ack()` 维护 `acked_count` 用于退出总结日志。
  - [x] T015c-2 在 `src/crawler/crawler/spiders/fetch_queue.py` 的 `start()` 循环每次迭代前检查 `consumer.is_shutting_down`，命中则退出循环；不注册自定义 `signal.signal()` handler。
  - [x] T015c-3 通过 Scrapy `spider_closed` 信号触发 `consumer.request_shutdown()`，并通过 `engine_stopped` 信号输出退出总结日志，二者均不接管 Scrapy 自身关停流程。
  - [x] T015c-4 在 `src/crawler/crawler/settings.py` 增加 `FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS`，缺省 25。drain 时限超过后由 `engine_stopped` 总结日志标记 `drain_timeout=true`。
  - [x] T015c-5 复用现有 `metrics.record_fetch_queue_event` 计数 `shutdown`；spider 入口日志 `fetch_queue_shutdown_signal_received`、退出日志 `fetch_queue_shutdown_loop_exit` 各一条，退出日志包含 `seen_messages` / `acked_count` / `in_flight_estimate` / `drain_timeout`。
  - [x] T015c-6 单元测试覆盖：consumer 停机后 `read()` / `reclaim_pending()` 不再调用 redis（`tests/unit/test_queues.py`）；spider `_on_spider_closed` / `_on_engine_stopped` 行为与 `start()` 在停机态立即退出（`tests/unit/test_fetch_queue_shutdown.py`）。
  - [x] T015c-7 创建 `deploy/scripts/run-p2-graceful-shutdown-validation.sh`，覆盖 SIGTERM 退出耗时、`XLEN` 不变、PEL 留存与 `times_delivered`、停机入口与退出日志四类断言。
  - [x] T015c-8 同一脚本 Phase 2 验证 SIGINT 与 SIGTERM 同语义；Phase 3 验证 SIGHUP 不触发 `fetch_queue_shutdown_signal_received`，沿用进程默认行为；SIGQUIT 因默认 core dump 不在脚本内验证，由 ADR-0009 §1 直接声明。
  - [ ] T015c-9 修正严格优雅停机入口：目标节点验证显示 `consumer.request_shutdown()` 当前在 `spider_closed` 才触发，晚于 SIGTERM 到达，退出中的 worker 仍可能继续 `XREADGROUP` / `XAUTOCLAIM`；后续需在更早的 Scrapy / Twisted 关停入口或受控 signal handler 中设置停机标志。
  - [ ] T015c-10 修正 drain deadline 语义：`FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS` 当前只用于退出总结日志，不强制进程在时限内结束；后续需明确是否主动关闭剩余 in-flight 或调整 FR-022 / ADR-0009 的严格退出要求。

## 阶段 4：指标与日志

- [x] T016 增加队列读取成功 / 空队列 / 无效消息 / ack 成功 / ack 失败指标。
- [x] T017 增加 fetch failed 指标和结构化日志。
- [x] T018 增加只读边界验证日志，便于审计 Redis 写入行为。

## 阶段 5：测试

- [x] T019 增加 Fetch Command 解析单元测试。
- [x] T020 增加无效消息单元测试。
- [x] T021 增加 request meta 映射测试。
- [x] T022 增加 fetch failed payload 测试。
- [x] T023 增加 outlinks 不入队测试。
- [ ] T024 增加多 worker 消费集成测试。
- [ ] T025 增加 Redis 只读边界测试。
- [x] T025a 增加同一 `job_id + canonical_url` 重复投递生成相同 `attempt_id` 的测试。

## 阶段 6：验证脚本与文档

- [x] T026 创建 `deploy/scripts/p2-enqueue-fetch-commands.sh`。
- [x] T027 创建 `deploy/scripts/run-p2-queue-consumer-validation.sh`。
- [x] T028 创建 `deploy/scripts/run-p2-multi-worker-validation.sh`。
- [x] T029 创建 `deploy/scripts/run-p2-readonly-boundary-validation.sh`。
- [x] T030 创建 `deploy/scripts/run-p2-invalid-command-validation.sh`。
- [x] T030a 创建 `deploy/scripts/run-p2-kafka-failure-pending-validation.sh`，对齐 ADR-0008 三阶段语义。
- [x] T031 更新 `quickstart.md` 的真实验证记录。

## 阶段 7：P2 退出评审

- [x] T032 验证单 worker 消费并发布 `crawl_attempt`。
- [x] T033 验证多 worker 正常 ack 路径无重复处理。
- [x] T034 验证 executor 不写 URL 队列、不 enqueue outlinks（已覆盖 key diff 与目标 stream `XLEN` 前后不变；更宽 audit pattern 仍由 T025 跟踪）。
- [x] T035 验证连接级 fetch failed 发布 `crawl_attempt(fetch_result=failed)`。
- [x] T036 验证 Kafka 发布失败的三阶段不变量（按 ADR-0008）：(1) Kafka 不可达时 worker 不 `XACK`、消息留 PEL；(2) 第二个 worker 通过 `XAUTOCLAIM` 接管同一消息且 `times_delivered` 递增，仍不 ack；(3) Kafka 恢复后 worker 完成发布并 `XACK`，PEL 清空。不验证"达到 max_deliveries 后发布终态 attempt"，该语义在 Kafka 层不适用。
- [x] T037 验证无效消息被丢弃、记录日志和指标，且不写入本系统 DLQ。
- [x] T038 更新 `state/current.md`、`state/roadmap.md`、`state/changelog.md`。

## 依赖与执行顺序

- 阶段 1 阻塞阶段 2。
- 阶段 2 阻塞阶段 3。
- 阶段 3 阻塞阶段 5 和真实验证。
- 阶段 4 可与阶段 3 并行。
- 阶段 6 在主要实现完成后执行。
- 阶段 7 是进入 M3 前的门禁。
