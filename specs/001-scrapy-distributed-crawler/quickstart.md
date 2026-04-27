# Quickstart: P0 Scrapy Distributed Crawler PoC

This file defines the intended P0 validation flow. Commands will be finalized once the source tree exists.

## Preconditions

- One Linux crawler node has auxiliary private IPv4 addresses configured on the target network interface.
- Each auxiliary private IP has a corresponding public EIP.
- Redis is reachable from the crawler node.
- The test URL set is approved for PoC traffic.
- At least one IP echo endpoint is available for egress validation.

## Configuration Inputs

- `CRAWL_INTERFACE`: network interface to scan, default `ens3`.
- `EXCLUDED_LOCAL_IPS`: primary management IPs excluded from crawl egress.
- `IP_SELECTION_STRATEGY`: `STICKY_BY_HOST` for normal PoC, `ROUND_ROBIN` for diagnostics.
- `IP_FAILURE_THRESHOLD`: default `5`.
- `IP_COOLDOWN_SECONDS`: default `1800`.
- `CONCURRENT_REQUESTS`: default P0 value to be confirmed.
- `CONCURRENT_REQUESTS_PER_DOMAIN`: default P0 value to be confirmed.
- `REDIS_URL`: Redis connection string.

## PoC Validation Outline

1. Prepare one crawler node with auxiliary IPs and EIPs.
2. Run the Scrapy worker with local IP rotation enabled.
3. Fetch a controlled URL set including an IP echo endpoint.
4. Verify observed public IP distribution.
5. Force failure thresholds and verify blacklist cooldown behavior.
6. Verify metrics are exposed and scrapeable.
7. Run a 24-hour steady test and compare throughput/resource usage with the current Heritrix baseline.

## Expected P0 Evidence

- List of discovered local IPs with excluded management IPs removed.
- Echo endpoint output showing observed public EIPs.
- Redis keys showing failure counters and blacklist TTL.
- Metrics snapshot for request count, status count, latency, active IP count, and blacklist count.
- 24-hour run summary: pages/sec, CPU, memory, error rate, blacklist rate, and any bottlenecks.

## Pending Inputs

- Cloud provider and node network setup.
- Test target URLs.
- Redis endpoint.
- Acceptance thresholds.
