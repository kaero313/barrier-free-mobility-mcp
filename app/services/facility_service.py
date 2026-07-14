from __future__ import annotations

import asyncio

from app.cache.base import CacheProtocol
from app.cache.factory import build_cache
from app.core.config import Settings, get_settings
from app.core.time import utc_now
from app.normalizers.facility_identity import facility_record_identity
from app.normalizers.facility_normalizer import normalize_facilities
from app.normalizers.helpers import line_matches, station_matches
from app.schemas.common import (
    CacheStatus,
    DataSourceMeta,
    FailedSource,
    SourceCoverageStatus,
)
from app.schemas.facility import AccessibleFacility, FacilityType
from app.services import client_factory
from app.services.source_coverage import (
    SourceCoverageDecision,
    evaluate_source_coverage,
)
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
        if _has_unresolved_explicit_line(context):
            return _unresolved_station_result(context)
        coverage = evaluate_source_coverage(
            "facility_info",
            context,
            app_mode=self.settings.app_mode,
        )
        if coverage.status == SourceCoverageStatus.UNSUPPORTED:
            return _unsupported_source_result(coverage)
        client = client_factory.facility_client(self.settings)
        result = await fetch_normalized_with_cache(
            settings=self.settings,
            cache=self.cache,
            cache_key="facility:all",
            ttl_seconds=self.settings.facility_info_ttl_seconds,
            source_name="facility_info",
            fetch=client.fetch,
            normalize=lambda raw: normalize_facilities(
                raw,
                line=None,
                source_name="facility_info",
            ),
            failure_limitation="역사 편의시설 위치 정보를 확인하지 못했습니다.",
        )
        return _filter_service_result(
            _annotate_source_coverage(result, coverage),
            station=context.station_name,
            line=context.line,
        )

    async def get_elevator_status(
        self,
        station: str,
        line: str | None = None,
    ) -> ServiceResult[list[AccessibleFacility]]:
        context = self._station_context(station, line)
        if _has_unresolved_explicit_line(context):
            return _unresolved_station_result(context)
        status_coverage = evaluate_source_coverage(
            "elevator_status",
            context,
            app_mode=self.settings.app_mode,
        )
        info_coverage = evaluate_source_coverage(
            "elevator_info",
            context,
            app_mode=self.settings.app_mode,
        )
        status_result, info_result = await asyncio.gather(
            self._get_elevator_source(
                source_name="elevator_status",
                coverage=status_coverage,
            ),
            self._get_elevator_source(
                source_name="elevator_info",
                coverage=info_coverage,
            ),
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
        if _has_unresolved_explicit_line(context):
            return _unresolved_station_result(context)
        coverage = evaluate_source_coverage(
            "restroom",
            context,
            app_mode=self.settings.app_mode,
        )
        if coverage.status == SourceCoverageStatus.UNSUPPORTED:
            return _unsupported_source_result(coverage)
        client = client_factory.restroom_client(self.settings)
        result = await fetch_normalized_with_cache(
            settings=self.settings,
            cache=self.cache,
            cache_key="restroom:all",
            ttl_seconds=self.settings.facility_info_ttl_seconds,
            source_name="restroom",
            fetch=client.fetch,
            normalize=lambda raw: normalize_facilities(
                raw,
                line=None,
                facility_type=FacilityType.ACCESSIBLE_RESTROOM,
                source_name="restroom",
            ),
            failure_limitation="장애인화장실 정보를 확인하지 못했습니다.",
        )
        return _filter_service_result(
            _annotate_source_coverage(result, coverage),
            station=context.station_name,
            line=context.line,
        )

    async def _get_elevator_source(
        self,
        *,
        source_name: str,
        coverage: SourceCoverageDecision,
    ) -> ServiceResult[list[AccessibleFacility]]:
        if coverage.status == SourceCoverageStatus.UNSUPPORTED:
            return _unsupported_source_result(coverage)

        if source_name == "elevator_status":
            client = client_factory.elevator_status_client(self.settings)
            ttl_seconds = self.settings.elevator_status_ttl_seconds
            limitation = "승강기 실시간 상태를 확인하지 못했습니다."
        else:
            client = client_factory.elevator_info_client(self.settings)
            ttl_seconds = self.settings.facility_info_ttl_seconds
            limitation = "엘리베이터 설치 현황 정보를 확인하지 못했습니다."

        result = await fetch_normalized_with_cache(
            settings=self.settings,
            cache=self.cache,
            cache_key=f"{source_name}:all",
            ttl_seconds=ttl_seconds,
            source_name=source_name,
            fetch=client.fetch,
            normalize=lambda raw: normalize_facilities(
                raw,
                line=None,
                facility_type=FacilityType.ELEVATOR,
                source_name=source_name,
            ),
            failure_limitation=limitation,
        )
        return _annotate_source_coverage(result, coverage)

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
    seen: set[tuple[str, ...]] = set()
    deduped: list[AccessibleFacility] = []
    for facility in facilities:
        identity = facility_record_identity(facility)
        if identity is not None and identity in seen:
            continue
        if identity is not None:
            seen.add(identity)
        deduped.append(facility)
    return deduped


def _unresolved_station_result(
    context: StationLookupContext,
) -> ServiceResult[list[AccessibleFacility]]:
    limitation = context.clarification_message or (
        "역명과 호선을 확정하지 못해 시설 정보를 조회하지 않았습니다."
    )
    return ServiceResult(
        value=[],
        failed_sources=[
            FailedSource(
                source_name="station_resolution",
                reason="needs_clarification",
            )
        ],
        limitations=[limitation],
    )


def _unsupported_source_result(
    decision: SourceCoverageDecision,
) -> ServiceResult[list[AccessibleFacility]]:
    note = decision.note or "현재 연결된 공공데이터의 제공 범위 밖입니다."
    return ServiceResult(
        value=[],
        data_sources=[
            DataSourceMeta(
                source_name=decision.source_name,
                source_type="public_api",
                fetched_at=utc_now(),
                cache_status=CacheStatus.BYPASS,
                success=False,
                coverage_status=SourceCoverageStatus.UNSUPPORTED,
                coverage_note=note,
            )
        ],
        limitations=[note],
    )


def _annotate_source_coverage(
    result: ServiceResult[list[AccessibleFacility]],
    decision: SourceCoverageDecision,
) -> ServiceResult[list[AccessibleFacility]]:
    return ServiceResult(
        value=result.value,
        data_sources=[
            source.model_copy(
                update={
                    "coverage_status": decision.status,
                    "coverage_note": decision.note,
                }
            )
            for source in result.data_sources
        ],
        failed_sources=result.failed_sources,
        limitations=result.limitations,
    )


def _has_unresolved_explicit_line(context: StationLookupContext) -> bool:
    return context.needs_clarification and context.line is not None


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
