# P0 Implementation Breakdown

## Objective

Validate the riskiest architecture assumption from `scrapy-distributed-crawler-feature.md`: Scrapy workers on one crawler node can reliably use multiple local auxiliary IPs as outbound source addresses and automatically cool down bad host/IP pairs.

## P0 In Scope

- Single-node Scrapy worker.
- Local network-interface IPv4 discovery.
- Source-IP binding through Scrapy request metadata.
- Host-aware IP selection.
- Redis-backed failure counters and blacklist TTL.
- Minimal spider for echo endpoint and controlled URL validation.
- Prometheus metrics and local run evidence.
- 24-hour soak test against approved targets.

## P0 Out of Scope

- Distributed scrapy-redis scheduler.
- Object storage upload.
- Kafka publication.
- PostgreSQL and ClickHouse consumers.
- K8s DaemonSet.
- Terraform and cloud-init automation.
- Full host-profile analytics.

## Implementation Modules

| Module | Responsibility |
|--------|----------------|
| `ip_pool.py` | Discover local IPs, filter excluded IPs, select IP by host and strategy |
| `health.py` | Classify failures, mutate Redis failure counters, maintain blacklist TTL |
| `middlewares.py` | Attach `bindaddress`, record selected IP, update health on response/exception |
| `metrics.py` | Expose request, latency, status, active IP, and blacklist metrics |
| `spiders/egress_validation.py` | Drive controlled PoC URL set and collect observed output |

## Rollout Steps

1. Build local Scrapy project skeleton.
2. Implement pure IP discovery and selection logic with unit tests.
3. Add Redis health primitives and threshold tests.
4. Wire Scrapy middleware and validate `Request.meta["bindaddress"]`.
5. Run echo endpoint validation with low concurrency.
6. Increase to target P0 concurrency gradually.
7. Run 24-hour soak test.
8. Produce P0 evidence report and decide P1 go/no-go.

## P0 Go/No-Go Criteria

Go to P1 only if:

- Multiple expected public EIPs are observed externally.
- Blacklist TTL behavior works without worker restart.
- The worker stays stable for the 24-hour run.
- Resource usage and throughput are close enough to the documented target, or the bottleneck is understood and fixable.

