from __future__ import annotations

from app.cache.base import CacheProtocol
from app.cache.factory import build_cache
from app.core.config import Settings, get_settings
from app.normalizers.facility_normalizer import normalize_facilities
from app.normalizers.helpers import line_matches, station_matches
from app.schemas.facility import AccessibleFacility, FacilityType
from app.services import client_factory
from app.services.source_helpers import fetch_normalized_with_cache
from app.services.station_context import StationLookupContext, resolve_station_context
from app.services.station_service import StationService
from app.services.types import ServiceResult


class FacilityService:
    def __init__(
        self,
        settings: Settings | None = None,
        cache: CacheProtocol | None = None,
        station_service: StationService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache or build_cache(self.settings)
        self.station_service = station_service or StationService()

    async def get_station_facilities(
        self,
        station: str,
        line: str | None = None,
    ) -> ServiceResult[list[AccessibleFacility]]:
        context = self._station_context(station, line)
        client = client_factory.facility_client(self.settings)
        result = await fetch_normalized_with_cache(
            settings=self.settings,
            cache=self.cache,
            cache_key=f"facility:all:{context.line or '*'}",
            ttl_seconds=self.settings.facility_info_ttl_seconds,
            source_name="facility_info",
            fetch=lambda: client.fetch(line=context.line),
            normalize=lambda raw: normalize_facilities(raw, line=context.line),
            failure_limitation="역사 편의시설 위치 정보를 확인하지 못했습니다.",
        )
        return _filter_service_result(
            result,
            station=context.station_name,
            line=context.line,
        )

    async def get_elevator_status(
        self,
        station: str,
        line: str | None = None,
    ) -> ServiceResult[list[AccessibleFacility]]:
        context = self._station_context(station, line)
        status_client = client_factory.elevator_status_client(self.settings)
        status_result = await fetch_normalized_with_cache(
            settings=self.settings,
            cache=self.cache,
            cache_key=f"elevator_status:all:{context.line or '*'}",
            ttl_seconds=self.settings.elevator_status_ttl_seconds,
            source_name="elevator_status",
            fetch=lambda: status_client.fetch(line=context.line),
            normalize=lambda raw: normalize_facilities(
                raw,
                line=context.line,
                facility_type=FacilityType.ELEVATOR,
            ),
            failure_limitation="승강기 실시간 상태를 확인하지 못했습니다.",
        )
        info_client = client_factory.elevator_info_client(self.settings)
        info_result = await fetch_normalized_with_cache(
            settings=self.settings,
            cache=self.cache,
            cache_key=f"elevator_info:all:{context.line or '*'}",
            ttl_seconds=self.settings.facility_info_ttl_seconds,
            source_name="elevator_info",
            fetch=lambda: info_client.fetch(line=context.line),
            normalize=lambda raw: normalize_facilities(
                raw,
                line=context.line,
                facility_type=FacilityType.ELEVATOR,
            ),
            failure_limitation="엘리베이터 설치 현황 정보를 확인하지 못했습니다.",
        )
        return ServiceResult(
            value=_filter_facilities(
                _dedupe_facilities([*status_result.value, *info_result.value]),
                station=context.station_name,
                line=context.line,
            ),
            data_sources=[*status_result.data_sources, *info_result.data_sources],
            failed_sources=[*status_result.failed_sources, *info_result.failed_sources],
            limitations=[*status_result.limitations, *info_result.limitations],
        )

    async def get_accessible_restroom(
        self,
        station: str,
        line: str | None = None,
    ) -> ServiceResult[list[AccessibleFacility]]:
        context = self._station_context(station, line)
        client = client_factory.restroom_client(self.settings)
        result = await fetch_normalized_with_cache(
            settings=self.settings,
            cache=self.cache,
            cache_key=f"restroom:all:{context.line or '*'}",
            ttl_seconds=self.settings.facility_info_ttl_seconds,
            source_name="restroom",
            fetch=lambda: client.fetch(line=context.line),
            normalize=lambda raw: normalize_facilities(
                raw,
                line=context.line,
                facility_type=FacilityType.ACCESSIBLE_RESTROOM,
            ),
            failure_limitation="장애인화장실 정보를 확인하지 못했습니다.",
        )
        return _filter_service_result(
            result,
            station=context.station_name,
            line=context.line,
        )

    def _station_context(
        self,
        station: str,
        line: str | None,
    ) -> StationLookupContext:
        return resolve_station_context(
            self.station_service,
            station,
            explicit_line=line,
        )


def _dedupe_facilities(facilities: list[AccessibleFacility]) -> list[AccessibleFacility]:
    seen: set[tuple[str | None, str, FacilityType]] = set()
    deduped: list[AccessibleFacility] = []
    for facility in facilities:
        identity = (facility.facility_id, facility.station_name, facility.facility_type)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(facility)
    return deduped


def _filter_facilities(
    facilities: list[AccessibleFacility],
    *,
    station: str,
    line: str | None,
) -> list[AccessibleFacility]:
    return [
        facility
        for facility in facilities
        if station_matches(facility.station_name, station) and line_matches(facility.line, line)
    ]


def _filter_service_result(
    result: ServiceResult[list[AccessibleFacility]],
    *,
    station: str,
    line: str | None,
) -> ServiceResult[list[AccessibleFacility]]:
    return ServiceResult(
        value=_filter_facilities(result.value, station=station, line=line),
        data_sources=result.data_sources,
        failed_sources=result.failed_sources,
        limitations=result.limitations,
    )
