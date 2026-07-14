from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.core.config import AppMode, Settings
from app.schemas.accessibility import MobilityProfile
from app.schemas.common import DataSourceMeta
from app.schemas.route import RouteCandidate, RouteSegment
from app.services.accessibility_service import AccessibilityService
from app.services.types import ServiceResult


class _MultiStationRouteService:
    async def get_route_candidates(self, origin: str, destination: str):
        return ServiceResult(
            value=[
                RouteCandidate(
                    route_id="multi-station",
                    origin=origin,
                    destination=destination,
                    segments=[
                        RouteSegment(
                            from_station=origin,
                            to_station=destination,
                            line="2호선",
                        )
                    ],
                    stations=[origin, "강남", destination],
                    transfer_count=0,
                )
            ],
            data_sources=[_source("shortest_route")],
        )


class _ConcurrencyTrackingFacilityService:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def get_station_facilities(self, station: str, line: str | None = None):
        return await self._query("facility_info")

    async def get_elevator_status(self, station: str, line: str | None = None):
        return await self._query("elevator_status")

    async def get_accessible_restroom(self, station: str, line: str | None = None):
        return await self._query("restroom")

    async def _query(self, source_name: str):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            return ServiceResult(value=[], data_sources=[_source(source_name)])
        finally:
            self.active -= 1


async def test_trip_facility_queries_respect_configured_concurrency_bound() -> None:
    facility_service = _ConcurrencyTrackingFacilityService()
    service = AccessibilityService(
        settings=Settings(
            _env_file=None,
            app_mode=AppMode.MOCK,
            facility_query_concurrency=2,
        ),
        route_service=_MultiStationRouteService(),  # type: ignore[arg-type]
        facility_service=facility_service,  # type: ignore[arg-type]
    )

    result = await service.check_accessible_trip(
        "2호선 홍대입구",
        "2호선 삼성",
        MobilityProfile(),
    )

    assert result.selected_route is not None
    assert facility_service.max_active == 2


def _source(source_name: str) -> DataSourceMeta:
    return DataSourceMeta(
        source_name=source_name,
        source_type="fixture",
        fetched_at=datetime(2026, 7, 13, tzinfo=UTC),
    )
