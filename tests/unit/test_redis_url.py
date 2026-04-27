from crawler.middlewares import build_redis_client


def test_redis_url_accepts_url_encoded_special_character_password():
    client = build_redis_client(
        "redis://crawler:p%40ss%3Aword%2Fwith%23chars%25and%26bang%21@redis-host:6379/0"
    )

    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["username"] == "crawler"
    assert kwargs["password"] == "p@ss:word/with#chars%and&bang!"
    assert kwargs["host"] == "redis-host"
    assert kwargs["port"] == 6379
    assert kwargs["db"] == 0

