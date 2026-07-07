from __future__ import annotations

import pytest

from app.engine.risk_alignment import align_risk_with_user_judgement
from app.schemas.accessibility import (
    AccessibilityCheck,
    AccessibilityEvidenceStatus,
    MobilityProfile,
    RiskReason,
)
from app.schemas.common import FailedSource, ResponseStatus
from app.schemas.facility import FacilityStatus


@pytest.mark.parametrize(
    "reason_code",
    [
        "transfer_required",
        "no_accessible_restroom_when_required",
        "elevator_unknown",
        "elevator_not_found",
        "stale_data",
    ],
)
def test_caution_reason_applies_caution_floor(reason_code: str) -> None:
    aligned = align_risk_with_user_judgement(
        risk_score=10,
        risk_level="LOW",
        risk_reasons=[
            RiskReason(
                code=reason_code,
                message=reason_code,
                score=10,
                severity="CAUTION",
            )
        ],
        failed_sources=[],
        accessibility_checks=[],
        mobility_profile=MobilityProfile(wheelchair=True),
        status=ResponseStatus.SUCCESS,
    )

    assert aligned.risk_level == "CAUTION"
    assert aligned.risk_score >= 35


def test_unknown_elevator_check_applies_caution_floor_when_elevator_required() -> None:
    aligned = align_risk_with_user_judgement(
        risk_score=0,
        risk_level="LOW",
        risk_reasons=[],
        failed_sources=[],
        accessibility_checks=[
            AccessibilityCheck(
                station="홍대입구",
                role="origin",
                elevator_status=FacilityStatus.UNKNOWN,
            )
        ],
        mobility_profile=MobilityProfile(wheelchair=True),
        status=ResponseStatus.SUCCESS,
    )

    assert aligned.risk_level == "CAUTION"
    assert aligned.risk_score == 35


def test_restroom_missing_check_applies_caution_floor_when_required() -> None:
    aligned = align_risk_with_user_judgement(
        risk_score=0,
        risk_level="LOW",
        risk_reasons=[],
        failed_sources=[],
        accessibility_checks=[
            AccessibilityCheck(
                station="홍대입구",
                role="origin",
                elevator_status=FacilityStatus.AVAILABLE,
                restroom_available=False,
                restroom_required=True,
            )
        ],
        mobility_profile=MobilityProfile(need_accessible_restroom=True),
        status=ResponseStatus.SUCCESS,
    )

    assert aligned.risk_level == "CAUTION"
    assert aligned.risk_score == 35


def test_unverified_required_path_evidence_applies_caution_floor() -> None:
    aligned = align_risk_with_user_judgement(
        risk_score=0,
        risk_level="LOW",
        risk_reasons=[],
        failed_sources=[],
        accessibility_checks=[
            AccessibilityCheck(
                station="삼성",
                role="destination",
                elevator_status=FacilityStatus.AVAILABLE,
                station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
                line_matched_elevator=AccessibilityEvidenceStatus.CONFIRMED,
                platform_to_concourse_verified=AccessibilityEvidenceStatus.UNVERIFIED,
                exit_elevator_verified=AccessibilityEvidenceStatus.CONFIRMED,
                status_verified=AccessibilityEvidenceStatus.CONFIRMED,
            )
        ],
        mobility_profile=MobilityProfile(wheelchair=True),
        status=ResponseStatus.SUCCESS,
    )

    assert aligned.risk_level == "CAUTION"
    assert aligned.risk_score == 35


def test_high_risk_is_not_downgraded_by_alignment() -> None:
    aligned = align_risk_with_user_judgement(
        risk_score=80,
        risk_level="HIGH",
        risk_reasons=[],
        failed_sources=[],
        accessibility_checks=[],
        mobility_profile=MobilityProfile(),
        status=ResponseStatus.SUCCESS,
    )

    assert aligned.risk_level == "HIGH"
    assert aligned.risk_score == 80


def test_critical_failed_source_keeps_unknown_priority() -> None:
    aligned = align_risk_with_user_judgement(
        risk_score=10,
        risk_level="LOW",
        risk_reasons=[
            RiskReason(
                code="transfer_required",
                message="환승 필요",
                score=10,
                severity="CAUTION",
            )
        ],
        failed_sources=[FailedSource(source_name="elevator_status", reason="timeout")],
        accessibility_checks=[],
        mobility_profile=MobilityProfile(wheelchair=True),
        status=ResponseStatus.PARTIAL,
    )

    assert aligned.risk_level == "UNKNOWN"
    assert aligned.risk_score == 10


def test_failed_or_clarification_status_keeps_unknown() -> None:
    aligned = align_risk_with_user_judgement(
        risk_score=25,
        risk_level="LOW",
        risk_reasons=[],
        failed_sources=[],
        accessibility_checks=[],
        mobility_profile=MobilityProfile(),
        status=ResponseStatus.NEEDS_CLARIFICATION,
    )

    assert aligned.risk_level == "UNKNOWN"
    assert aligned.risk_score == 25
