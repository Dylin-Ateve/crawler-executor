# M3 K8s base manifests

This directory contains first-pass Kubernetes templates for `crawler-executor`.

Do not commit real Secret values. `secrets.example.yaml` documents required Secret names and keys only; create real Secrets in the target cluster through the approved secret-management path.

Environment profiles live under `deploy/environments/`. Use `production.env` for the current OCI / OKE production candidate and `staging.env` for the earlier `ens3` staging defaults.

The DaemonSet uses conservative initial resources:

- requests: `cpu=1000m`, `memory=2Gi`
- limits: `cpu=4000m`, `memory=6Gi`

Tune these with `CONCURRENT_REQUESTS = min(ip_count * per_ip_concurrency, global_cap)`. Increasing the 50-60 IP pool utilization requires revisiting CPU, memory, Kafka flush latency, object storage upload latency, and gzip compression overhead.

Prometheus discovery is provided through pod annotations on `:9410/metrics`. Clusters that require `ServiceMonitor` or `PodMonitor` can translate those annotations into their monitoring stack without changing the application container contract.

The pause flag is exposed both as `CRAWLER_PAUSED` at startup and as a ConfigMap volume file mounted at `/etc/crawler/runtime/crawler_paused`. Patch `crawler-executor-config.data.crawler_paused` to pause or resume existing pods without deleting the DaemonSet; allow for normal kubelet ConfigMap volume propagation delay.

Apply order for a test namespace:

```bash
kubectl apply -f configmap.yaml
kubectl apply -f <real-secrets.yaml>
kubectl apply -f daemonset.yaml
```
