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

CRAWL_INTERFACE = os.getenv("CRAWL_INTERFACE", "ens3")
EXCLUDED_LOCAL_IPS = _csv_env("EXCLUDED_LOCAL_IPS")
LOCAL_IP_POOL = _csv_env("LOCAL_IP_POOL")
IP_SELECTION_STRATEGY = os.getenv("IP_SELECTION_STRATEGY", "STICKY_BY_HOST")
IP_FAILURE_THRESHOLD = _int_env("IP_FAILURE_THRESHOLD", 5)
IP_FAILURE_WINDOW_SECONDS = _int_env("IP_FAILURE_WINDOW_SECONDS", 300)
IP_COOLDOWN_SECONDS = _int_env("IP_COOLDOWN_SECONDS", 1800)

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
FORCE_CLOSE_CONNECTIONS = _bool_env("FORCE_CLOSE_CONNECTIONS", True)

DOWNLOADER_MIDDLEWARES = {
    "crawler.middlewares.LocalIpRotationMiddleware": 100,
    "crawler.middlewares.IpHealthCheckMiddleware": 200,
    "scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware": None,
}

EXTENSIONS = {
    "crawler.metrics.PrometheusMetricsExtension": 500,
}

ITEM_PIPELINES = (
    {
        "crawler.pipelines.ContentPersistencePipeline": 300,
    }
    if ENABLE_P1_PERSISTENCE
    else {}
)
