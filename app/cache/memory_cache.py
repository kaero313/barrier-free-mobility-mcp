from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from app.cache.base import CacheEntry


@dataclass
class _StoredValue:
    value: Any
    created_at: float
    expires_at: float


class MemoryTTLCache:
    def __init__(self) -> None:
        self._values: dict[str, _StoredValue] = {}

    def get(self, key: str, *, allow_stale: bool = False) -> CacheEntry | None:
        stored = self._values.get(key)
        if stored is None:
            return None
        now = monotonic()
        stale = now > stored.expires_at
        if stale and not allow_stale:
            return None
        return CacheEntry(
            value=stored.value,
            staleness_seconds=max(0, int(now - stored.created_at)),
            stale=stale,
        )

    def set(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        now = monotonic()
        self._values[key] = _StoredValue(
            value=value,
            created_at=now,
            expires_at=now + ttl_seconds,
        )

