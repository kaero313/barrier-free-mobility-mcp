from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.common import (
    CacheStatus,
    DataSourceMeta,
    FailedSource,
    ResponseStatus,
    SourceCoverageStatus,
)
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.schemas.lookup import LookupOutcome
from app.services.lookup_result import (
    build_facility_lookup_result,
    classify_lookup_result,
)
from app.services.types import ServiceResult

CHECKED_AT = datetime(2026, 7, 13, 8, 30, tzinfo=UTC)


def _source(
    *,
    source_name: str = "facility_info",
    success: bool = True,
    cache_status: CacheStatus = CacheStatus.MISS,
    coverage_status: SourceCoverageStatus = SourceCoverageStatus.SUPPORTED,
) -> DataSourceMeta:
    return DataSourceMeta(
        source_name=source_name,
        source_type="public_api",
        fetched_at=CHECKED_AT,
        cache_status=cache_status,
        success=success,
        error_message=None if success else "request_failed",
        coverage_status=coverage_status,
    )


@pytest.mark.parametrize(
    ("service_result", "expected_status", "expected_outcome"),
    [
        (
            ServiceResult(value=["data"], data_sources=[_source()]),
            ResponseStatus.SUCCESS,
            LookupOutcome.DATA,
        ),
        (
            ServiceResult(value=[], data_sources=[_source()]),
            ResponseStatus.SUCCESS,
            LookupOutcome.EMPTY,
        ),
        (
            ServiceResult(
                value=[],
                data_sources=[_source(success=False)],
                failed_sources=[FailedSource(source_name="facility_info", reason="timeout")],
            ),
            ResponseStatus.FAILED,
            LookupOutcome.FAILED,
        ),
        (
            ServiceResult(
                value=[],
                data_sources=[
                    _source(
                        success=False,
                        coverage_status=SourceCoverageStatus.UNSUPPORTED,
                    )
                ],
            ),
            ResponseStatus.PARTIAL,
            LookupOutcome.UNSUPPORTED,
        ),
        (
            ServiceResult(
                value=["cached"],
                data_sources=[
                    _source(success=False, cache_status=CacheStatus.STALE)
                ],
                failed_sources=[FailedSource(source_name="facility_info", reason="timeout")],
            ),
            ResponseStatus.PARTIAL,
            LookupOutcome.STALE,
        ),
        (
            ServiceResult(
                value=["partial"],
                data_sources=[_source(), _source(source_name="elevator_info", success=False)],
                failed_sources=[FailedSource(source_name="elevator_info", reason="timeout")],
            ),
            ResponseStatus.PARTIAL,
            LookupOutcome.PARTIAL,
        ),
    ],
)
def test_classify_lookup_result_distinguishes_completeness_states(
    service_result: ServiceResult[list[str]],
    expected_status: ResponseStatus,
    expected_outcome: LookupOutcome,
) -> None:
    status, outcome = classify_lookup_result(service_result)

    assert status == expected_status
    assert outcome == expected_outcome


def test_facility_lookup_result_preserves_service_metadata_and_v1_data() -> None:
    facility = AccessibleFacility(
        facility_id="EV-1",
        facility_name="엘리베이터",
        station_name="삼성",
        line="2",
        facility_type=FacilityType.ELEVATOR,
        status=FacilityStatus.AVAILABLE,
    )
    failed = FailedSource(source_name="elevator_info", reason="timeout")
    service_result = ServiceResult(
        value=[facility],
        data_sources=[_source(), _source(source_name="elevator_info", success=False)],
        failed_sources=[failed],
        limitations=["엘리베이터 위치 정보 일부를 확인하지 못했습니다."],
    )

    result = build_facility_lookup_result(
        station="삼성",
        line="2",
        service_result=service_result,
    )

    assert result.schema_version == 2
    assert result.data == [facility]
    assert result.failed_sources == [failed]
    assert result.limitations == service_result.limitations
    assert result.status == ResponseStatus.PARTIAL
    assert result.outcome == LookupOutcome.PARTIAL
