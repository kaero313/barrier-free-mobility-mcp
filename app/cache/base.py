from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    staleness_seconds: int
    stale: bool
    fetched_at: datetime


class CacheProtocol(Protocol):
    async def get(
        self,
        key: str,
        *,
        allow_stale: bool = False,
    ) -> CacheEntry | None: ...

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: int,
        fetched_at: datetime | None = None,
    ) -> None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...
