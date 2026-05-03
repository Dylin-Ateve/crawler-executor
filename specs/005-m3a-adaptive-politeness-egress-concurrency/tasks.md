# 任务：M3a 自适应 Politeness 与出口并发控制

**输入**：`spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/`
**前置条件**：P2 Redis Streams 队列消费目标节点验证通过；ADR-0012 已接受。
**当前状态**：已完成。本地实现、验证脚本与 staging OKE 等价镜像环境验证均已通过；production 复刻验证作为发布流程后续执行。

## 阶段 1：规格与契约

- [x] T001 创建 005 M3a 规格草案，明确范围、非目标、成功标准和 004 恢复关系。
- [x] T002 定义 runtime env 契约：sticky-pool、pacer、soft-ban、delayed buffer、Redis 执行态。
- [x] T003 定义 Redis 执行态契约：允许 key、禁止 key、TTL 和审计口径。
- [x] T004 定义 metrics 契约：sticky-pool、pacer、delayed buffer、feedback、cooldown、slowdown。
- [x] T005 审核 production / staging env profile，准备将 production 从 `STICKY_BY_HOST` 切换到 `STICKY_POOL`。

## 阶段 2：纯逻辑模块

- [x] T006 新增 `egress_identity.py`，封装 bind IP / public IP / identity hash / identity type。
- [x] T007 新增或扩展 private-to-public egress 映射加载逻辑，缺失时 fallback 到 bind IP 并标注 `egress_identity_type=bind_ip`。
- [x] T008 新增 `egress_policy.py`，实现 host-aware sticky-pool 候选池生成。
- [x] T009 为 sticky-pool 编写单元测试：候选数量、重复运行稳定性、IP pool 变化的局部扰动。
- [x] T010 新增 `politeness.py`，实现 per-(host, egress_identity) pacer、jitter、指数 backoff 计算。
- [x] T011 为 pacer 编写单元测试：eligible 判断、next_allowed_at 推导、backoff 上限、host slowdown factor。
- [x] T012 新增 `response_signals.py`，实现 HTTP status、exception、body pattern 到 `FeedbackSignal` 的归一化。
- [x] T013 为 response signal 编写单元测试：429、challenge pattern、anti-bot 200、timeout、5xx 权重区分。

## 阶段 3：Redis 执行态

- [x] T014 新增 `fetch_safety_state.py`，实现 `host_ip` backoff、IP cooldown、host slowdown 的 Redis TTL 读写。
- [x] T015 实现 signal window counter，用于跨 host / 跨 IP 聚合 soft-ban 信号。
- [x] T016 为 Redis 执行态编写单元或集成测试：prefix、TTL、读写失败、fail-open 行为。
- [x] T017 增加 Redis key builder 测试，确保禁止 key pattern 不会由 005 代码生成。
- [x] T018 增加 Redis 写入边界审计 helper，供目标验证脚本复用。

## 阶段 4：Scrapy 与队列消费集成

- [x] T019 将出口选择从 `STICKY_BY_HOST` production / staging 路径切换为 `STICKY_POOL`，保留显式 fallback 策略。
- [x] T020 在 Request meta 中写入 `egress_identity`、`egress_identity_hash`、`egress_identity_type`、`download_slot`。
- [x] T021 设置 Scrapy `download_slot` 为 `{host}@{egress_identity}` 或等价语义。
- [x] T022 在 Fetch Command 调度到 Scrapy Request 前接入 pacer eligible 判断。
- [x] T023 实现本地 delayed buffer，保存未 eligible 的 Fetch Command。
- [x] T024 实现 delayed buffer 容量上限；满时停止 `XREADGROUP`。
- [x] T025 实现 `MAX_LOCAL_DELAY_SECONDS` 超限日志和指标，不 `XACK`、不发布虚假 `crawl_attempt`。
- [x] T026 确保 worker 停机时 delayed buffer 中未执行消息留 PEL。
- [x] T027 确保 Kafka publish failure、storage failure、fetch failed 分支仍遵守 ADR-0006 / ADR-0008。

## 阶段 5：反馈闭环

- [x] T028 在 response / exception 处理路径中生成 `FeedbackSignal`。
- [x] T029 根据同一 `(host, egress_identity)` soft-ban 信号更新 host-ip backoff。
- [x] T030 根据同一 egress identity 跨 host challenge 聚合更新 IP cooldown。
- [x] T031 根据同一 host 跨 egress identity challenge 聚合更新 host slowdown。
- [x] T032 增加 ASN / CIDR 指标分桶接口，第一版允许未配置时降级为 disabled。
- [x] T033 若启用 `HOST_ASN_SOFT_LIMIT_ENABLED`，实现 `(host, asn)` 短窗口 soft limit。

## 阶段 6：指标与观测

- [x] T034 增加 sticky-pool 选择和候选池大小指标。
- [x] T035 增加 pacer delay、delayed buffer size、oldest age、buffer full、XREADGROUP suppressed 指标。
- [x] T036 增加 feedback signal、host-ip backoff、IP cooldown、host slowdown 指标。
- [x] T037 增加 Redis 执行态读写结果和 TTL 指标。
- [x] T038 审核指标 label，避免完整 URL、响应 body、凭据和高基数 trace id。

## 阶段 7：验证脚本

- [x] T039 编写 `deploy/scripts/run-m3a-config-audit.sh`。
- [x] T040 编写 `deploy/scripts/run-m3a-sticky-pool-validation.sh`。
- [x] T041 编写 `deploy/scripts/run-m3a-pacer-validation.sh`。
- [x] T042 编写 `deploy/scripts/run-m3a-soft-ban-feedback-validation.sh`。
- [x] T043 编写 `deploy/scripts/run-m3a-delayed-buffer-validation.sh`。
- [x] T044 编写 `deploy/scripts/run-m3a-redis-boundary-validation.sh`。
- [x] T045 在本地或目标节点执行 005 验证脚本，记录结果到 `quickstart.md` 或验证报告。
- [x] T045a 在 staging OKE 等价镜像环境完成 DaemonSet、IP 池、Kafka publish smoke、PEL 清空和 M3a runtime 指标验证。

## 阶段 8：004 恢复准备

- [x] T046 更新 `deploy/environments/production.env`，将生产默认切换到 005 策略参数。
- [x] T047 更新 004 ConfigMap 契约和模板，移除 `STICKY_BY_HOST` 作为生产默认的残留。
- [x] T048 更新 004 quickstart 的恢复入口，加入 005 验证通过作为前置条件。
- [x] T049 更新 `state/current.md`、`state/roadmap.md`、`state/changelog.md`，记录 005 验证状态。
- [x] T050 若 005 实现发现需要写长期画像事实或非 TTL 状态，先新增 ADR，再继续；本轮未引入长期画像事实或非 TTL 状态。
- [x] T051 关闭 spec005，补充系统能力、staging 验证结果和 runtime 监控指标维度小结。

## 依赖与执行顺序

- 阶段 1 是所有实现任务前置。
- 阶段 2 可与阶段 3 并行，但 Scrapy 集成前必须完成核心接口。
- 阶段 4 依赖阶段 2 / 3。
- 阶段 5 依赖 response signal 和 Redis 执行态。
- 阶段 6 可与阶段 4 / 5 并行，但验证脚本前必须完成。
- 阶段 7 阻塞 005 收口。
- 阶段 8 是恢复 004 的前置准备。
