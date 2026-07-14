from __future__ import annotations

from datetime import UTC, datetime

from app.engine.elevator_status import (
    align_elevator_answer_state_with_sources,
    summarize_elevator_status,
)
from app.normalizers.facility_identity import facility_record_identity
from app.schemas.accessibility import FacilityAnswerState
from app.schemas.common import DataSourceMeta, SourceCoverageStatus
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType


def test_static_elevator_info_does_not_claim_live_availability() -> None:
    summary = summarize_elevator_status(
        [_elevator("info-1", FacilityStatus.AVAILABLE, source="elevator_info")]
    )

    assert summary.answer_state == FacilityAnswerState.UNKNOWN
    assert summary.operational_facilities == ()


def test_operational_available_and_maintenance_are_mixed() -> None:
    summary = summarize_elevator_status(
        [
            _elevator("status-1", FacilityStatus.AVAILABLE),
            _elevator("status-2", FacilityStatus.MAINTENANCE),
        ]
    )

    assert summary.answer_state == FacilityAnswerState.MIXED
    assert [facility.facility_id for facility in summary.available] == ["status-1"]
    assert [facility.facility_id for facility in summary.maintenance] == ["status-2"]


def test_cross_source_records_are_preserved_for_evidence() -> None:
    status = _elevator("EL-1", FacilityStatus.AVAILABLE)
    info = _elevator("EL-1", FacilityStatus.AVAILABLE, source="elevator_info")

    assert facility_record_identity(status) != facility_record_identity(info)


def test_idless_records_with_different_locations_are_not_merged() -> None:
    first = _elevator(None, FacilityStatus.AVAILABLE, location="1번 출구")
    second = _elevator(None, FacilityStatus.AVAILABLE, location="8번 출구")

    summary = summarize_elevator_status([first, second])

    assert len(summary.operational_facilities) == 2


def test_empty_result_distinguishes_supported_unsupported_and_failed_sources() -> None:
    empty_state = FacilityAnswerState.NOT_FOUND

    supported = align_elevator_answer_state_with_sources(
        empty_state,
        [_source(success=True, coverage=SourceCoverageStatus.SUPPORTED)],
    )
    unsupported = align_elevator_answer_state_with_sources(
        empty_state,
        [_source(success=True, coverage=SourceCoverageStatus.UNSUPPORTED)],
    )
    failed = align_elevator_answer_state_with_sources(
        empty_state,
        [_source(success=False, coverage=SourceCoverageStatus.SUPPORTED)],
    )

    assert supported == FacilityAnswerState.NOT_FOUND
    assert unsupported == FacilityAnswerState.UNSUPPORTED
    assert failed == FacilityAnswerState.UNKNOWN


def test_partial_empty_result_does_not_claim_not_found() -> None:
    result = align_elevator_answer_state_with_sources(
        FacilityAnswerState.NOT_FOUND,
        [
            _source(success=True, coverage=SourceCoverageStatus.SUPPORTED),
            _source(success=False, coverage=SourceCoverageStatus.SUPPORTED),
        ],
    )

    assert result == FacilityAnswerState.UNKNOWN


def _elevator(
    facility_id: str | None,
    status: FacilityStatus,
    *,
    source: str = "elevator_status",
    location: str = "8번 출구",
) -> AccessibleFacility:
    return AccessibleFacility(
        facility_id=facility_id,
        facility_name="엘리베이터",
        station_name="홍대입구",
        line="2",
        facility_type=FacilityType.ELEVATOR,
        status=status,
        location_description=location,
        source_name=source,
    )


def _source(
    *,
    success: bool,
    coverage: SourceCoverageStatus,
) -> DataSourceMeta:
    return DataSourceMeta(
        source_name="elevator_status",
        source_type="public_api",
        fetched_at=datetime(2026, 7, 13, tzinfo=UTC),
        success=success,
        coverage_status=coverage,
    )
