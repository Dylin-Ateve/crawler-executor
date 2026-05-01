from crawler.health import RedisHealthStore
from crawler.ip_pool import LocalIpPool
from crawler.middlewares import IpHealthCheckMiddleware, LocalIpRotationMiddleware
from crawler.response_signals import BodyPattern


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
        self.headers = {}


class DummyResponse:
    status = 200
    body = b"<html>ok</html>"
    headers = {}


class ChallengeResponse:
    status = 200
    body = b"<html>please verify you are human</html>"
    headers = {b"Content-Type": b"text/html"}


class DummySpider:
    class Logger:
        def warning(self, *_args, **_kwargs):
            return None

    logger = Logger()


class RecordingFeedbackController:
    def __init__(self):
        self.signals = []

    def record_signal(self, signal, *, asn=None, cidr=None):
        self.signals.append((signal, asn, cidr))


def test_rotation_middleware_sets_bindaddress_metadata():
    health = RedisHealthStore(FakeRedis())
    middleware = LocalIpRotationMiddleware(LocalIpPool(["10.0.0.2"]), health)
    request = DummyRequest("https://example.com/page")

    assert middleware.process_request(request, DummySpider()) is None
    assert request.meta["bindaddress"] == ("10.0.0.2", 0)
    assert request.meta["egress_local_ip"] == "10.0.0.2"
    assert request.meta["egress_host"] == "example.com"
    assert request.headers["Connection"] == "close"


def test_rotation_middleware_honors_preselected_egress_ip():
    health = RedisHealthStore(FakeRedis())
    middleware = LocalIpRotationMiddleware(LocalIpPool(["10.0.0.2", "10.0.0.3"]), health)
    request = DummyRequest("https://example.com/page")
    request.meta["egress_bind_ip"] = "10.0.0.3"
    request.meta["egress_local_ip"] = "10.0.0.3"

    assert middleware.process_request(request, DummySpider()) is None
    assert request.meta["bindaddress"] == ("10.0.0.3", 0)
    assert request.meta["egress_local_ip"] == "10.0.0.3"


def test_health_middleware_records_success_without_scrapy_runtime():
    redis = FakeRedis()
    health = RedisHealthStore(redis)
    middleware = IpHealthCheckMiddleware(health)
    request = DummyRequest("https://example.com/page")
    request.meta["egress_local_ip"] = "10.0.0.2"
    request.meta["egress_host"] = "example.com"

    response = middleware.process_response(request, DummyResponse(), DummySpider())

    assert response.status == 200


def test_health_middleware_records_feedback_signal_from_response():
    redis = FakeRedis()
    feedback = RecordingFeedbackController()
    middleware = IpHealthCheckMiddleware(
        RedisHealthStore(redis),
        feedback_controller=feedback,
        challenge_patterns=(BodyPattern("human-check", "verify you are human"),),
    )
    request = DummyRequest("https://example.com/page")
    request.meta["egress_local_ip"] = "10.0.0.2"
    request.meta["egress_identity_hash"] = "identity-hash"
    request.meta["egress_asn"] = "AS31898"

    response = middleware.process_response(request, ChallengeResponse(), DummySpider())

    assert response.status == 200
    assert len(feedback.signals) == 1
    signal, asn, cidr = feedback.signals[0]
    assert signal.signal_type == "captcha_challenge"
    assert signal.identity_hash == "identity-hash"
    assert asn == "AS31898"
    assert cidr is None


def test_health_middleware_records_feedback_signal_from_exception():
    redis = FakeRedis()
    feedback = RecordingFeedbackController()
    middleware = IpHealthCheckMiddleware(RedisHealthStore(redis), feedback_controller=feedback)
    request = DummyRequest("https://example.com/page")
    request.meta["egress_local_ip"] = "10.0.0.2"

    result = middleware.process_exception(request, TimeoutError("timed out"), DummySpider())

    assert result is None
    assert len(feedback.signals) == 1
    assert feedback.signals[0][0].signal_type == "timeout"
