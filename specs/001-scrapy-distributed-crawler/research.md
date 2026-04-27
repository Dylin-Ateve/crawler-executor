# Research: Scrapy Distributed Crawler

## Decisions To Research

- Scrapy `bindaddress` behavior under Kubernetes `hostNetwork`.
- scrapy-redis queue customization for host bucketing and prioritization.
- Redis data structures for blacklist, dedupe, and overflow strategy.
- Kafka producer durability settings and local disk buffering.
- PostgreSQL partitioning strategy and retention policy.
- ClickHouse schema and materialized views for host profiles.
- Cloud provider mechanics for auxiliary IPs and EIP binding.

## Decision Log

| Topic | Decision | Rationale | Alternatives |
|-------|----------|-----------|--------------|
| P0 boundary | Single-node Scrapy egress-IP PoC only | This isolates the riskiest assumption before storage and orchestration work | Building full Kafka/PG/CH path first would hide network uncertainty behind more moving parts |
| IP selection | Start with `STICKY_BY_HOST`; keep `ROUND_ROBIN` as diagnostic mode | Sticky host mapping reduces per-host egress churn while still distributing hosts across IPs | Pure random selection may look noisier to target hosts |
| Blacklist state | Redis keys with TTL for host/IP cooldown | Matches the target architecture and makes recovery automatic | Local in-memory state cannot validate shared behavior |
| Metrics | Prometheus endpoint in the crawler process | Low-friction operational visibility and reusable for later K8s phase | Parsing logs after the run is insufficient for live validation |
