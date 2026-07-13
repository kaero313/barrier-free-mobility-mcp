from __future__ import annotations

import pickle
from datetime import UTC, datetime

from redis.exceptions import RedisError

from app.cache.factory import build_cache
from app.cache.memory_cache import MemoryTTLCache
from app.cache.redis_cache import RedisTTLCache
from app.core.config import CacheBackend, Settings


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, name: str) -> bytes | None:
        return self.values.get(name)

    async def set(self, name: str, value: bytes, *, ex: int) -> None:
        self.values[name] = value
        self.expirations[name] = ex

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


class FailingRedis(FakeRedis):
    async def get(self, name: str) -> bytes | None:
        raise RedisError("redis unavailable")

    async def set(self, name: str, value: bytes, *, ex: int) -> None:
        raise RedisError("redis unavailable")

    async def ping(self) -> bool:
        raise RedisError("redis unavailable")


async def test_redis_cache_returns_fresh_hit() -> None:
    now = 1000.0
    fetched_at = datetime(2026, 7, 13, 1, 2, 3, tzinfo=UTC)
    client = FakeRedis()
    cache = RedisTTLCache(
        "redis://unused",
        stale_ttl_seconds=60,
        socket_timeout_seconds=1,
        socket_connect_timeout_seconds=1,
        client=client,  # type: ignore[arg-type]
        time_fn=lambda: now,
    )

    await cache.set(
        "route:홍대입구:삼성",
        {"ok": True},
        ttl_seconds=30,
        fetched_at=fetched_at,
    )
    now = 1010.0

    entry = await cache.get("route:홍대입구:삼성")

    assert entry is not None
    assert entry.value == {"ok": True}
    assert entry.stale is False
    assert entry.staleness_seconds == 10
    assert entry.fetched_at == fetched_at


async def test_redis_cache_returns_stale_only_when_allowed() -> None:
    now = 1000.0
    cache = RedisTTLCache(
        "redis://unused",
        stale_ttl_seconds=60,
        socket_timeout_seconds=1,
        socket_connect_timeout_seconds=1,
        client=FakeRedis(),  # type: ignore[arg-type]
        time_fn=lambda: now,
    )

    await cache.set("facility:all:2", ["elevator"], ttl_seconds=10)
    now = 1012.0

    assert await cache.get("facility:all:2") is None
    stale = await cache.get("facility:all:2", allow_stale=True)

    assert stale is not None
    assert stale.value == ["elevator"]
    assert stale.stale is True


async def test_redis_cache_drops_entries_after_stale_window() -> None:
    now = 1000.0
    cache = RedisTTLCache(
        "redis://unused",
        stale_ttl_seconds=5,
        socket_timeout_seconds=1,
        socket_connect_timeout_seconds=1,
        client=FakeRedis(),  # type: ignore[arg-type]
        time_fn=lambda: now,
    )

    await cache.set("restroom:all:9", "value", ttl_seconds=10)
    now = 1016.0

    assert await cache.get("restroom:all:9", allow_stale=True) is None


async def test_redis_cache_failure_behaves_like_miss() -> None:
    cache = RedisTTLCache(
        "redis://unused",
        stale_ttl_seconds=60,
        socket_timeout_seconds=1,
        socket_connect_timeout_seconds=1,
        client=FailingRedis(),  # type: ignore[arg-type]
    )

    await cache.set("route:서울역:시청", "value", ttl_seconds=10)

    assert await cache.get("route:서울역:시청") is None
    assert await cache.ping() is False


async def test_redis_cache_invalid_timestamp_payload_behaves_like_miss() -> None:
    client = FakeRedis()
    cache = RedisTTLCache(
        "redis://unused",
        stale_ttl_seconds=60,
        socket_timeout_seconds=1,
        socket_connect_timeout_seconds=1,
        client=client,  # type: ignore[arg-type]
        time_fn=lambda: 1000.0,
    )
    client.values[cache._redis_key("route")] = pickle.dumps(
        {
            "version": 2,
            "created_at": 1000.0,
            "expires_at": 1010.0,
            "stale_expires_at": 1070.0,
            "fetched_at": "invalid",
            "value": {"ok": True},
        }
    )

    assert await cache.get("route") is None


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
    assert redis_key.startswith("barrier-free-mobility-mcp:cache:v2:")


async def test_memory_cache_uses_bounded_stale_window_and_preserves_fetched_at() -> None:
    now = 1000.0
    fetched_at = datetime(2026, 7, 13, 1, 2, 3, tzinfo=UTC)
    cache = MemoryTTLCache(stale_ttl_seconds=5, time_fn=lambda: now)

    await cache.set(
        "elevator:2",
        ["available"],
        ttl_seconds=10,
        fetched_at=fetched_at,
    )
    now = 1012.0

    assert await cache.get("elevator:2") is None
    stale = await cache.get("elevator:2", allow_stale=True)
    assert stale is not None
    assert stale.stale is True
    assert stale.staleness_seconds == 12
    assert stale.fetched_at == fetched_at

    now = 1016.0
    assert await cache.get("elevator:2", allow_stale=True) is None


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
    assert memory.stale_ttl_seconds == 86400
    assert isinstance(redis, RedisTTLCache)
