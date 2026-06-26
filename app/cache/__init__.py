"""Cache abstractions."""

from app.cache.base import CacheEntry, CacheProtocol
from app.cache.factory import build_cache
from app.cache.memory_cache import MemoryTTLCache
from app.cache.redis_cache import RedisTTLCache

__all__ = ["CacheEntry", "CacheProtocol", "MemoryTTLCache", "RedisTTLCache", "build_cache"]
