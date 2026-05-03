# ADR-0014: 控制平面策略作用域与 Redis Streams 边界

**状态**：已接受
**日期**：2026-05-03

## 背景

spec004 与 spec005 在 staging 等价镜像环境验证后，系统已形成当前事实：crawler-executor 通过 Redis / Valkey Streams consumer group 只读消费第六类 Fetch Command，通过 DaemonSet + hostNetwork 常驻运行，并以 `crawl_attempt` 作为唯一抓取事实事件。

复核 M4 前发现北极星文档仍残留两类不一致：

- `HostGroup` 被写成控制平面策略下发作用域，容易把 Heritrix 旧系统的分组语义带回第二类执行器。
- `scrapy-redis` 被写成未来只读消费形态，但 ADR-0004 / ADR-0005 已明确采用 Redis Streams consumer group，且不使用 scrapy-redis 默认 scheduler / dupefilter。

同时，代码里仍有少量 P1 第一版 `page_metadata` 兼容命名和 P0 包名，容易误导后续实现者以为系统仍处于旧 producer 或 P0 PoC 形态。

## 决策

1. crawler-executor 不把 `HostGroup` 作为一等概念。
2. M4 及后续控制平面策略作用域统一使用中性执行上下文：
   - `tier`
   - `site_id`
   - `host_id`
   - `politeness_key`
   - 可选 `policy_scope_id`
3. `policy_scope_id` 是控制平面或第六类解析后的 opaque identifier。crawler-executor 只消费，不维护成员关系，不计算分组归属，也不承载业务调度语义。
4. Fetch Command 下发载体以 Redis / Valkey Streams consumer group 为当前已接受形态。crawler-executor 只执行 `XREADGROUP`、`XACK`、`XAUTOCLAIM` 等消费确认与恢复协议，不写 URL 队列，不维护 scheduler / dupefilter。
5. `scrapy-redis` 不作为本系统运行时依赖、终态下发形态或后续目标。它只允许出现在历史研究、候选方案和“不采纳”ADR 上下文中。
6. `crawl_attempt` 应透传与一次抓取 attempt 相关的上游执行上下文。上游提供 `command_id`、`trace_id`、`job_id`、`host_id`、`site_id`、`tier`、`politeness_key` 或 `policy_scope_id` 时，事件中应保留这些字段，供第五类事实投影和控制平面审计使用。
7. 历史 `page_metadata` 代码入口和 P0 包名应从当前代码主路径清理；历史 spec 和契约文件可保留为追溯记录，但必须标明其历史兼容性质。

## 备选方案

- 继续沿用 `HostGroup`。不采纳。该词与 Heritrix 历史分组模型耦合，容易让 executor 承担分组成员管理和业务调度语义。
- 在 crawler-executor 内实现 HostGroup / policy group 解析。不采纳。策略解释和分组成员关系属于控制平面或第六类，本系统只执行已解析的抓取指令。
- 引入 scrapy-redis 作为只读 scheduler。已由 ADR-0005 不采纳。默认 scheduler / dupefilter 容易引入 URL 写入、去重和优先级语义。
- 保留 `page_metadata` 代码兼容入口。短期可运行，但不采纳为继续演进方向。当前唯一 producer 目标是 `crawl_attempt`。

## 后果

- 好处：M4 的边界更清晰，控制平面接入不会把 Heritrix 或 scheduler 语义带回第二类。
- 好处：北极星层、现状层、ADR 和代码命名对齐，后续 spec 门禁更容易判断是否越界。
- 好处：`crawl_attempt` 具备策略上下文追踪能力，第五类和控制平面可以按执行上下文做审计和过滤。
- 代价：需要一次短期文档和命名收口，清理历史 `page_metadata` 代码入口与 P0 包名。
- 后续：M4 仍需定义策略源、热加载周期、last-known-good、策略应用失败语义、全局 / 作用域 pause 行为和相关指标。

## 关联

- `specs/006-policy-scope-and-document-alignment/`
- `.specify/memory/product.md`
- `.specify/memory/architecture.md`
- `state/roadmap.md`
- ADR-0001
- ADR-0002
- ADR-0003
- ADR-0004
- ADR-0005
- ADR-0010
- ADR-0012
