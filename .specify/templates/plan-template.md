# 实施计划：[功能]

**分支**：`[###-feature-name]`
**日期**：[DATE]
**规格文档**：[link]

## 摘要

[核心需求和已选技术方案。]

## 技术上下文

**语言/版本**：[例如 Python 3.12 或 NEEDS CLARIFICATION]
**主要依赖**：[例如 Scrapy、scrapy-redis、Kafka client]
**存储**：[例如对象存储、PostgreSQL、ClickHouse]
**测试**：[例如 pytest、集成测试、压测]
**目标平台**：[例如 Kubernetes Linux 节点]
**项目类型**：[服务/基础设施/数据管道]
**性能目标**：[可度量目标]
**约束**：[网络、成本、合规、运维约束]
**规模/范围**：[预期抓取规模]

## 章程检查

[记录该计划是否满足 `.specify/memory/constitution.md`。]

## 项目结构

### 文档

```text
specs/[###-feature]/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
└── tasks.md
```

### 源码

```text
src/
tests/
deploy/
infra/
```

**结构决策**：[记录已选择的结构。]

## 复杂度跟踪

| 例外项 | 必要原因 | 未采纳更简单方案的原因 |
|--------|----------|------------------------------|
