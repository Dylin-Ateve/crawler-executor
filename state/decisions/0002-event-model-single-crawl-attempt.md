# ADR-0002: 事件模型收敛为单一 `crawl_attempt`

**状态**：已接受
**日期**：2026-04-29

## 背景

P1 第一版 producer 曾以成功页面 metadata 为中心验证对象存储和 Kafka 发布链路。后续讨论确认：抓取执行系统需要表达的是“一次抓取 attempt 的完整事实”，而不是只表达成功页面。

fetch 失败、非 HTML 响应、对象存储失败和成功快照都需要进入同一条可订阅事实流，由下游消费端自行投影为 `crawl_logs`、`page_snapshots`、`pages_latest` 等存储模型。

## 决策

本系统对外只发布单一 `crawl_attempt` 事件类型。事件承载 fetch / content / storage 三类正交结果，并以 `attempt_id` 作为 attempt 级幂等键。

事件发布规则：

- 成功 HTML：先写对象存储，再发布 `storage_result=stored` 的 `crawl_attempt`。
- 对象存储上传失败：仍发布 `crawl_attempt`，标记 `storage_result=failed`，不携带对象引用。
- 非 HTML 响应：仍发布 `crawl_attempt`，标记 `content_result=non_snapshot`、`storage_result=skipped`。
- fetch 失败：仍发布 `crawl_attempt`，标记 fetch 失败与后续阶段 skipped。

## 备选方案

- 多 topic：`page-metadata`、`crawl-events`、`parse-tasks` 分别发布。不采纳。producer 侧会承担过多下游投影和派发语义。
- 只对成功 HTML 发布 metadata。不采纳。失败事实不可追溯，下游无法形成完整抓取历史。
- producer 直接写 PostgreSQL 表。不采纳。事实层归第五类，本系统只负责发布事件。

## 后果

- 好处：事件语义统一，成功与失败都可追溯。
- 好处：下游消费端可以按自身需要投影数据库模型，不反向污染第二类边界。
- 好处：第三类内容加工直接订阅事件自取 `storage_key`，无需本系统派发 parse-tasks。
- 代价：P1 需要从 `page-metadata` producer 调整为 `crawl_attempt` producer，并补齐失败 / skipped 场景测试。
- 代价：下游消费端需要严格按 `attempt_id` 幂等处理 at-least-once 投递。

## 关联

- `.specify/memory/architecture.md`
- `specs/002-p1-content-persistence/`
- `specs/002-p1-content-persistence/contracts/crawl-attempt.schema.json`
