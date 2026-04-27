from crawler.health import RedisHealthStore
from crawler.ip_pool import LocalIpPool
from crawler.middlewares import IpHealthCheckMiddleware, LocalIpRotationMiddleware


class FakeRedis:
    def exists(self, _key):
        return False

    def delete(self, _key):
        return None

    def zadd(self, _key, _mapping):
        return None

    def zremrangebyscore(self, _key, _minimum, _maximum):
        return None

    def expire(self, _key, _ttl):
        return None

    def zcard(self, _key):
        return 0

    def setex(self, _key, _ttl, _value):
        return None

    def scan_iter(self, match=None):
        return iter(())


class DummyRequest:
    def __init__(self, url):
        self.url = url
        self.meta = {}


class DummyResponse:
    status = 200
    body = b"<html>ok</html>"
    headers = {}


class DummySpider:
    class Logger:
        def warning(self, *_args, **_kwargs):
            return None

    logger = Logger()


def test_rotation_middleware_sets_bindaddress_metadata():
    health = RedisHealthStore(FakeRedis())
    middleware = LocalIpRotationMiddleware(LocalIpPool(["10.0.0.2"]), health)
    request = DummyRequest("https://example.com/page")

    assert middleware.process_request(request, DummySpider()) is None
    assert request.meta["bindaddress"] == ("10.0.0.2", 0)
    assert request.meta["egress_local_ip"] == "10.0.0.2"
    assert request.meta["egress_host"] == "example.com"


def test_health_middleware_records_success_without_scrapy_runtime():
    redis = FakeRedis()
    health = RedisHealthStore(redis)
    middleware = IpHealthCheckMiddleware(health)
    request = DummyRequest("https://example.com/page")
    request.meta["egress_local_ip"] = "10.0.0.2"
    request.meta["egress_host"] = "example.com"

    response = middleware.process_response(request, DummyResponse(), DummySpider())

    assert response.status == 200

