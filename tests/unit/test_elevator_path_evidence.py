from __future__ import annotations

from app.engine.elevator_path_evidence import evaluate_elevator_path_evidence
from app.schemas.accessibility import AccessibilityEvidenceStatus
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType


def test_explicit_platform_concourse_text_confirms_only_that_segment() -> None:
    evidence = evaluate_elevator_path_evidence(
        required=True,
        role="origin",
        station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
        facilities=[_elevator(location="2호선 대합실-승강장 연결")],
    )

    assert evidence.platform_to_concourse == AccessibilityEvidenceStatus.CONFIRMED
    assert evidence.transfer_path == AccessibilityEvidenceStatus.NOT_APPLICABLE
    assert evidence.exit_path == AccessibilityEvidenceStatus.UNVERIFIED


def test_separate_explicit_records_can_confirm_platform_and_exit_segments() -> None:
    evidence = evaluate_elevator_path_evidence(
        required=True,
        role="destination",
        station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
        facilities=[
            _elevator(location="대합실-승강장 연결"),
            _elevator(location="8번 출입구 외부"),
        ],
    )

    assert evidence.platform_to_concourse == AccessibilityEvidenceStatus.CONFIRMED
    assert evidence.exit_path == AccessibilityEvidenceStatus.CONFIRMED


def test_transfer_path_requires_explicit_transfer_text() -> None:
    unverified = evaluate_elevator_path_evidence(
        required=True,
        role="transfer",
        station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
        facilities=[_elevator(location="대합실-승강장 연결")],
    )
    confirmed = evaluate_elevator_path_evidence(
        required=True,
        role="transfer",
        station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
        facilities=[_elevator(location="2호선-3호선 환승 연결")],
    )

    assert unverified.transfer_path == AccessibilityEvidenceStatus.UNVERIFIED
    assert confirmed.transfer_path == AccessibilityEvidenceStatus.CONFIRMED
    assert confirmed.exit_path == AccessibilityEvidenceStatus.NOT_APPLICABLE


def test_floor_range_or_elevator_existence_does_not_invent_path_evidence() -> None:
    evidence = evaluate_elevator_path_evidence(
        required=True,
        role="origin",
        station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
        facilities=[_elevator(location="합정 방면 7-2", operation_section="B2-B1")],
    )

    assert evidence.platform_to_concourse == AccessibilityEvidenceStatus.UNVERIFIED
    assert evidence.exit_path == AccessibilityEvidenceStatus.UNVERIFIED


def test_failed_station_or_non_required_profile_uses_terminal_evidence_states() -> None:
    failed = evaluate_elevator_path_evidence(
        required=True,
        role="destination",
        station_has_elevator=AccessibilityEvidenceStatus.FAILED,
        facilities=[],
    )
    not_required = evaluate_elevator_path_evidence(
        required=False,
        role="transfer",
        station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
        facilities=[_elevator(location="환승 연결")],
    )

    assert failed.platform_to_concourse == AccessibilityEvidenceStatus.FAILED
    assert failed.exit_path == AccessibilityEvidenceStatus.FAILED
    assert (
        not_required.platform_to_concourse
        == AccessibilityEvidenceStatus.NOT_APPLICABLE
    )
    assert not_required.transfer_path == AccessibilityEvidenceStatus.NOT_APPLICABLE


def _elevator(
    *,
    location: str,
    operation_section: str | None = None,
) -> AccessibleFacility:
    return AccessibleFacility(
        station_name="홍대입구",
        line="2",
        facility_type=FacilityType.ELEVATOR,
        status=FacilityStatus.AVAILABLE,
        location_description=location,
        operation_section=operation_section,
        source_name="elevator_info",
    )
