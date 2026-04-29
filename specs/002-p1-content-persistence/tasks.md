# 任务：P1 抓取内容可靠持久化与 crawl_attempt 投递

**输入**：`spec.md`、`plan.md`、P0 验证收尾报告
**范围**：对象存储、Kafka producer、schema 与验证脚本

说明：T001-T039 记录 P1 第一版 `page-metadata` producer 的完成情况。基于 2026-04-29 的设计结论，P1 目标调整为单一 `crawl_attempt` producer，新增 T040-T055 作为本轮调整任务。

## 阶段 1：规格与契约

- [x] T001 创建 `specs/002-p1-content-persistence/` 规格目录。
- [x] T002 定义 P1 用户故事、边界和成功标准。
- [x] T003 定义 `page-metadata` JSON schema。
- [x] T004 确认 `crawl-events` 不纳入 P1 发布链路。
- [x] T005 确认 `dead-letter` 不纳入 P1 发布链路。
- [x] T006 确认 OCI Object Storage namespace、region、bucket、endpoint、OCI SDK 接入方式和双认证模式。
- [x] T007 确认 Kafka broker、认证方式和 topic 命名。
- [x] T008 确认 P1 仅交付 producer 链路和契约，不包含 PostgreSQL/ClickHouse 消费者。

## 阶段 2：存储与消息基础模块

- [x] T009 在 `src/crawler/crawler/storage.py` 中定义对象存储客户端接口。
- [x] T010 使用 OCI SDK 实现 Oracle Cloud Object Storage 客户端。
- [x] T010a 实现 `OCI_AUTH_MODE` 认证工厂，支持 `api_key` 和 `instance_principal`，并保证业务 pipeline 无感。
- [x] T011 增加 fake object storage client，用于单元和集成测试。
- [x] T012 在 `src/crawler/crawler/publisher.py` 中定义 Kafka publisher 接口。
- [x] T013 实现 Kafka producer 配置，显式设置 ack、retry、timeout 和幂等相关参数。
- [x] T014 在 `src/crawler/crawler/schemas.py` 中实现 schema 校验辅助逻辑。

## 阶段 3：Scrapy Pipeline

- [x] T016 在 Scrapy pipeline 中生成 canonical URL、`url_hash` 和 `snapshot_id`。
- [x] T017 实现响应内容 hash、压缩和对象存储 key 生成。
- [x] T018 实现“先上传对象存储，再发布 `page-metadata`”。
- [x] T019 实现非 HTML 响应跳过对象存储和 Kafka，只记录日志与指标。
- [x] T020 实现 outlink 发现与统计，站外链接只记录不入队。
- [x] T021 对上传失败和 Kafka 发布失败增加结构化日志。
- [x] T022 暴露对象存储和 Kafka 指标。

## 阶段 4：测试

- [x] T023 增加对象存储 key 生成单元测试。
- [x] T024 增加内容压缩和 sha256 校验测试。
- [x] T025 增加 `page-metadata` schema 校验测试。
- [x] T026 增加非 HTML 响应不发布 Kafka 的测试。
- [x] T027 增加对象存储上传失败时不发布 metadata 的集成测试。
- [x] T028 增加 Kafka 发布失败时记录日志和指标的集成测试。
- [x] T029 增加非 HTML 响应不写对象存储的测试。

## 阶段 5：验证脚本与文档

- [x] T030 创建 `deploy/scripts/p1-object-storage-smoke.sh`。
- [x] T031 创建 `deploy/scripts/p1-kafka-smoke.sh`。
- [x] T032 创建 `deploy/scripts/run-p1-persistence-validation.sh`。
- [x] T033 更新 `deploy/examples/p0.env.example` 或新增 P1 env 示例。
- [x] T034 在 `quickstart.md` 记录真实环境验证结果。
- [x] T034a 创建 P1 对象存储失败验证脚本。
- [x] T034b 创建 P1 Kafka 失败验证脚本。

## 阶段 6：P1 退出评审

- [x] T035 收集对象存储写入与读取证据。
- [x] T036 收集 Kafka metadata 消息样例。
- [x] T037 验证对象存储失败不会发布 metadata。
- [x] T038 验证 Kafka 故障会记录发布失败日志和指标。
- [x] T039 决定是否进入 PostgreSQL/ClickHouse 消费者或 P2 编排部署。

## 阶段 7：crawl_attempt 契约调整

- [x] T040 定义 `crawl-attempt.schema.json` 契约草案。
- [x] T041 更新 `data-flow.md`，将 producer flow 从 `page-metadata` 调整为 `crawl_attempt`。
- [x] T042 更新 `data-model.md`，定义 `crawl_attempt` 与 `crawl_logs/page_snapshots/pages_latest` 投影关系。
- [x] T043 更新 `spec.md`、`plan.md`、`contracts/README.md` 和 `quickstart.md` 的目标语义。
- [x] T044 在代码中新增 `attempt_id` 生成逻辑。
- [x] T044a 确保 Scrapy 内部 retry 复用同一个 `attempt_id`。
- [x] T045 将 payload builder 从 `page-metadata` 调整为 `crawl_attempt`。
- [x] T046 增加 `fetch_result/content_result/storage_result` 字段生成逻辑。
- [x] T047 调整 Kafka 默认 topic 为 `crawler.crawl-attempt.v1`。
- [x] T048 成功 HTML 分支发布 `storage_result=stored` 的 `crawl_attempt`。
- [x] T049 非 HTML/非 200 分支发布 `storage_result=skipped` 的 `crawl_attempt`。
- [x] T050 对象存储失败分支发布 `storage_result=failed` 的 `crawl_attempt`。
- [x] T051 Kafka smoke 脚本调整为验证 `crawl_attempt`。
- [x] T052 端到端验证脚本调整为校验 `crawl_attempt.storage_key` 可读取。
- [x] T053 对象存储失败验证脚本调整为校验 `storage_result=failed`。
- [x] T054 补充 `crawl_attempt` schema 和 pipeline 单元测试。
- [x] T054a 增加 P1 T055 目标节点聚合验证脚本。
- [x] T055 在目标节点重新执行 P1 调整后验证。

## 依赖与执行顺序

- 阶段 1 阻塞阶段 2。
- 阶段 2 阻塞阶段 3。
- 阶段 3 阻塞真实端到端验证。
- 阶段 4 可随阶段 2/3 并行补充。
- 阶段 6 是进入下一阶段前的 P1 门禁。
- 阶段 7 是 P1 事件模型调整门禁；T044-T055 已完成，`002` 的 `crawl_attempt` producer 目标已通过目标节点验证。
