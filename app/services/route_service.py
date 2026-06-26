from __future__ import annotations

from datetime import datetime

from app.cache.base import CacheProtocol
from app.cache.factory import build_cache
from app.core.config import Settings, get_settings
from app.normalizers.route_normalizer import normalize_route_candidates
from app.schemas.route import RouteCandidate
from app.services import client_factory
from app.services.source_helpers import fetch_normalized_with_cache
from app.services.types import ServiceResult


class RouteService:
    def __init__(
        self,
        settings: Settings | None = None,
        cache: CacheProtocol | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache or build_cache(self.settings)

    async def get_route_candidates(
        self,
        origin: str,
        destination: str,
    ) -> ServiceResult[list[RouteCandidate]]:
        client = client_factory.route_client(self.settings)
        return await fetch_normalized_with_cache(
            settings=self.settings,
            cache=self.cache,
            cache_key=route_cache_key(origin, destination, self.settings),
            ttl_seconds=self.settings.route_ttl_seconds,
            source_name="shortest_route",
            fetch=lambda: client.fetch(origin=origin, destination=destination),
            normalize=lambda raw: normalize_route_candidates(
                raw,
                origin=origin,
                destination=destination,
            ),
            failure_limitation="최단경로 후보 정보를 확인하지 못했습니다.",
        )


def route_cache_key(
    origin: str,
    destination: str,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> str:
    return f"route:{origin}:{destination}:{route_search_cache_scope(settings, now=now)}"


def route_search_cache_scope(settings: Settings, *, now: datetime | None = None) -> str:
    if not settings.route_search_date_param:
        return "no-search-date"

    search_date = settings.route_default_search_date.strip()
    if search_date:
        return f"{settings.route_search_date_param}={search_date}"

    current = now or datetime.now()
    return f"{settings.route_search_date_param}={current.strftime('%Y-%m-%d %H:00:00')}"
