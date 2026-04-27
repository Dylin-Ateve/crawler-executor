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
