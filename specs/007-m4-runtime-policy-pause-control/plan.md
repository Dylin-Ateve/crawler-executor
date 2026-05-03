# 实施计划：M4 运行时执行策略与停抓控制

**分支**：`007-m4-runtime-policy-pause-control`  
**日期**：2026-05-03  
**规格文档**：`specs/007-m4-runtime-policy-pause-control/spec.md`

## 摘要

007 在 P2 Redis Streams 消费、P1 `crawl_attempt` producer、M3 K8s staging 验证和 M3a 自适应 politeness 已完成的基础上，补齐运行时控制能力。第一版不等待上游控制平面建成，而是使用本地文件 / ConfigMap provider 承载 future-compatible effective policy，验证热加载、last-known-good、全局 / 作用域 pause、`deadline_at`、`max_retries` 和严格优雅停机。

007 不做 production 复刻，不做 Kafka outbox，不做 DLQ，不做完整 Grafana / 告警落地。

## 技术上下文

**语言/版本**：Python 3.9+  
**主要依赖**：Scrapy、Redis / Valkey client、Prometheus client、Kafka client、OCI SDK  
**输入协议**：Redis / Valkey Streams Fetch Command，沿用 `crawl:tasks` / consumer group 形态  
**输出协议**：单一 `crawl_attempt` Kafka 事件，沿用 P1 / P2 schema 并保持向后兼容  
**策略源**：本地 JSON 文件或 K8s ConfigMap volume，后续可替换为控制平面 provider  
**测试**：pytest、Redis 集成测试、可控 HTTP test server、信号 / 子进程验证脚本  
**目标平台**：Linux crawler node；K8s `hostNetwork` pod 由 M3 已验证，production 复刻后置到 M5  
**性能目标**：不承诺 30-50 pages/sec 压测收口；本阶段验证运行时控制语义正确、有界、可观测  
**约束**：不写 URL 队列；不重排第六类业务优先级；不持有长期策略成员关系；`crawl_attempt` 发布成功后才 `XACK`

## 门禁检查

| 门禁 | 来源 | 结果 | 说明 |
|---|---|---|---|
| 章程门禁 | `.specify/memory/constitution.md` | 通过 | 先定义 spec、plan、data model、contracts、quickstart 和 tasks。 |
| 产品门禁 | `.specify/memory/product.md` | 通过 | 只做执行层运行时控制，不做 URL 选择、优先级或重抓窗口。 |
| 架构门禁 | `.specify/memory/architecture.md` | 通过 | 符合控制平面执行策略作用域、短窗口执行安全和只读队列边界。 |
| 决策门禁 | `state/decisions/` | 通过 | 遵守 ADR-0003/0004/0006/0007/0008/0009/0010/0012/0014。 |
| 路线图对齐 | `state/roadmap.md` | 通过 | 对应 M4；production 复刻、outbox、DLQ 和完整观测后置。 |

## 项目结构

### 文档

```text
specs/007-m4-runtime-policy-pause-control/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── effective-policy.schema.json
│   ├── effective-policy.md
│   ├── fetch-command-m4.md
│   └── metrics.md
└── tasks.md
```

### 预期源码 / 测试结构

```text
src/crawler/crawler/
├── runtime_policy.py          # effective policy model、validation、matching、LKG
├── policy_provider.py         # local file / ConfigMap provider
├── queues.py                  # deadline_at / max_retries 解析收口
├── spiders/fetch_queue.py     # policy decision、pause、deadline、retry、shutdown 集成
├── pipelines.py               # terminal skip attempt 发布 / ack 集成
├── schemas.py                 # crawl_attempt 可选字段 / error type 兼容
├── metrics.py                 # M4 运行时控制指标
└── settings.py                # policy provider 与 reload env

deploy/scripts/
├── run-m4-policy-reload-validation.sh
├── run-m4-policy-lkg-validation.sh
├── run-m4-pause-validation.sh
├── run-m4-deadline-validation.sh
├── run-m4-max-retries-validation.sh
└── run-m4-graceful-shutdown-validation.sh

tests/
├── unit/
└── integration/
```

