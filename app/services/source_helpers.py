from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from weakref import WeakKeyDictionary

from app.cache.base import CacheProtocol
from app.core.config import AppMode, Settings
from app.core.errors import PublicApiError
from app.core.metrics import metrics_registry
from app.core.time import utc_now
from app.schemas.common import CacheStatus, DataSourceMeta, FailedSource
from app.services.types import ServiceResult

_CACHE_KEY_LOCKS: WeakKeyDictionary[object, dict[str, asyncio.Lock]] = (
    WeakKeyDictionary()
)


async def fetch_normalized_with_cache[T](
    *,
    settings: Settings,
    cache: CacheProtocol,
    cache_key: str,
    ttl_seconds: int,
    source_name: str,
    fetch: Callable[[], Awaitable[dict[str, Any]]],
    normalize: Callable[[dict[str, Any]], T],
    failure_limitation: str,
) -> ServiceResult[T]:
    cached = await cache.get(cache_key)
    if cached is not None:
        return _cache_hit_result(
            cached,
            source_name=source_name,
        )

    async with _cache_key_lock(cache, cache_key):
        cached = await cache.get(cache_key)
        if cached is not None:
            return _cache_hit_result(
                cached,
                source_name=source_name,
            )

        try:
            raw = await fetch()
            fetched_at = utc_now()
            value = normalize(raw)
            await cache.set(
                cache_key,
                value,
                ttl_seconds=ttl_seconds,
                fetched_at=fetched_at,
            )
            metrics_registry.record_cache_event(CacheStatus.MISS)
            return ServiceResult(
                value=value,
                data_sources=[
                    DataSourceMeta(
                        source_name=source_name,
                        source_type=(
                            "fixture" if settings.app_mode == AppMode.MOCK else "public_api"
                        ),
                        fetched_at=fetched_at,
                        cache_status=CacheStatus.MISS,
                    )
                ],
            )
        except PublicApiError as exc:
            stale = await cache.get(cache_key, allow_stale=True)
            metrics_registry.record_fallback_response()
            failed = FailedSource(
                source_name=exc.source_name,
                reason=exc.reason,
                recoverable=exc.recoverable,
            )
            if stale is not None:
                metrics_registry.record_cache_event(CacheStatus.STALE)
                return ServiceResult(
                    value=stale.value,
                    data_sources=[
                        DataSourceMeta(
                            source_name=source_name,
                            source_type="cache",
                            fetched_at=stale.fetched_at,
                            cache_status=CacheStatus.STALE,
                            staleness_seconds=stale.staleness_seconds,
                            success=False,
                            error_message=exc.reason,
                        )
                    ],
                    failed_sources=[failed],
                    limitations=[failure_limitation],
                )
            metrics_registry.record_cache_event(CacheStatus.MISS)
            return ServiceResult(
                value=normalize({"rows": []}),
                data_sources=[
                    DataSourceMeta(
                        source_name=source_name,
                        source_type=(
                            "public_api" if settings.app_mode == AppMode.LIVE else "fixture"
                        ),
                        fetched_at=utc_now(),
                        cache_status=CacheStatus.MISS,
                        success=False,
                        error_message=exc.reason,
                    )
                ],
                failed_sources=[failed],
                limitations=[failure_limitation],
            )


def _cache_key_lock(cache: CacheProtocol, cache_key: str) -> asyncio.Lock:
    locks = _CACHE_KEY_LOCKS.setdefault(cache, {})
    return locks.setdefault(cache_key, asyncio.Lock())


def _cache_hit_result[T](cached: Any, *, source_name: str) -> ServiceResult[T]:
    metrics_registry.record_cache_event(CacheStatus.HIT)
    return ServiceResult(
        value=cached.value,
        data_sources=[
            DataSourceMeta(
                source_name=source_name,
                source_type="cache",
                fetched_at=cached.fetched_at,
                cache_status=CacheStatus.HIT,
                staleness_seconds=cached.staleness_seconds,
            )
        ],
    )
