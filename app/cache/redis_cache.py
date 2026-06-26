from __future__ import annotations

import pickle
from collections.abc import Callable
from hashlib import sha256
from time import time
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.cache.base import CacheEntry

CACHE_PAYLOAD_VERSION = 1
DEFAULT_KEY_PREFIX = "barrier-free-mobility-mcp:cache:v1"


class RedisTTLCache:
    """Redis-backed TTL cache for server-internal normalized values."""

    def __init__(
        self,
        redis_url: str,
        *,
        stale_ttl_seconds: int,
        socket_timeout_seconds: float,
        socket_connect_timeout_seconds: float,
        key_prefix: str = DEFAULT_KEY_PREFIX,
        client: Redis | None = None,
        time_fn: Callable[[], float] = time,
    ) -> None:
        self._key_prefix = key_prefix.rstrip(":")
        self._stale_ttl_seconds = max(0, int(stale_ttl_seconds))
        self._time_fn = time_fn
        self._client = client or Redis.from_url(
            redis_url,
            socket_timeout=socket_timeout_seconds,
            socket_connect_timeout=socket_connect_timeout_seconds,
            decode_responses=False,
        )

    def get(self, key: str, *, allow_stale: bool = False) -> CacheEntry | None:
        try:
            raw = self._client.get(self._redis_key(key))
        except RedisError:
            return None
        if raw is None:
            return None

        payload = self._loads(raw)
        if payload is None:
            return None

        now = self._time_fn()
        if now > payload["stale_expires_at"]:
            return None

        stale = now > payload["expires_at"]
        if stale and not allow_stale:
            return None

        return CacheEntry(
            value=payload["value"],
            staleness_seconds=max(0, int(now - payload["created_at"])),
            stale=stale,
        )

    def set(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        fresh_ttl_seconds = max(1, int(ttl_seconds))
        now = self._time_fn()
        stale_expires_at = now + fresh_ttl_seconds + self._stale_ttl_seconds
        payload = {
            "version": CACHE_PAYLOAD_VERSION,
            "created_at": now,
            "expires_at": now + fresh_ttl_seconds,
            "stale_expires_at": stale_expires_at,
            "value": value,
        }
        try:
            self._client.set(
                self._redis_key(key),
                pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL),
                ex=max(1, int(stale_expires_at - now)),
            )
        except RedisError:
            return

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except RedisError:
            return False

    def _redis_key(self, key: str) -> str:
        digest = sha256(key.encode("utf-8")).hexdigest()
        return f"{self._key_prefix}:{digest}"

    @staticmethod
    def _loads(raw: bytes) -> dict[str, Any] | None:
        try:
            payload = pickle.loads(raw)
        except (pickle.PickleError, EOFError, AttributeError, TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("version") != CACHE_PAYLOAD_VERSION:
            return None
        required = {"created_at", "expires_at", "stale_expires_at", "value"}
        if not required.issubset(payload):
            return None
        return payload


RedisCache = RedisTTLCache
