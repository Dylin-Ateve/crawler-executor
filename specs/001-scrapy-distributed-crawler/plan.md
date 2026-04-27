# Implementation Plan: Scrapy Distributed Crawler

**Branch**: `001-scrapy-distributed-crawler`  
**Date**: 2026-04-27  
**Spec**: `specs/001-scrapy-distributed-crawler/spec.md`

## Summary

P0 implements a single-node Scrapy PoC that validates local auxiliary-IP egress. The implementation focuses on a narrow but production-shaped slice: IP discovery, Scrapy downloader middleware, Redis-backed blacklist/cooldown, bounded crawl settings, Prometheus metrics, and repeatable validation scripts.

The P0 output is not the final distributed crawler. It is the proof point required before committing to Kafka/PG/ClickHouse/K8s/Terraform scale-out work.

## Technical Context

**Language/Version**: Python 3.12 for P0  
**Primary Dependencies**: Scrapy, Twisted, redis-py, prometheus-client, netifaces or psutil  
**Storage**: Redis for P0 blacklist/counters; no durable page storage in P0 unless explicitly enabled  
**Testing**: pytest for pure logic, Scrapy integration smoke tests, 24-hour PoC run  
**Target Platform**: One Linux crawler node with auxiliary private IPs mapped to EIPs  
**Project Type**: Distributed crawler and data pipeline  
**Performance Goals**: P0 target is 30 pages/sec for 24 hours, CPU < 50%, memory < 4 GB  
**Constraints**: Must bind outbound requests to local source addresses; must avoid unsafe unbounded host pressure  
**Scale/Scope**: Single node, controlled URL set, external IP echo validation, limited comparison workload

## Constitution Check

- Specification First: Pass for P0; broader production clarifications remain open.
- Operational Safety: Pass for P0 only if default concurrency and target hosts are constrained.
- Data Durability: Not applicable to P0 page persistence; required before P1 storage path.
- Incremental Delivery: Pass, phased delivery is expected.
- Measurable Acceptance: Pass for P0 with explicit 24-hour throughput and resource targets.

## P0 Architecture

```text
seed URLs / echo URLs
        |
        v
Scrapy Spider
        |
        v
Downloader Middleware
  - Local IP discovery
  - host -> local IP selection
  - Request.meta["bindaddress"]
        |
        v
Internet target / IP echo endpoint
        |
        v
Health Middleware
  - status/error classification
  - Redis failure counters
  - Redis blacklist TTL
        |
        v
Prometheus metrics + local run logs
```

## P0 Implementation Strategy

1. Create a standard Scrapy project under `src/crawler/`.
2. Implement IP discovery as a standalone utility with unit tests.
3. Implement `LocalIpRotationMiddleware` with `STICKY_BY_HOST` first.
4. Implement `IpHealthCheckMiddleware` with Redis TTL blacklist.
5. Add a minimal spider that accepts a seed URL file and records observed egress IP output.
6. Add metrics endpoint for request totals, status totals, latency, active IP count, and blacklist count.
7. Package a single-node run command for bare-metal or host-network container execution.
8. Run controlled validation against IP echo endpoints and a small allowed target set.
9. Run the 24-hour comparison against the current Heritrix baseline.

## P0 Deferred Items

- scrapy-redis distributed scheduler and URL dedupe.
- Kafka message publication.
- Object storage pipeline.
- PostgreSQL and ClickHouse consumers.
- K8s DaemonSet rollout.
- Terraform/cloud-init EIP automation.
- Full host-profile analytical queries.

## P0 Acceptance Gates

- Gate 1: Worker starts and discovers at least two eligible local IPs.
- Gate 2: External echo endpoint observes requests from multiple expected EIPs.
- Gate 3: Host/IP blacklist enters and exits cooldown using Redis TTL.
- Gate 4: Metrics endpoint reports crawl counters and IP health.
- Gate 5: 24-hour run reaches the target or produces a bottleneck report.

## Project Structure

### Documentation

```text
specs/001-scrapy-distributed-crawler/
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
├── crawler/
│   ├── crawler/
│   │   ├── middlewares.py
│   │   ├── ip_pool.py
│   │   ├── health.py
│   │   ├── metrics.py
│   │   ├── settings.py
│   │   └── spiders/
│   └── scrapy.cfg
tests/
├── unit/
└── integration/
deploy/
├── docker/
└── scripts/
infra/
```

**Structure Decision**: P0 uses a single Python/Scrapy project. Later phases may add `consumers/`, `schemas/`, `deploy/k8s/`, and `infra/terraform/`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| Redis in P0 | Required to validate shared blacklist semantics from the target architecture | Pure in-memory blacklist would not prove the cross-worker cooldown model |
| Prometheus metrics in P0 | Required to compare with Heritrix and run the 24-hour gate | Log-only observation is too weak for sustained-run validation |
