# Feature Specification: Scrapy Distributed Crawler

**Feature Branch**: `001-scrapy-distributed-crawler`  
**Created**: 2026-04-27  
**Status**: Draft  
**Input**: `scrapy-distributed-crawler-feature.md`

## User Scenarios & Testing

## P0 Scope

P0 targets the original document's "阶段 1：PoC 验证".

P0 proves that a single crawler node can:

- discover local auxiliary IPv4 addresses,
- bind Scrapy outbound requests to those addresses,
- rotate or stick IPs by host,
- cool down failing host/IP pairs through Redis,
- expose enough metrics for a 24-hour comparison against the current Heritrix path.

P0 explicitly does not include production Kafka fan-out, PostgreSQL/ClickHouse persistence, Terraform automation, or multi-node scale-out. Those remain required for later phases and stay documented in this spec.

### User Story 1 - Validate Multi-IP Scrapy Crawl Path (Priority: P0)

As an operator, I need a single crawler node to fetch pages through multiple local egress IPs so that the team can verify Scrapy can replace the current single-IP Heritrix path.

**Why this priority**: This is the highest-risk assumption in the architecture and blocks scale-out.

**Independent Test**: Run one node against an IP echo endpoint and verify requests leave through the expected auxiliary EIPs.

**Acceptance Scenarios**:

1. **Given** a crawler node with auxiliary IPs, **When** the Scrapy worker processes test URLs, **Then** observed public egress IPs include the configured auxiliary EIPs.
2. **Given** repeated failures for a host and IP pair, **When** the failure threshold is reached, **Then** that pair enters cooldown and later traffic selects another eligible IP.
3. **Given** Redis is reachable, **When** multiple requests target the same host, **Then** the configured selection strategy keeps host/IP mapping stable unless the pair is blacklisted.
4. **Given** Redis is temporarily unavailable, **When** the worker processes requests, **Then** the worker fails closed for blacklist mutation but continues with local in-memory state for already discovered IPs. [NEEDS CLARIFICATION: preferred Redis outage behavior]

### User Story 2 - Persist Crawl Output Reliably (Priority: P1)

As a data platform owner, I need fetched HTML stored durably and metadata emitted for downstream systems so that crawl results survive worker, database, and consumer failures.

**Why this priority**: Crawling at scale without durable storage and replayable metadata risks data loss.

**Independent Test**: Fetch sample URLs, store compressed HTML in object storage, publish metadata to Kafka, and verify consumers can replay into PostgreSQL and ClickHouse.

### User Story 3 - Operate Distributed Crawl at Scale (Priority: P2)

As an operator, I need Kubernetes deployment, health checks, metrics, and alerts so that the crawler can scale across many nodes and be safely rolled out.

**Why this priority**: Distributed crawl behavior must be observable before production traffic scale-out.

**Independent Test**: Deploy a small DaemonSet, observe metrics, roll the workload, and verify queue, lag, error, and IP-health panels.

### User Story 4 - Analyze Host Crawl Profile (Priority: P2)

As an analyst or operator, I need host-level crawl profiles so that I can identify slow, blocked, high-error, or high-growth hosts.

**Why this priority**: Host profiling is a stated business capability and informs crawl policy tuning.

**Independent Test**: Query recent crawl events by host and verify success rate, latency percentiles, error distribution, egress IP behavior, and outlink counts.

## Edge Cases

- Redis is unavailable during request scheduling or IP blacklist lookup.
- Kafka is unavailable after object storage upload succeeds.
- Object storage upload fails after a successful HTTP response.
- All local IPs are blacklisted for a target host.
- A host returns CAPTCHA pages with HTTP 200.
- Cold-start URL volume exceeds Redis memory expectations.
- PostgreSQL partition size grows beyond planned limits.
- Source sites rate-limit an entire subnet or ASN.

## Requirements

### Functional Requirements