**结构决策**：策略模型和 provider 独立成模块，避免把策略读取、校验、匹配和 LKG 全部塞进 spider。`FetchQueueSpider` 只消费 `PolicyDecision`，并在 request 构造前执行 pause / deadline / max retries 判断。

## 关键设计约束

### 1. Effective policy 边界

- 策略文件必须是 effective policy，而不是控制平面原始策略。
- executor 不计算业务优先级，不合并策略树，不维护 Host/Site 成员关系。
- 第一版只基于 Fetch Command 已携带的上下文字段做精确匹配。
- 同一 scope type + scope id 重复出现视为策略非法。

### 2. Provider 与 LKG

- 本地文件 / ConfigMap provider 是第一版策略源。
- 成功校验并应用的策略成为 current policy 和 LKG。
- 读取失败、JSON 错误、schema 错误、重复 scope 或字段越界时，不覆盖 LKG。
- 启动时没有有效策略和 LKG 时，从 env / settings 生成 bootstrap default policy。

### 3. Pause / deadline terminal attempt

- pause 和 deadline 都发生在发起 HTTP 请求前。
- 命中 pause / deadline 必须发布 terminal `crawl_attempt`，发布成功后才 `XACK`。
- Kafka 发布失败时不 `XACK`，消息留 PEL，遵守 ADR-0008。
- 已经 in-flight 的请求不因后续 pause 或 deadline 变化被伪造成失败。

### 4. max_retries

- `max_retries` 应用于 fetch 层失败、可重试 HTTP 状态和 Redis Stream delivery 上限的终态判断。
- 命令级 `max_retries` 优先于 effective policy 默认值。
- Kafka publish failure 不进入 `max_retries` 语义。
- 非法 `max_retries` 按无效 Fetch Command 处理。

### 5. 严格优雅停机

- SIGTERM / SIGINT 到达时尽早设置共享 shutdown flag。
- shutdown 后 consumer 不再发起新的 `XREADGROUP` 或 `XAUTOCLAIM`。
- delayed buffer 未执行消息不 `XACK`。
- in-flight 是否主动取消由实现计划明确；第一版至少必须保证停止新读 / claim 和 PEL 可恢复。

## 复杂度跟踪

| 例外项 | 必要原因 | 未采纳更简单方案的原因 |
|---|---|---|
| 本地 effective policy provider | 上游控制平面尚未建成，但需要真实验证 M4 运行时语义 | 空实现无法验证热加载、pause、LKG 和指标 |
| LKG 缓存 | 策略源异常不能导致全体 worker 停摆 | 每次读失败直接回退 env 会让运行行为不可审计 |
| pause / deadline 发布 terminal attempt | 下游第五类需要完整 attempt 事实，不应无声丢弃 | 直接 ack 丢弃会破坏可追溯性 |
| 严格停机收口 | production 复刻前需要减少滚动期间重复 claim / 重复处理 | 继续沿用当前过渡语义会扩大生产滚动风险 |

## 实施阶段

1. 规格与契约：收口 effective policy schema、Fetch Command M4 字段、M4 指标和验证口径。
2. 策略模型：实现 policy model、schema validation、scope index、matching 和 bootstrap default。
3. Provider 与 LKG：实现 local file / ConfigMap provider、reload interval、版本检测、LKG 状态和指标。
4. 队列 / spider 集成：在 request 构造前接入 policy decision、pause、deadline 和 max retries。
5. Terminal attempt：实现 pause / deadline terminal attempt 构造、发布和 ack。
6. 严格停机：修正 shutdown flag 入口，停止新 `XREADGROUP` / `XAUTOCLAIM`，补测试和验证脚本。
7. 指标与验证脚本：补 M4 指标、日志、脚本和 quickstart。
8. 文档收口：更新现状层、roadmap、changelog；不关闭 production 后置项。

## 后续计划约束

- M4 完成后，M5 才进入 production 复刻验证和 Kafka outbox / 故障补偿。
- 若实现过程中发现必须让 executor 计算策略优先级、成员关系或业务重排，必须先新增 ADR，再继续。
- 若 terminal skip attempt 需要扩展 `crawl_attempt` schema，新增字段必须可选并保持向后兼容。
