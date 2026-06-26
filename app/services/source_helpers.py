from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.cache.base import CacheProtocol
from app.core.config import AppMode, Settings
from app.core.errors import PublicApiError
from app.core.metrics import metrics_registry
from app.core.time import utc_now
from app.schemas.common import CacheStatus, DataSourceMeta, FailedSource
from app.services.types import ServiceResult


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
    cached = cache.get(cache_key)
    if cached is not None:
        metrics_registry.record_cache_event(CacheStatus.HIT)
        return ServiceResult(
            value=cached.value,
            data_sources=[
                DataSourceMeta(
                    source_name=source_name,
                    source_type="cache",
                    fetched_at=utc_now(),
                    cache_status=CacheStatus.HIT,
                    staleness_seconds=cached.staleness_seconds,
                )
            ],
        )

    try:
        raw = await fetch()
        value = normalize(raw)
        cache.set(cache_key, value, ttl_seconds=ttl_seconds)
        metrics_registry.record_cache_event(CacheStatus.MISS)
        return ServiceResult(
            value=value,
            data_sources=[
                DataSourceMeta(
                    source_name=source_name,
                    source_type="fixture" if settings.app_mode == AppMode.MOCK else "public_api",
                    fetched_at=utc_now(),
                    cache_status=CacheStatus.MISS,
                )
            ],
        )
    except PublicApiError as exc:
        stale = cache.get(cache_key, allow_stale=True)
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
                        fetched_at=utc_now(),
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
                    source_type="public_api" if settings.app_mode == AppMode.LIVE else "fixture",
                    fetched_at=utc_now(),
                    cache_status=CacheStatus.MISS,
                    success=False,
                    error_message=exc.reason,
                )
            ],
            failed_sources=[failed],
            limitations=[failure_limitation],
        )