- **FR-001**: System MUST crawl pages using Scrapy workers instead of Heritrix for the new crawl path.
- **FR-002**: System MUST support binding outbound requests to local auxiliary IPs.
- **FR-003**: System MUST support host-aware IP selection and cooldown after repeated failures.
- **FR-003a**: P0 MUST support `STICKY_BY_HOST` IP selection and MAY support `ROUND_ROBIN` as a diagnostic mode.
- **FR-003b**: P0 MUST store host/IP blacklist state in Redis with TTL-based automatic recovery.
- **FR-003c**: P0 MUST expose metrics for request count, status count, response latency, active IP count, and blacklist count.
- **FR-003d**: P0 MUST provide a repeatable command or script for validating observed egress IP distribution.
- **FR-004**: System MUST store compressed HTML in object storage before publishing downstream metadata.
- **FR-005**: System MUST publish page metadata, crawl events, and parse tasks to Kafka topics.
- **FR-006**: System MUST persist page metadata and crawl logs into partitioned PostgreSQL tables.
- **FR-007**: System MUST write crawl events into ClickHouse for host-profile analytics.
- **FR-008**: System MUST expose operational metrics for throughput, failures, queue depth, Kafka lag, and IP health.
- **FR-009**: System MUST support Kubernetes deployment across crawler nodes.
- **FR-010**: System MUST define URL deduplication semantics. [NEEDS CLARIFICATION: original URL hash vs canonical URL hash rules]
- **FR-011**: System MUST define crawl scope rules. [NEEDS CLARIFICATION: allowed domains, external links, depth limits, recrawl policy]
- **FR-012**: System MUST define downstream parser message contracts. [NEEDS CLARIFICATION: existing consumer schema vs new schema]

### Non-Functional Requirements

- **NFR-001**: P0 SHOULD validate whether one node can sustain 30 pages/sec for 24 hours with CPU below 50% and memory below 4 GB, matching the original PoC acceptance target.
- **NFR-002**: The system SHOULD support a steady-state target of 100 million pages/day, pending infrastructure sizing.
- **NFR-003**: Single-node resource usage SHOULD remain below 70% CPU and 8 GB memory under target throughput.
- **NFR-004**: Crawl output delivery SHOULD use at-least-once semantics with idempotent consumers.
- **NFR-005**: Host and IP failure state SHOULD propagate across workers within 5 seconds.
- **NFR-006**: Production scale-out MUST be gated by rate-limit and compliance decisions. [NEEDS CLARIFICATION: robots.txt, ToS, legal review, max host QPS]

### Key Entities

- **URL Task**: A URL queued for crawl, including priority, scope, dedupe key, retry state, and discovery source.
- **Page Snapshot**: A successful fetched page with URL identity, fetch time, status, content metadata, storage key, and outlink count.
- **Crawl Event**: A single request attempt with timing, egress IP, status or error, retry count, and byte count.
- **Host Profile**: Aggregated host-level behavior including success rate, latency, errors, outlinks, and IP health.
- **IP Health State**: Per-host and global status for a local egress IP, including failures, cooldown, and recovery.

## Success Criteria

- **SC-001**: PoC verifies auxiliary EIPs are used as observed by an external endpoint.
- **SC-002**: P0 single node sustains 30 pages/sec for 24 hours with CPU below 50% and memory below 4 GB, or records the bottleneck preventing that result.
- **SC-003**: HTML is present in object storage before corresponding metadata is made available to downstream consumers.
- **SC-004**: Host profile queries over the agreed time window return within the agreed latency target. [NEEDS CLARIFICATION: target window and latency]
- **SC-005**: Kubernetes rollout, health checks, and metrics are validated on a small node pool before full migration.

## Assumptions

- The original Heritrix path remains available during PoC and staged rollout.
- Auxiliary private IP to EIP mapping is available on crawler nodes.
- Object storage is the system of record for HTML content.
- Kafka is used as a buffer and fan-out layer, not the long-term source of truth.

## Clarifications

- 2026-04-27: Initial draft created from `scrapy-distributed-crawler-feature.md`; open questions remain before detailed planning.
- 2026-04-27: P0 scope is treated as the single-node PoC from the original implementation plan. Production storage, analytics, IaC, and multi-node rollout are deferred to later phases.
