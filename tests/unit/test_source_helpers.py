from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.cache.memory_cache import MemoryTTLCache
from app.core.config import AppMode, Settings
from app.core.errors import PublicApiError
from app.schemas.common import CacheStatus
from app.services.source_helpers import fetch_normalized_with_cache


async def test_cache_hit_uses_original_fetch_timestamp() -> None:
    now = 1000.0
    fetched_at = datetime(2026, 7, 13, 1, 2, 3, tzinfo=UTC)
    cache = MemoryTTLCache(stale_ttl_seconds=30, time_fn=lambda: now)
    await cache.set("facility", ["cached"], ttl_seconds=10, fetched_at=fetched_at)
    now = 1005.0

    async def unexpected_fetch() -> dict[str, object]:
        raise AssertionError("fresh cache hit must not call the source")

    result = await fetch_normalized_with_cache(
        settings=Settings(_env_file=None, app_mode=AppMode.MOCK),
        cache=cache,
        cache_key="facility",
        ttl_seconds=10,
        source_name="facility_info",
        fetch=unexpected_fetch,
        normalize=lambda raw: list(raw.get("rows", [])),
        failure_limitation="시설 정보를 확인하지 못했습니다.",
    )

    assert result.value == ["cached"]
    assert result.data_sources[0].cache_status == CacheStatus.HIT
    assert result.data_sources[0].fetched_at == fetched_at
    assert result.data_sources[0].staleness_seconds == 5


async def test_stale_fallback_uses_original_fetch_timestamp() -> None:
    now = 1000.0
    fetched_at = datetime(2026, 7, 13, 1, 2, 3, tzinfo=UTC)
    cache = MemoryTTLCache(stale_ttl_seconds=30, time_fn=lambda: now)
    await cache.set("elevator", ["cached"], ttl_seconds=10, fetched_at=fetched_at)
    now = 1012.0

    async def failing_fetch() -> dict[str, object]:
        raise PublicApiError("elevator_status", "timeout")

    result = await fetch_normalized_with_cache(
        settings=Settings(_env_file=None, app_mode=AppMode.LIVE),
        cache=cache,
        cache_key="elevator",
        ttl_seconds=10,
        source_name="elevator_status",
        fetch=failing_fetch,
        normalize=lambda raw: list(raw.get("rows", [])),
        failure_limitation="승강기 상태를 확인하지 못했습니다.",
    )

    assert result.value == ["cached"]
    assert result.data_sources[0].cache_status == CacheStatus.STALE
    assert result.data_sources[0].fetched_at == fetched_at
    assert result.data_sources[0].staleness_seconds == 12


async def test_expired_stale_entry_is_not_used_as_fallback() -> None:
    now = 1000.0
    fetched_at = datetime(2026, 7, 13, 1, 2, 3, tzinfo=UTC)
    cache = MemoryTTLCache(stale_ttl_seconds=5, time_fn=lambda: now)
    await cache.set("restroom", ["cached"], ttl_seconds=10, fetched_at=fetched_at)
    now = 1016.0

    async def failing_fetch() -> dict[str, object]:
        raise PublicApiError("restroom", "timeout")

    result = await fetch_normalized_with_cache(
        settings=Settings(_env_file=None, app_mode=AppMode.LIVE),
        cache=cache,
        cache_key="restroom",
        ttl_seconds=10,
        source_name="restroom",
        fetch=failing_fetch,
        normalize=lambda raw: list(raw.get("rows", [])),
        failure_limitation="화장실 정보를 확인하지 못했습니다.",
    )

    assert result.value == []
    assert result.data_sources[0].cache_status == CacheStatus.MISS
    assert result.data_sources[0].fetched_at != fetched_at


async def test_concurrent_cache_misses_share_one_source_fetch() -> None:
    cache = MemoryTTLCache()
    fetch_count = 0

    async def fetch() -> dict[str, object]:
        nonlocal fetch_count
        fetch_count += 1
        await asyncio.sleep(0.01)
        return {"rows": ["value"]}

    async def load():
        return await fetch_normalized_with_cache(
            settings=Settings(_env_file=None, app_mode=AppMode.LIVE),
            cache=cache,
            cache_key="facility:all",
            ttl_seconds=60,
            source_name="facility_info",
            fetch=fetch,
            normalize=lambda raw: list(raw.get("rows", [])),
            failure_limitation="시설 정보를 확인하지 못했습니다.",
        )

    first, second = await asyncio.gather(load(), load())

    assert fetch_count == 1
    assert first.value == second.value == ["value"]
    assert {
        first.data_sources[0].cache_status,
        second.data_sources[0].cache_status,
    } == {CacheStatus.MISS, CacheStatus.HIT}
