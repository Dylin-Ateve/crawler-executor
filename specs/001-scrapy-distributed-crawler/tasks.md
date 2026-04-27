# Tasks: P0 Scrapy Distributed Crawler PoC

**Input**: `spec.md`, `plan.md`, original `scrapy-distributed-crawler-feature.md`  
**Scope**: P0 single-node PoC only

## Phase 1: P0 Setup

- [ ] T001 Create Python/Scrapy project skeleton under `src/crawler/`.
- [ ] T002 Add dependency definition for Scrapy, redis client, Prometheus client, IP discovery library, and pytest.
- [ ] T003 Create configuration module for `CRAWL_INTERFACE`, `EXCLUDED_LOCAL_IPS`, IP strategy, Redis URL, cooldown thresholds, and Scrapy concurrency.
- [ ] T004 Create local run documentation in `specs/001-scrapy-distributed-crawler/quickstart.md`.

## Phase 2: Foundational IP + Redis Behavior

- [ ] T005 [P] Implement local IPv4 discovery in `src/crawler/crawler/ip_pool.py`.
- [ ] T006 [P] Add unit tests for IP discovery filtering in `tests/unit/test_ip_pool.py`.
- [ ] T007 Implement host/IP selection logic in `src/crawler/crawler/ip_pool.py`.
- [ ] T008 [P] Add unit tests for `STICKY_BY_HOST` and `ROUND_ROBIN` selection in `tests/unit/test_ip_pool.py`.
- [ ] T009 Implement Redis blacklist and failure-counter helpers in `src/crawler/crawler/health.py`.
- [ ] T010 [P] Add unit tests for blacklist key format and threshold behavior in `tests/unit/test_health.py`.

## Phase 3: Scrapy Middleware Slice

- [ ] T011 Implement `LocalIpRotationMiddleware` in `src/crawler/crawler/middlewares.py`.
- [ ] T012 Implement `IpHealthCheckMiddleware` in `src/crawler/crawler/middlewares.py`.
- [ ] T013 Configure Scrapy downloader middleware order in `src/crawler/crawler/settings.py`.
- [ ] T014 Add a minimal validation spider in `src/crawler/crawler/spiders/egress_validation.py`.
- [ ] T015 Add integration smoke test for middleware metadata binding in `tests/integration/test_egress_middleware.py`.

## Phase 4: Observability

- [ ] T016 Implement Prometheus metrics in `src/crawler/crawler/metrics.py`.
- [ ] T017 Expose request totals, status totals, response duration, active IP count, and blacklist count.
- [ ] T018 Add run-log output for observed echo endpoint IPs.

## Phase 5: P0 Validation Scripts

- [ ] T019 Create a script to run echo-endpoint validation in `deploy/scripts/run-egress-validation.sh`.
- [ ] T020 Create a script to inspect Redis blacklist keys in `deploy/scripts/inspect-ip-health.sh`.
- [ ] T021 Create a 24-hour PoC run command in `deploy/scripts/run-p0-soak.sh`.
- [ ] T022 Document the expected PoC evidence and result table in `specs/001-scrapy-distributed-crawler/quickstart.md`.

## Phase 6: P0 Exit Review

- [ ] T023 Collect observed EIP distribution from the validation run.
- [ ] T024 Collect 24-hour throughput, CPU, memory, error-rate, and blacklist-rate results.
- [ ] T025 Compare P0 results with the current Heritrix baseline.
- [ ] T026 Decide whether to proceed to P1 storage and Kafka implementation.

## Dependencies & Execution Order

- Phase 1 blocks all implementation work.
- Phase 2 blocks Scrapy middleware behavior.
- Phase 3 blocks live egress validation.
- Phase 4 and Phase 5 can proceed after Phase 3.
- Phase 6 is the P0 gate before P1 planning.
