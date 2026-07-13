from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from app.cache.base import CacheEntry


@dataclass
class _StoredValue:
    value: Any
    created_at: float
    expires_at: float
    stale_expires_at: float
    fetched_at: datetime


class MemoryTTLCache:
    def __init__(
        self,
        *,
        stale_ttl_seconds: int = 86400,
        time_fn: Callable[[], float] = monotonic,
    ) -> None:
        self.stale_ttl_seconds = max(0, int(stale_ttl_seconds))
        self._time_fn = time_fn
        self._values: dict[str, _StoredValue] = {}

    async def get(self, key: str, *, allow_stale: bool = False) -> CacheEntry | None:
        stored = self._values.get(key)
        if stored is None:
            return None
        now = self._time_fn()
        if now > stored.stale_expires_at:
            self._values.pop(key, None)
            return None
        stale = now > stored.expires_at
        if stale and not allow_stale:
            return None
        return CacheEntry(
            value=stored.value,
            staleness_seconds=max(0, int(now - stored.created_at)),
            stale=stale,
            fetched_at=stored.fetched_at,
        )

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: int,
        fetched_at: datetime | None = None,
    ) -> None:
        fresh_ttl_seconds = max(1, int(ttl_seconds))
        now = self._time_fn()
        self._values[key] = _StoredValue(
            value=value,
            created_at=now,
            expires_at=now + fresh_ttl_seconds,
            stale_expires_at=now + fresh_ttl_seconds + self.stale_ttl_seconds,
            fetched_at=_as_utc(fetched_at or datetime.now(UTC)),
        )

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
