# 需求质量检查表：P2 第六类队列只读消费与多 worker 运行形态

## 内容质量

- [x] 用户故事可以独立测试。
- [x] 成功标准可度量。
- [x] 已明确 003 不包含第五类事实投影。
- [x] 已明确 Redis 队列写入侧归第六类。
- [x] 已明确本系统不 enqueue outlinks。
- [x] 队列协议已确认：Redis Streams consumer group。
- [x] 已明确第六类不提供 `attempt_id`，本系统基于 `job_id + canonical_url` 生成。
- [x] 已明确 `canonical_url` 是 Fetch Command 必填字段。
- [x] 已明确无效消息直接丢弃并记录日志 / 指标。
- [x] 已明确 003 不规划 DLQ，未来如启用归第六类。

## 完整性

- [x] stored / skipped / storage failed 复用 P1 语义。
- [x] fetch failed 事件化已列为 003 范围。
- [x] 多 worker 消费验收已定义。
- [x] 无效消息处理已定义。
- [x] 只读边界验收已定义。
- [x] `host_id` / `site_id` 字段已进入契约，当前允许为空。
- [x] PostgreSQL/ClickHouse 不纳入 003。

## 就绪度

- [x] ADR-0003 已创建。
- [x] ADR-0004 已创建。
- [x] ADR-0005 已创建。
- [x] ADR-0006 已创建。
- [x] ADR-0007 已创建。
- [x] 003 任务已拆分。
- [x] research 已确认不使用 scrapy-redis 默认 scheduler / dupefilter。
- [ ] quickstart 命令已实现。
- [ ] 真实环境验证数据已收集。
