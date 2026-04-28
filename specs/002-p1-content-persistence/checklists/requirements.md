# 需求质量检查表：P1 抓取内容可靠持久化与元数据投递

## 内容质量

- [x] 用户故事可以独立测试。
- [x] 成功标准可度量。
- [x] 已明确 P1 不包含下游解析服务。
- [x] OCI endpoint 和认证方式已确认。
- [x] OCI namespace、region 和 bucket 已确认。
- [x] OCI SDK 接入方式已确认。
- [x] Kafka broker、认证方式和 topic 命名已确认。

## 完整性

- [x] 对象存储先写、Kafka 后发的顺序已定义。
- [x] Kafka at-least-once 和消费端幂等语义已定义。
- [x] 消息 schema 已初步定义。
- [x] 上传失败和发布失败边界已定义。
- [x] 本地 outbox 不纳入 P1。
- [x] PostgreSQL/ClickHouse 不纳入 P1。

## 就绪度

- [x] P1 任务已拆分。
- [ ] P1 smoke test 脚本已实现。
- [ ] P1 真实环境验证数据已收集。
- [ ] P1 退出门禁已完成。
