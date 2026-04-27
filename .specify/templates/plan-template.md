# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]`  
**Date**: [DATE]  
**Spec**: [link]

## Summary

[Primary requirement and selected technical approach.]

## Technical Context

**Language/Version**: [e.g. Python 3.12 or NEEDS CLARIFICATION]  
**Primary Dependencies**: [e.g. Scrapy, scrapy-redis, Kafka client]  
**Storage**: [e.g. object storage, PostgreSQL, ClickHouse]  
**Testing**: [e.g. pytest, integration tests, load tests]  
**Target Platform**: [e.g. Kubernetes Linux nodes]  
**Project Type**: [service/infrastructure/data pipeline]  
**Performance Goals**: [Measurable goals]  
**Constraints**: [Network, cost, compliance, operational constraints]  
**Scale/Scope**: [Expected crawl scale]

## Constitution Check

[Document whether the plan satisfies `.specify/memory/constitution.md`.]

## Project Structure

### Documentation

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

### Source Code

```text
src/
tests/
deploy/
infra/
```

**Structure Decision**: [Document selected structure.]

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|

