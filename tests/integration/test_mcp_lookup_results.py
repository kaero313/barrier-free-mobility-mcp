from __future__ import annotations

from datetime import UTC, datetime

from app.mcp import tools
from app.schemas.common import (
    CacheStatus,
    DataSourceMeta,
    FailedSource,
    ResponseStatus,
    SourceCoverageStatus,
)
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.schemas.lookup import LookupOutcome
from app.schemas.route import RouteCandidate
from app.services.types import ServiceResult

CHECKED_AT = datetime(2026, 7, 13, 9, 0, tzinfo=UTC)


class _FacilityServiceStub:
    def __init__(self, result: ServiceResult[list[AccessibleFacility]]) -> None:
        self.result = result

    async def get_station_facilities(self, station: str, line: str | None = None):
        return self.result

    async def get_elevator_status(self, station: str, line: str | None = None):
        return self.result

    async def get_accessible_restroom(self, station: str, line: str | None = None):
        return self.result


class _RouteServiceStub:
    def __init__(self, result: ServiceResult[list[RouteCandidate]]) -> None:
        self.result = result

    async def get_route_candidates(self, origin: str, destination: str):
        return self.result


async def test_individual_tool_distinguishes_successful_empty_result() -> None:
    tools._facility_service = _FacilityServiceStub(
        ServiceResult(value=[], data_sources=[_source()])
    )

    result = await tools.get_accessible_restroom("삼성", "2")

    assert result.schema_version == 2
    assert result.status == ResponseStatus.SUCCESS
    assert result.outcome == LookupOutcome.EMPTY
    assert result.data == []
    assert result.failed_sources == []


async def test_individual_tool_preserves_full_failure_metadata() -> None:
    failed = FailedSource(source_name="elevator_status", reason="timeout")
    tools._facility_service = _FacilityServiceStub(
        ServiceResult(
            value=[],
            data_sources=[_source(source_name="elevator_status", success=False)],
            failed_sources=[failed],
            limitations=["승강기 실시간 상태를 확인하지 못했습니다."],
        )
    )

    result = await tools.get_elevator_status("삼성", "2")

    assert result.status == ResponseStatus.FAILED
    assert result.outcome == LookupOutcome.FAILED
    assert result.data == []
    assert result.failed_sources == [failed]
    assert result.limitations == ["승강기 실시간 상태를 확인하지 못했습니다."]


async def test_individual_tool_preserves_unsupported_coverage_metadata() -> None:
    coverage_note = "9호선 여의도역은 현재 데이터 제공 범위 밖입니다."
    tools._facility_service = _FacilityServiceStub(
        ServiceResult(
            value=[],
            data_sources=[
                _source(
                    source_name="restroom",
                    success=False,
                    coverage_status=SourceCoverageStatus.UNSUPPORTED,
                    coverage_note=coverage_note,
                )
            ],
            limitations=[coverage_note],
        )
    )

    result = await tools.get_accessible_restroom("9호선 여의도")

    assert result.status == ResponseStatus.PARTIAL
    assert result.outcome == LookupOutcome.UNSUPPORTED
    assert result.data_sources[0].coverage_note == coverage_note
    assert result.failed_sources == []


async def test_individual_tool_preserves_stale_fallback_data_and_failure() -> None:
    facility = AccessibleFacility(
        facility_id="EV-1",
        facility_name="엘리베이터",
        station_name="삼성",
        line="2",
        facility_type=FacilityType.ELEVATOR,
        status=FacilityStatus.AVAILABLE,
    )
    failed = FailedSource(source_name="elevator_status", reason="timeout")
    tools._facility_service = _FacilityServiceStub(
        ServiceResult(
            value=[facility],
            data_sources=[
                _source(
                    source_name="elevator_status",
                    success=False,
                    cache_status=CacheStatus.STALE,
                )
            ],
            failed_sources=[failed],
            limitations=["이전 캐시 응답을 사용했습니다."],
        )
    )

    result = await tools.get_elevator_status("삼성", "2")

    assert result.status == ResponseStatus.PARTIAL
    assert result.outcome == LookupOutcome.STALE
    assert result.data == [facility]
    assert result.data_sources[0].cache_status == CacheStatus.STALE
    assert result.failed_sources == [failed]


async def test_route_tool_preserves_failure_instead_of_returning_empty_list() -> None:
    failed = FailedSource(source_name="shortest_route", reason="timeout")
    tools._route_service = _RouteServiceStub(
        ServiceResult(
            value=[],
            data_sources=[_source(source_name="shortest_route", success=False)],
            failed_sources=[failed],
            limitations=["최단경로 후보 정보를 확인하지 못했습니다."],
        )
    )

    result = await tools.get_route_candidates("홍대입구", "삼성")

    assert result.schema_version == 2
    assert result.status == ResponseStatus.FAILED
    assert result.outcome == LookupOutcome.FAILED
    assert result.data == []
    assert result.failed_sources == [failed]


def _source(
    *,
    source_name: str = "facility_info",
    success: bool = True,
    cache_status: CacheStatus = CacheStatus.MISS,
    coverage_status: SourceCoverageStatus = SourceCoverageStatus.SUPPORTED,
    coverage_note: str | None = None,
) -> DataSourceMeta:
    return DataSourceMeta(
        source_name=source_name,
        source_type="public_api",
        fetched_at=CHECKED_AT,
        cache_status=cache_status,
        success=success,
        error_message=None if success else "request_failed",
        coverage_status=coverage_status,
        coverage_note=coverage_note,
    )
