from __future__ import annotations

from dataclasses import dataclass

from app.engine.mobility_profile import requires_elevator
from app.engine.risk_scoring import calculate_risk_level, clamp_score
from app.schemas.accessibility import (
    AccessibilityCheck,
    MobilityProfile,
    RiskLevel,
    RiskReason,
)
from app.schemas.common import FailedSource, ResponseStatus
from app.schemas.facility import FacilityStatus

CAUTION_REASON_CODES = {
    "transfer_required",
    "too_many_transfers",
    "no_accessible_restroom_when_required",
    "elevator_unknown",
    "elevator_not_found",
    "elevator_unavailable",
    "stale_data",
}
CAUTION_SCORE_FLOOR = 35


@dataclass(frozen=True)
class RiskAlignmentResult:
    risk_score: int
    risk_level: RiskLevel


def align_risk_with_user_judgement(
    *,
    risk_score: int,
    risk_level: RiskLevel,
    risk_reasons: list[RiskReason],
    failed_sources: list[FailedSource],
    accessibility_checks: list[AccessibilityCheck],
    mobility_profile: MobilityProfile,
    status: ResponseStatus,
) -> RiskAlignmentResult:
    if status in {ResponseStatus.FAILED, ResponseStatus.NEEDS_CLARIFICATION}:
        return RiskAlignmentResult(risk_score=clamp_score(risk_score), risk_level="UNKNOWN")

    calculated_level = calculate_risk_level(risk_score, failed_sources=failed_sources)
    if calculated_level == "UNKNOWN" or risk_level == "UNKNOWN":
        return RiskAlignmentResult(risk_score=clamp_score(risk_score), risk_level="UNKNOWN")

    aligned_score = clamp_score(risk_score)
    aligned_level = _max_risk_level(risk_level, calculated_level)
    if _requires_caution_floor(
        risk_reasons=risk_reasons,
        accessibility_checks=accessibility_checks,
        mobility_profile=mobility_profile,
    ):
        aligned_score = max(aligned_score, CAUTION_SCORE_FLOOR)
        aligned_level = _max_risk_level(aligned_level, "CAUTION")

    return RiskAlignmentResult(
        risk_score=clamp_score(aligned_score),
        risk_level=aligned_level,
    )


def _requires_caution_floor(
    *,
    risk_reasons: list[RiskReason],
    accessibility_checks: list[AccessibilityCheck],
    mobility_profile: MobilityProfile,
) -> bool:
    if any(reason.code in CAUTION_REASON_CODES for reason in risk_reasons):
        return True

    if requires_elevator(mobility_profile) and any(
        check.elevator_status == FacilityStatus.UNKNOWN for check in accessibility_checks
    ):
        return True

    return bool(
        mobility_profile.need_accessible_restroom
        and any(
            check.restroom_required is True and check.restroom_available is False
            for check in accessibility_checks
        )
    )


def _max_risk_level(left: RiskLevel, right: RiskLevel) -> RiskLevel:
    order: dict[RiskLevel, int] = {
        "LOW": 0,
        "CAUTION": 1,
        "HIGH": 2,
        "UNKNOWN": 3,
    }
    return left if order[left] >= order[right] else right
