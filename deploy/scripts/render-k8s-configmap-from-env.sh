#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"

"${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import os


CONFIG_KEYS = [
    ("fetch_queue_backend", "FETCH_QUEUE_BACKEND", "redis_streams"),
    ("fetch_queue_stream", "FETCH_QUEUE_STREAM", "crawl:tasks"),
    ("fetch_queue_group", "FETCH_QUEUE_GROUP", "crawler-executor"),
    ("fetch_queue_consumer_template", "FETCH_QUEUE_CONSUMER_TEMPLATE", "${NODE_NAME}-${POD_NAME}"),
    ("fetch_queue_read_count", "FETCH_QUEUE_READ_COUNT", "10"),
    ("fetch_queue_block_ms", "FETCH_QUEUE_BLOCK_MS", "1000"),
    ("fetch_queue_max_deliveries", "FETCH_QUEUE_MAX_DELIVERIES", "3"),
    ("fetch_queue_claim_min_idle_ms", "FETCH_QUEUE_CLAIM_MIN_IDLE_MS", "600000"),
    ("fetch_queue_shutdown_drain_seconds", "FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS", "25"),
    ("fetch_queue_max_messages", "FETCH_QUEUE_MAX_MESSAGES", "0"),
    ("concurrent_requests", "CONCURRENT_REQUESTS", "64"),
    ("concurrent_requests_per_domain", "CONCURRENT_REQUESTS_PER_DOMAIN", "4"),
    ("download_delay", "DOWNLOAD_DELAY", "0.1"),
    ("download_timeout", "DOWNLOAD_TIMEOUT", "30"),
    ("retry_enabled", "RETRY_ENABLED", "true"),
    ("retry_times", "RETRY_TIMES", "2"),
    ("force_close_connections", "FORCE_CLOSE_CONNECTIONS", "true"),
    ("crawl_interface", "CRAWL_INTERFACE", "enp0s5"),
    ("excluded_local_ips", "EXCLUDED_LOCAL_IPS", ""),
    ("local_ip_pool", "LOCAL_IP_POOL", ""),
    ("ip_selection_strategy", "IP_SELECTION_STRATEGY", "STICKY_POOL"),
    ("ip_failure_threshold", "IP_FAILURE_THRESHOLD", "5"),
    ("ip_failure_window_seconds", "IP_FAILURE_WINDOW_SECONDS", "300"),
    ("ip_cooldown_seconds", "IP_COOLDOWN_SECONDS", "1800"),
    ("egress_selection_strategy", "EGRESS_SELECTION_STRATEGY", "STICKY_POOL"),
    ("sticky_pool_size", "STICKY_POOL_SIZE", "4"),
    ("egress_identity_source", "EGRESS_IDENTITY_SOURCE", "auto"),
    ("egress_identity_map_file", "EGRESS_IDENTITY_MAP_FILE", ""),
    ("egress_identity_hash_salt", "EGRESS_IDENTITY_HASH_SALT", ""),
    ("allow_bind_ip_as_egress_identity", "ALLOW_BIND_IP_AS_EGRESS_IDENTITY", "true"),
    ("host_ip_min_delay_ms", "HOST_IP_MIN_DELAY_MS", "2000"),
    ("host_ip_jitter_ms", "HOST_IP_JITTER_MS", "500"),
    ("host_ip_backoff_base_ms", "HOST_IP_BACKOFF_BASE_MS", "5000"),
    ("host_ip_backoff_max_ms", "HOST_IP_BACKOFF_MAX_MS", "300000"),
    ("host_ip_backoff_multiplier", "HOST_IP_BACKOFF_MULTIPLIER", "2.0"),
    ("host_slowdown_seconds", "HOST_SLOWDOWN_SECONDS", "600"),
    ("host_slowdown_factor", "HOST_SLOWDOWN_FACTOR", "3.0"),
    ("local_delayed_buffer_capacity", "LOCAL_DELAYED_BUFFER_CAPACITY", "100"),
    ("max_local_delay_seconds", "MAX_LOCAL_DELAY_SECONDS", "300"),
    ("local_delayed_buffer_poll_ms", "LOCAL_DELAYED_BUFFER_POLL_MS", "500"),
    ("stop_reading_when_delayed_buffer_full", "STOP_READING_WHEN_DELAYED_BUFFER_FULL", "true"),
    ("soft_ban_window_seconds", "SOFT_BAN_WINDOW_SECONDS", "300"),
    ("host_ip_soft_ban_threshold", "HOST_IP_SOFT_BAN_THRESHOLD", "2"),
    ("ip_cross_host_challenge_threshold", "IP_CROSS_HOST_CHALLENGE_THRESHOLD", "3"),
    ("host_cross_ip_challenge_threshold", "HOST_CROSS_IP_CHALLENGE_THRESHOLD", "3"),
    ("http_429_weight", "HTTP_429_WEIGHT", "3"),
    ("captcha_challenge_weight", "CAPTCHA_CHALLENGE_WEIGHT", "5"),
    ("anti_bot_200_weight", "ANTI_BOT_200_WEIGHT", "4"),
    ("http_5xx_weight", "HTTP_5XX_WEIGHT", "1"),
    ("timeout_weight", "TIMEOUT_WEIGHT", "1"),
    ("challenge_body_patterns", "CHALLENGE_BODY_PATTERNS", ""),
    ("anti_bot_200_patterns", "ANTI_BOT_200_PATTERNS", ""),
    ("execution_state_redis_url", "EXECUTION_STATE_REDIS_URL", ""),
    ("execution_state_redis_prefix", "EXECUTION_STATE_REDIS_PREFIX", "crawler:exec:safety"),
    ("execution_state_max_ttl_seconds", "EXECUTION_STATE_MAX_TTL_SECONDS", "86400"),
    ("execution_state_write_enabled", "EXECUTION_STATE_WRITE_ENABLED", "true"),
    ("execution_state_fail_open", "EXECUTION_STATE_FAIL_OPEN", "true"),
    ("asn_observability_enabled", "ASN_OBSERVABILITY_ENABLED", "false"),
    ("asn_database_path", "ASN_DATABASE_PATH", ""),
    ("host_asn_soft_limit_enabled", "HOST_ASN_SOFT_LIMIT_ENABLED", "false"),
    ("redis_key_prefix", "REDIS_KEY_PREFIX", "crawler"),
    ("enable_p1_persistence", "ENABLE_P1_PERSISTENCE", "true"),
    ("object_storage_provider", "OBJECT_STORAGE_PROVIDER", "oci"),
    ("oci_object_storage_bucket", "OCI_OBJECT_STORAGE_BUCKET", ""),
    ("oci_object_storage_namespace", "OCI_OBJECT_STORAGE_NAMESPACE", ""),
    ("oci_object_storage_region", "OCI_OBJECT_STORAGE_REGION", "us-phoenix-1"),
    ("oci_object_storage_endpoint", "OCI_OBJECT_STORAGE_ENDPOINT", "https://objectstorage.us-phoenix-1.oraclecloud.com"),
    ("oci_auth_mode", "OCI_AUTH_MODE", "instance_principal"),
    ("content_compression", "CONTENT_COMPRESSION", "gzip"),
    ("kafka_bootstrap_servers", "KAFKA_BOOTSTRAP_SERVERS", ""),
    ("kafka_security_protocol", "KAFKA_SECURITY_PROTOCOL", "SASL_SSL"),
    ("kafka_sasl_mechanism", "KAFKA_SASL_MECHANISM", "SCRAM-SHA-512"),
    ("kafka_ssl_ca_location", "KAFKA_SSL_CA_LOCATION", "/etc/ssl/certs/ca-certificates.crt"),
    ("kafka_topic_crawl_attempt", "KAFKA_TOPIC_CRAWL_ATTEMPT", "crawler.crawl-attempt.v1"),
    ("kafka_batch_size", "KAFKA_BATCH_SIZE", "100"),
    ("kafka_producer_retries", "KAFKA_PRODUCER_RETRIES", "3"),
    ("kafka_request_timeout_ms", "KAFKA_REQUEST_TIMEOUT_MS", "30000"),
    ("kafka_delivery_timeout_ms", "KAFKA_DELIVERY_TIMEOUT_MS", "120000"),
    ("kafka_flush_timeout_ms", "KAFKA_FLUSH_TIMEOUT_MS", "130000"),
    ("prometheus_port", "PROMETHEUS_PORT", "9410"),
    ("health_port", "HEALTH_PORT", "9411"),
    ("readiness_max_heartbeat_age_seconds", "READINESS_MAX_HEARTBEAT_AGE_SECONDS", "30"),
    ("log_level", "LOG_LEVEL", "INFO"),
    ("crawler_paused", "CRAWLER_PAUSED", "false"),
    ("crawler_pause_poll_seconds", "CRAWLER_PAUSE_POLL_SECONDS", "5"),
    ("crawler_debug_mode", "CRAWLER_DEBUG_MODE", "false"),
    ("debug_fetch_queue_stream_template", "DEBUG_FETCH_QUEUE_STREAM_TEMPLATE", "crawl:tasks:debug:{node_name}"),
    ("debug_fetch_queue_group_template", "DEBUG_FETCH_QUEUE_GROUP_TEMPLATE", "crawler-executor-debug:{node_name}"),
    ("debug_fetch_queue_consumer_template", "DEBUG_FETCH_QUEUE_CONSUMER_TEMPLATE", "${NODE_NAME}-${POD_NAME}-debug"),
    ("debug_attempt_tier", "DEBUG_ATTEMPT_TIER", "debug"),
]


def quote(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


print("apiVersion: v1")
print("kind: ConfigMap")
print("metadata:")
print("  name: crawler-executor-config")
print("  labels:")
print("    app.kubernetes.io/name: crawler-executor")
print("    app.kubernetes.io/component: fetch-worker")
print("data:")
for key, env_name, default in CONFIG_KEYS:
    print(f"  {key}: {quote(os.getenv(env_name, default))}")
PY
