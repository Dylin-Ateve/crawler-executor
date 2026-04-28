# 任务：P1 抓取内容可靠持久化与元数据投递

**输入**：`spec.md`、`plan.md`、P0 验证收尾报告
**范围**：对象存储、Kafka producer、schema 与验证脚本

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

- [ ] T009 在 `src/crawler/crawler/storage.py` 中定义对象存储客户端接口。
- [ ] T010 使用 OCI SDK 实现 Oracle Cloud Object Storage 客户端。
- [ ] T010a 实现 `OCI_AUTH_MODE` 认证工厂，支持 `api_key` 和 `instance_principal`，并保证业务 pipeline 无感。
- [ ] T011 增加 fake object storage client，用于单元和集成测试。
- [ ] T012 在 `src/crawler/crawler/publisher.py` 中定义 Kafka publisher 接口。
- [ ] T013 实现 Kafka producer 配置，显式设置 ack、retry、timeout 和幂等相关参数。
- [ ] T014 在 `src/crawler/crawler/schemas.py` 中实现 schema 校验辅助逻辑。

## 阶段 3：Scrapy Pipeline

- [ ] T016 在 Scrapy pipeline 中生成 canonical URL、`url_hash` 和 `snapshot_id`。
- [ ] T017 实现响应内容 hash、压缩和对象存储 key 生成。
- [ ] T018 实现“先上传对象存储，再发布 `page-metadata`”。
- [ ] T019 实现非 HTML 响应跳过对象存储和 Kafka，只记录日志与指标。
- [ ] T020 实现 outlink 发现与统计，站外链接只记录不入队。
- [ ] T021 对上传失败和 Kafka 发布失败增加结构化日志。
- [ ] T022 暴露对象存储和 Kafka 指标。

## 阶段 4：测试

- [ ] T023 增加对象存储 key 生成单元测试。
- [ ] T024 增加内容压缩和 sha256 校验测试。
- [ ] T025 增加 `page-metadata` schema 校验测试。
- [ ] T026 增加非 HTML 响应不发布 Kafka 的测试。
- [ ] T027 增加对象存储上传失败时不发布 metadata 的集成测试。
- [ ] T028 增加 Kafka 发布失败时记录日志和指标的集成测试。
- [ ] T029 增加非 HTML 响应不写对象存储的测试。

## 阶段 5：验证脚本与文档

- [ ] T030 创建 `deploy/scripts/p1-object-storage-smoke.sh`。
- [ ] T031 创建 `deploy/scripts/p1-kafka-smoke.sh`。
- [ ] T032 创建 `deploy/scripts/run-p1-persistence-validation.sh`。
- [ ] T033 更新 `deploy/examples/p0.env.example` 或新增 P1 env 示例。
- [ ] T034 在 `quickstart.md` 记录真实环境验证结果。

## 阶段 6：P1 退出评审

- [ ] T035 收集对象存储写入与读取证据。
- [ ] T036 收集 Kafka metadata 消息样例。
- [ ] T037 验证对象存储失败不会发布 metadata。
- [ ] T038 验证 Kafka 故障会记录发布失败日志和指标。
- [ ] T039 决定是否进入 PostgreSQL/ClickHouse 消费者或 P2 编排部署。

## 依赖与执行顺序

- 阶段 1 阻塞阶段 2。
- 阶段 2 阻塞阶段 3。
- 阶段 3 阻塞真实端到端验证。
- 阶段 4 可随阶段 2/3 并行补充。
- 阶段 6 是进入下一阶段前的 P1 门禁。
