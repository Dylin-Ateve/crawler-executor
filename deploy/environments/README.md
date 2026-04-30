# Environment profiles

This directory contains sourceable environment profiles for M3 validation and deployment planning.

- `production.env` reflects the current OCI / OKE production candidate:
  - node pool `scrapy-node-pool`
  - subnet `subnetCollection`
  - node label `scrapy-egress=true`
  - no taint for the first validation pass
  - `CRAWL_INTERFACE=enp0s5`
  - expected per-node IPv4 range `60-70`
- `staging.env` preserves the earlier staging defaults:
  - `CRAWL_INTERFACE=ens3`
  - `ateve.io/crawler-egress=true`
  - expected per-node IPv4 range `50-60`

The files intentionally contain placeholder Secret values only. Create real Kubernetes Secrets for Redis and Kafka credentials instead of committing credentials to this repository.

Example:

```bash
set -a
source deploy/environments/production.env
set +a

deploy/scripts/run-m3-k8s-daemonset-audit.sh
```
