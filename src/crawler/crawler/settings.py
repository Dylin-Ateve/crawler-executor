import os


def _csv_env(name: str, default: str = ""):
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    return int(raw)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


BOT_NAME = "crawler"
SPIDER_MODULES = ["crawler.spiders"]
NEWSPIDER_MODULE = "crawler.spiders"

ROBOTSTXT_OBEY = False
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

CRAWL_INTERFACE = os.getenv("CRAWL_INTERFACE", "enp0s5")
EXCLUDED_LOCAL_IPS = _csv_env("EXCLUDED_LOCAL_IPS")
LOCAL_IP_POOL = _csv_env("LOCAL_IP_POOL")
IP_SELECTION_STRATEGY = os.getenv("IP_SELECTION_STRATEGY", "STICKY_BY_HOST")
IP_FAILURE_THRESHOLD = _int_env("IP_FAILURE_THRESHOLD", 5)
IP_FAILURE_WINDOW_SECONDS = _int_env("IP_FAILURE_WINDOW_SECONDS", 300)
IP_COOLDOWN_SECONDS = _int_env("IP_COOLDOWN_SECONDS", 1800)

EGRESS_SELECTION_STRATEGY = os.getenv("EGRESS_SELECTION_STRATEGY", IP_SELECTION_STRATEGY)
STICKY_POOL_SIZE = _int_env("STICKY_POOL_SIZE", 4)
EGRESS_IDENTITY_SOURCE = os.getenv("EGRESS_IDENTITY_SOURCE", "auto")
EGRESS_IDENTITY_MAP_FILE = os.getenv("EGRESS_IDENTITY_MAP_FILE", "")
EGRESS_IDENTITY_HASH_SALT = os.getenv("EGRESS_IDENTITY_HASH_SALT", "")
ALLOW_BIND_IP_AS_EGRESS_IDENTITY = _bool_env("ALLOW_BIND_IP_AS_EGRESS_IDENTITY", True)
HOST_IP_MIN_DELAY_MS = _int_env("HOST_IP_MIN_DELAY_MS", 2000)
HOST_IP_JITTER_MS = _int_env("HOST_IP_JITTER_MS", 500)
HOST_IP_BACKOFF_BASE_MS = _int_env("HOST_IP_BACKOFF_BASE_MS", 5000)
HOST_IP_BACKOFF_MAX_MS = _int_env("HOST_IP_BACKOFF_MAX_MS", 300000)
HOST_IP_BACKOFF_MULTIPLIER = float(os.getenv("HOST_IP_BACKOFF_MULTIPLIER", "2.0"))
HOST_SLOWDOWN_FACTOR = float(os.getenv("HOST_SLOWDOWN_FACTOR", "1.0"))
LOCAL_DELAYED_BUFFER_CAPACITY = _int_env("LOCAL_DELAYED_BUFFER_CAPACITY", 100)
MAX_LOCAL_DELAY_SECONDS = _int_env("MAX_LOCAL_DELAY_SECONDS", 300)
LOCAL_DELAYED_BUFFER_POLL_MS = _int_env("LOCAL_DELAYED_BUFFER_POLL_MS", 500)
STOP_READING_WHEN_DELAYED_BUFFER_FULL = _bool_env("STOP_READING_WHEN_DELAYED_BUFFER_FULL", True)

REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "crawler")

ENABLE_P1_PERSISTENCE = _bool_env("ENABLE_P1_PERSISTENCE", False)
OBJECT_STORAGE_PROVIDER = os.getenv("OBJECT_STORAGE_PROVIDER", "oci")
OCI_OBJECT_STORAGE_BUCKET = os.getenv("OCI_OBJECT_STORAGE_BUCKET", "clawer_content_staging")
OCI_OBJECT_STORAGE_NAMESPACE = os.getenv("OCI_OBJECT_STORAGE_NAMESPACE", "axfwvgxlpupm")
OCI_OBJECT_STORAGE_REGION = os.getenv("OCI_OBJECT_STORAGE_REGION", "us-phoenix-1")
OCI_OBJECT_STORAGE_ENDPOINT = os.getenv(
    "OCI_OBJECT_STORAGE_ENDPOINT",
    "https://objectstorage.us-phoenix-1.oraclecloud.com",
)
OCI_AUTH_MODE = os.getenv("OCI_AUTH_MODE", "api_key")
OCI_CONFIG_FILE = os.getenv("OCI_CONFIG_FILE", os.path.expanduser("~/.oci/config"))
OCI_PROFILE = os.getenv("OCI_PROFILE", "DEFAULT")
CONTENT_COMPRESSION = os.getenv("CONTENT_COMPRESSION", "gzip")

KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "bootstrap-clstr-hcpqnx0ycdc2ds5o.kafka.us-phoenix-1.oci.oraclecloud.com:9092",
)
KAFKA_SECURITY_PROTOCOL = os.getenv("KAFKA_SECURITY_PROTOCOL", "SASL_SSL")
KAFKA_SASL_MECHANISM = os.getenv("KAFKA_SASL_MECHANISM", "SCRAM-SHA-512")
KAFKA_USERNAME = os.getenv("KAFKA_USERNAME", "")
KAFKA_PASSWORD = os.getenv("KAFKA_PASSWORD", "")
KAFKA_SSL_CA_LOCATION = os.getenv("KAFKA_SSL_CA_LOCATION", "/etc/pki/tls/certs/ca-bundle.crt")
KAFKA_BATCH_SIZE = _int_env("KAFKA_BATCH_SIZE", 100)
KAFKA_TOPIC_PAGE_METADATA = os.getenv("KAFKA_TOPIC_PAGE_METADATA", "crawler.page-metadata.v1")
KAFKA_TOPIC_CRAWL_ATTEMPT = os.getenv("KAFKA_TOPIC_CRAWL_ATTEMPT", "crawler.crawl-attempt.v1")
KAFKA_PRODUCER_RETRIES = _int_env("KAFKA_PRODUCER_RETRIES", 3)
KAFKA_REQUEST_TIMEOUT_MS = _int_env("KAFKA_REQUEST_TIMEOUT_MS", 30000)
KAFKA_DELIVERY_TIMEOUT_MS = _int_env("KAFKA_DELIVERY_TIMEOUT_MS", 120000)
KAFKA_FLUSH_TIMEOUT_MS = _int_env("KAFKA_FLUSH_TIMEOUT_MS", 130000)

CONCURRENT_REQUESTS = _int_env("CONCURRENT_REQUESTS", 64)
CONCURRENT_REQUESTS_PER_DOMAIN = _int_env("CONCURRENT_REQUESTS_PER_DOMAIN", 4)
DOWNLOAD_DELAY = float(os.getenv("DOWNLOAD_DELAY", "0.1"))
RANDOMIZE_DOWNLOAD_DELAY = True
DOWNLOAD_TIMEOUT = _int_env("DOWNLOAD_TIMEOUT", 30)
RETRY_ENABLED = _bool_env("RETRY_ENABLED", True)
RETRY_TIMES = _int_env("RETRY_TIMES", 2)
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408]

PROMETHEUS_PORT = _int_env("PROMETHEUS_PORT", 9410)
HEALTH_PORT = _int_env("HEALTH_PORT", 9411)
READINESS_MAX_HEARTBEAT_AGE_SECONDS = _int_env("READINESS_MAX_HEARTBEAT_AGE_SECONDS", 30)
FORCE_CLOSE_CONNECTIONS = _bool_env("FORCE_CLOSE_CONNECTIONS", True)

FETCH_QUEUE_BACKEND = os.getenv("FETCH_QUEUE_BACKEND", "redis_streams")
FETCH_QUEUE_REDIS_URL = os.getenv("FETCH_QUEUE_REDIS_URL", "")
FETCH_QUEUE_STREAM = os.getenv("FETCH_QUEUE_STREAM", "crawl:tasks")
FETCH_QUEUE_GROUP = os.getenv("FETCH_QUEUE_GROUP", "crawler-executor")
FETCH_QUEUE_CONSUMER = os.getenv("FETCH_QUEUE_CONSUMER", "")
FETCH_QUEUE_CONSUMER_TEMPLATE = os.getenv("FETCH_QUEUE_CONSUMER_TEMPLATE", "")
NODE_NAME = os.getenv("NODE_NAME", "")
POD_NAME = os.getenv("POD_NAME", "")
CRAWLER_DEBUG_MODE = _bool_env("CRAWLER_DEBUG_MODE", False)
DEBUG_FETCH_QUEUE_STREAM_TEMPLATE = os.getenv("DEBUG_FETCH_QUEUE_STREAM_TEMPLATE", "crawl:tasks:debug:{node_name}")
DEBUG_FETCH_QUEUE_GROUP_TEMPLATE = os.getenv("DEBUG_FETCH_QUEUE_GROUP_TEMPLATE", "crawler-executor-debug:{node_name}")
DEBUG_FETCH_QUEUE_CONSUMER_TEMPLATE = os.getenv("DEBUG_FETCH_QUEUE_CONSUMER_TEMPLATE", "${NODE_NAME}-${POD_NAME}-debug")
CRAWLER_PAUSED = _bool_env("CRAWLER_PAUSED", False)
CRAWLER_PAUSE_FILE = os.getenv("CRAWLER_PAUSE_FILE", "")
CRAWLER_PAUSE_POLL_SECONDS = _int_env("CRAWLER_PAUSE_POLL_SECONDS", 5)
FETCH_QUEUE_READ_COUNT = _int_env("FETCH_QUEUE_READ_COUNT", 10)
FETCH_QUEUE_BLOCK_MS = _int_env("FETCH_QUEUE_BLOCK_MS", 5000)
FETCH_QUEUE_MAX_DELIVERIES = _int_env("FETCH_QUEUE_MAX_DELIVERIES", 3)
FETCH_QUEUE_CLAIM_MIN_IDLE_MS = _int_env("FETCH_QUEUE_CLAIM_MIN_IDLE_MS", 60000)
FETCH_QUEUE_MAX_MESSAGES = _int_env("FETCH_QUEUE_MAX_MESSAGES", 0)
# ADR-0009：优雅停机 drain 缺省 25 秒，留出 K8s 默认 30 秒 grace period 安全边距。
FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS = _int_env("FETCH_QUEUE_SHUTDOWN_DRAIN_SECONDS", 25)

DOWNLOADER_MIDDLEWARES = {
    "crawler.middlewares.LocalIpRotationMiddleware": 100,
    "crawler.middlewares.IpHealthCheckMiddleware": 200,
    "scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware": None,
}

EXTENSIONS = {
    "crawler.metrics.PrometheusMetricsExtension": 500,
    "crawler.health.HealthCheckExtension": 510,
}

ITEM_PIPELINES = (
    {
        "crawler.pipelines.ContentPersistencePipeline": 300,
    }
    if ENABLE_P1_PERSISTENCE
    else {}
)
