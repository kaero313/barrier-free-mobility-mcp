from __future__ import annotations

from app.cache.base import CacheProtocol
from app.cache.memory_cache import MemoryTTLCache
from app.cache.redis_cache import RedisTTLCache
from app.core.config import CacheBackend, Settings, get_settings


def build_cache(settings: Settings | None = None) -> CacheProtocol:
    active_settings = settings or get_settings()
    if active_settings.cache_backend == CacheBackend.REDIS:
        return RedisTTLCache(
            active_settings.redis_url,
            stale_ttl_seconds=active_settings.cache_stale_ttl_seconds,
            socket_timeout_seconds=active_settings.redis_socket_timeout_seconds,
            socket_connect_timeout_seconds=active_settings.redis_socket_connect_timeout_seconds,
        )
    return MemoryTTLCache()


def redis_cache_available(settings: Settings | None = None) -> bool:
    active_settings = settings or get_settings()
    if active_settings.cache_backend != CacheBackend.REDIS:
        return False
    return RedisTTLCache(
        active_settings.redis_url,
        stale_ttl_seconds=active_settings.cache_stale_ttl_seconds,
        socket_timeout_seconds=active_settings.redis_socket_timeout_seconds,
        socket_connect_timeout_seconds=active_settings.redis_socket_connect_timeout_seconds,
    ).ping()
