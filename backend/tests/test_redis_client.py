import app.redis_client as redis_client


def test_get_redis_singleton(monkeypatch):
    redis_client._redis_client = None

    class DummyRedis:
        pass

    def fake_from_url(url, decode_responses):
        return DummyRedis()

    monkeypatch.setattr(redis_client.settings, "redis_url", "redis://example", raising=False)
    monkeypatch.setattr(redis_client.redis.Redis, "from_url", staticmethod(fake_from_url))

    client_a = redis_client.get_redis()
    client_b = redis_client.get_redis()

    assert isinstance(client_a, DummyRedis)
    assert client_a is client_b
