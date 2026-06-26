from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    staleness_seconds: int
    stale: bool


class CacheProtocol(Protocol):
    def get(self, key: str, *, allow_stale: bool = False) -> CacheEntry | None: ...

    def set(self, key: str, value: Any, *, ttl_seconds: int) -> None: ...

