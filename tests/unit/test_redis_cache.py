from __future__ import annotations

from redis.exceptions import RedisError

from app.cache.factory import build_cache
from app.cache.memory_cache import MemoryTTLCache
from app.cache.redis_cache import RedisTTLCache
from app.core.config import CacheBackend, Settings


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.expirations: dict[str, int] = {}

    def get(self, name: str) -> bytes | None:
        return self.values.get(name)

    def set(self, name: str, value: bytes, *, ex: int) -> None:
        self.values[name] = value
        self.expirations[name] = ex

    def ping(self) -> bool:
        return True


class FailingRedis(FakeRedis):
    def get(self, name: str) -> bytes | None:
        raise RedisError("redis unavailable")

    def set(self, name: str, value: bytes, *, ex: int) -> None:
        raise RedisError("redis unavailable")

    def ping(self) -> bool:
        raise RedisError("redis unavailable")


def test_redis_cache_returns_fresh_hit() -> None:
    now = 1000.0
    client = FakeRedis()
    cache = RedisTTLCache(
        "redis://unused",
        stale_ttl_seconds=60,
        socket_timeout_seconds=1,
        socket_connect_timeout_seconds=1,
        client=client,  # type: ignore[arg-type]
        time_fn=lambda: now,
    )

    cache.set("route:홍대입구:삼성", {"ok": True}, ttl_seconds=30)
    now = 1010.0

    entry = cache.get("route:홍대입구:삼성")

    assert entry is not None
    assert entry.value == {"ok": True}
    assert entry.stale is False
    assert entry.staleness_seconds == 10


def test_redis_cache_returns_stale_only_when_allowed() -> None:
    now = 1000.0
    cache = RedisTTLCache(
        "redis://unused",
        stale_ttl_seconds=60,
        socket_timeout_seconds=1,
        socket_connect_timeout_seconds=1,
        client=FakeRedis(),  # type: ignore[arg-type]
        time_fn=lambda: now,
    )

    cache.set("facility:all:2", ["elevator"], ttl_seconds=10)
    now = 1012.0

    assert cache.get("facility:all:2") is None
    stale = cache.get("facility:all:2", allow_stale=True)

    assert stale is not None
    assert stale.value == ["elevator"]
    assert stale.stale is True


def test_redis_cache_drops_entries_after_stale_window() -> None:
    now = 1000.0
    cache = RedisTTLCache(
        "redis://unused",
        stale_ttl_seconds=5,
        socket_timeout_seconds=1,
        socket_connect_timeout_seconds=1,
        client=FakeRedis(),  # type: ignore[arg-type]
        time_fn=lambda: now,
    )

    cache.set("restroom:all:9", "value", ttl_seconds=10)
    now = 1016.0

    assert cache.get("restroom:all:9", allow_stale=True) is None


def test_redis_cache_failure_behaves_like_miss() -> None:
    cache = RedisTTLCache(
        "redis://unused",
        stale_ttl_seconds=60,
        socket_timeout_seconds=1,
        socket_connect_timeout_seconds=1,
        client=FailingRedis(),  # type: ignore[arg-type]
    )

    cache.set("route:서울역:시청", "value", ttl_seconds=10)

    assert cache.get("route:서울역:시청") is None
    assert cache.ping() is False


def test_redis_cache_key_hashes_user_input() -> None:
    cache = RedisTTLCache(
        "redis://unused",
        stale_ttl_seconds=60,
        socket_timeout_seconds=1,
        socket_connect_timeout_seconds=1,
        client=FakeRedis(),  # type: ignore[arg-type]
    )

    redis_key = cache._redis_key("route:홍대입구:삼성")

    assert "홍대입구" not in redis_key
    assert "삼성" not in redis_key
    assert redis_key.startswith("barrier-free-mobility-mcp:cache:v1:")


def test_cache_factory_builds_memory_and_redis_backends() -> None:
    memory = build_cache(Settings(_env_file=None, cache_backend=CacheBackend.MEMORY))
    redis = build_cache(
        Settings(
            _env_file=None,
            cache_backend=CacheBackend.REDIS,
            redis_url="redis://localhost:1/0",
            redis_socket_timeout_seconds=0.01,
            redis_socket_connect_timeout_seconds=0.01,
        )
    )

    assert isinstance(memory, MemoryTTLCache)
    assert isinstance(redis, RedisTTLCache)
