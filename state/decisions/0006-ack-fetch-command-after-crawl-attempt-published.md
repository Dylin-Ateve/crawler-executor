# ADR-0006: `crawl_attempt` 发布成功后再确认抓取指令

**状态**：已接受
**日期**：2026-04-29

## 背景

003 中 Redis Streams 消息代表第六类下发的一条抓取指令。worker 消费后会发起抓取，并最终发布 `crawl_attempt` 作为系统群可追溯事实。

如果 worker 在 request 交给 Scrapy 后立即 `XACK`，后续 fetch、对象存储或 Kafka 失败可能导致指令已经消失但没有 attempt 事实。若永远不 ack 可重试失败，则消息会长期滞留 PEL，需要明确重试和终态失败规则。

## 决策

worker 只在 `crawl_attempt` 发布成功后执行 `XACK`。

每条 `XREADGROUP` 拉取到的消息最终必须进入三类结果之一：

1. **成功抓取**
   - HTML 成功：对象存储写入成功，发布 `crawl_attempt(storage_result=stored)`，然后 `XACK`。
   - 非 HTML / 404 / 410 等已获得 HTTP 响应且无需重试的场景：发布 `crawl_attempt(storage_result=skipped)`，然后 `XACK`。

2. **可重试失败**
   - 例如网络抖动、连接超时、临时 DNS 失败、对方 5xx、429、临时限流。
   - 不 `XACK`，消息留在 PEL。
   - 后续由 worker 通过 `XAUTOCLAIM` 或等价机制按 `min-idle-time` 接管重试。

3. **永久失败**
   - 例如 URL 格式非法、不支持的 URL scheme、404 / 410、投递次数超限、目标被判定为不可继续重试。
   - 发布终态 `crawl_attempt(fetch_result=failed 或 storage_result=skipped)`，然后 `XACK`。

必须定义最大投递次数，例如 `FETCH_QUEUE_MAX_DELIVERIES`。超过上限后将可重试失败转为永久失败，发布 `error_type=retry_exhausted` 的 `crawl_attempt` 后 `XACK`。

SIGTERM 处理：

- worker 收到 SIGTERM 后停止新的 `XREADGROUP`。
- 正在 fetch 的 request 允许完成。
- 若 `crawl_attempt` 发布成功，则 `XACK` 后退出。
- 不尝试清空 PEL；未完成消息交给 `XAUTOCLAIM`。

## 备选方案

- request 交给 Scrapy 后立即 `XACK`：不采纳。可能导致没有 attempt 事实的任务丢失。
- fetch 完成后、Kafka 发布前 `XACK`：不采纳。事件未进入系统群事实流，仍不可追溯。
- 永远不 ack 失败消息：不采纳。会导致 PEL 长期堆积，无法形成终态失败事实。
- SIGTERM 后尝试处理完整 PEL：不采纳。PEL 恢复是 `XAUTOCLAIM` 的职责，worker 退出逻辑应保持简单。

## 后果

- 好处：每条已 ack 的抓取指令都有可追溯的 `crawl_attempt`。
- 好处：Kafka 故障不会让指令无声消失。
- 好处：SIGTERM 处理简单，未完成消息交给 Streams 协议恢复。
- 代价：Kafka 发布失败或 worker 崩溃可能导致消息后续被重取，需要 attempt / command 幂等。
- 代价：需要实现投递次数上限和 `XAUTOCLAIM` 恢复策略。

## 关联

- ADR-0002
- ADR-0004
- `specs/003-p2-readonly-scheduler-queue/`
