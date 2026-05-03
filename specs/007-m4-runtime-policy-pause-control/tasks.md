# 任务：M4 运行时执行策略与停抓控制

**输入**：`spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/`  
**前置条件**：P2 Redis Streams 队列消费目标节点验证通过；M3a 自适应 politeness 已完成；ADR-0014 已接受。  
**当前状态**：本地实现与验证完成；staging / production 复刻不在本 spec 范围。

## 阶段 1：规格与契约

- [x] T001 创建 007 M4 规格，明确范围、非目标、成功标准和后置能力。
- [x] T002 定义 effective policy 契约文档和 JSON schema。
- [x] T003 定义 Fetch Command M4 行为增量：`deadline_at`、`max_retries`、policy context。
- [x] T004 定义 M4 metrics 契约。
- [x] T005 明确 `crawl_attempt` terminal skip 字段兼容策略。

## 阶段 2：策略模型与校验

- [x] T006 新增 `runtime_policy.py`，定义 `EffectivePolicyDocument`、`EffectivePolicy`、`ScopePolicy`、`PolicyDecision`。
- [x] T007 实现 effective policy JSON schema / 手写校验，覆盖字段类型、取值范围、schema version。
- [x] T008 实现重复 scope 检测，同一 `scope_type + scope_id` 重复时拒绝加载。
- [x] T009 实现从 Scrapy settings / env 构造 bootstrap default policy。
- [x] T010 实现固定匹配顺序：`policy_scope_id -> politeness_key -> host_id -> site_id -> tier -> default_policy`。
- [x] T011 为策略校验和匹配编写单元测试。

## 阶段 3：Policy provider 与 last-known-good

- [x] T012 新增 `policy_provider.py`，实现本地文件 / ConfigMap provider。
- [x] T013 增加 `RUNTIME_POLICY_PROVIDER`、`RUNTIME_POLICY_FILE`、`RUNTIME_POLICY_RELOAD_INTERVAL_SECONDS`、`RUNTIME_POLICY_LKG_MAX_AGE_SECONDS` 等 settings。
- [x] T014 实现 policy reload interval 与版本检测。
- [x] T015 实现 last-known-good 缓存，策略读取 / 校验失败时继续使用 LKG。
- [x] T016 实现无 LKG 时使用 bootstrap default policy 的启动路径。
- [x] T017 为 provider、reload、LKG 和 bootstrap 编写单元测试。

## 阶段 4：Fetch Command 解析与执行决策

- [x] T018 收口 `deadline_at` 解析：支持 ISO-8601 UTC，非法值按无效消息处理。
- [x] T019 收口 `max_retries` 解析：非整数、负数或超过安全上限按无效消息处理。
- [x] T020 将 policy decision 接入 `FetchQueueSpider` request 构造前路径。
- [x] T021 在 request meta 中记录 `policy_version`、`matched_policy_scope_type`、`matched_policy_scope_id`、`policy_lkg_active`。
- [x] T022 将 matched policy 的 `download_timeout_seconds`、`sticky_pool_size`、pacer 参数接入现有执行路径。
- [x] T023 确保没有命中 scope 时使用 default policy。

## 阶段 5：Pause 与 deadline terminal attempt

- [x] T024 在 request 构造前实现 pause 判断，命中时不发起 HTTP 请求。
- [x] T025 实现 pause terminal item / payload，发布 `error_type=paused` 的 `crawl_attempt`。
- [x] T026 在 request 构造前和 delayed buffer 重新尝试前实现 deadline 判断。
- [x] T027 实现 deadline terminal item / payload，发布 `error_type=deadline_expired` 的 `crawl_attempt`。
- [x] T028 确保 pause / deadline terminal attempt 遵守 Kafka 发布成功后才 `XACK`。
- [x] T029 为 pause / deadline 的成功发布、Kafka failure、PEL 留存编写单元或集成测试。

## 阶段 6：max_retries 生效

- [x] T030 定义 retry budget 计算优先级：command -> policy -> settings。
- [x] T031 将 retry budget 接入 fetch 层可重试 HTTP 状态和 errback 判断。
- [x] T032 确保 `max_retries=0` 时第一次 fetch 可重试失败即 terminal。
- [x] T033 确保 Kafka publish failure 不消耗 retry budget，不进入 terminal retry exhausted。
- [x] T034 为 max retries 编写单元 / 集成测试。

## 阶段 7：严格优雅停机

- [x] T035 修正 shutdown flag 入口，使 SIGTERM / SIGINT 到达后尽早停止读 / claim。
- [x] T036 确保 consumer shutdown 后不再调用 `XREADGROUP`。
- [x] T037 确保 consumer shutdown 后不再调用 `XAUTOCLAIM`。
- [x] T038 确保 delayed buffer 未执行消息在 shutdown 时不 `XACK`。
- [x] T039 明确 in-flight drain 行为和 drain timeout 日志。
- [x] T040 为 consumer、spider、SIGTERM / SIGINT 行为编写单元和目标脚本验证。

## 阶段 8：指标与日志

- [x] T041 增加 policy load result 指标。
- [x] T042 增加 current policy version、LKG active、LKG age 指标。
- [x] T043 增加 policy decision、pause skip、deadline expired、retry terminal 指标。
- [x] T044 增加 shutdown events、in-flight estimate、drain timeout 指标。
- [x] T045 审核 M4 指标 label，避免完整 URL、响应 body、凭据和高基数字段。

## 阶段 9：验证脚本

- [x] T046 编写 `deploy/scripts/run-m4-policy-reload-validation.sh`。
- [x] T047 编写 `deploy/scripts/run-m4-policy-lkg-validation.sh`。
- [x] T048 编写 `deploy/scripts/run-m4-pause-validation.sh`。
- [x] T049 编写 `deploy/scripts/run-m4-deadline-validation.sh`。
- [x] T050 编写 `deploy/scripts/run-m4-max-retries-validation.sh`。
- [x] T051 编写 `deploy/scripts/run-m4-graceful-shutdown-validation.sh`。
- [x] T052 在本地或 staging 等价环境执行 M4 验证脚本，并记录结果。

## 阶段 10：文档收口

- [x] T053 更新 `state/current.md`，记录 M4 实现状态和剩余生产化能力。
- [x] T054 更新 `state/roadmap.md`，按结果调整 M5 / M5a 后置项。
- [x] T055 更新 `state/changelog.md`，记录 M4 交付摘要。
- [x] T056 更新 README 当前状态摘要。
- [x] T057 若实现触碰策略优先级、业务合并或成员关系，先新增 ADR；否则明确无需新增 ADR；本轮未触碰，无需新增 ADR。

## 依赖与执行顺序

- 阶段 1 是所有实现任务前置。
- 阶段 2 / 3 可并行，但 spider 集成前必须完成稳定接口。
- 阶段 4 依赖阶段 2 / 3。
- 阶段 5 / 6 依赖阶段 4。
- 阶段 7 可与阶段 5 / 6 并行，但最终验证必须一起跑。
- 阶段 8 可与阶段 4-7 并行。
- 阶段 9 阻塞 M4 收口。
- 阶段 10 是交付收尾。
