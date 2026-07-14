from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.accessibility import (
    AccessibilityCheck,
    AlternativeRoute,
    RiskLevel,
    RiskReason,
)
from app.schemas.common import DataSourceMeta, FailedSource, ResponseStatus
from app.schemas.facility import AccessibleFacility, FacilityIssue
from app.schemas.route import RouteCandidate


@dataclass
class RouteCandidateAssessment:
    """A route candidate after evidence collection and risk alignment."""

    route: RouteCandidate
    status: ResponseStatus
    risk_score: int
    risk_level: RiskLevel
    risk_reasons: list[RiskReason] = field(default_factory=list)
    caution_points: list[str] = field(default_factory=list)
    blocked_facilities: list[FacilityIssue] = field(default_factory=list)
    accessible_facilities: list[AccessibleFacility] = field(default_factory=list)
    accessibility_checks: list[AccessibilityCheck] = field(default_factory=list)
    data_sources: list[DataSourceMeta] = field(default_factory=list)
    failed_sources: list[FailedSource] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


_RISK_ORDER: dict[RiskLevel, int] = {
    "LOW": 0,
    "CAUTION": 1,
    "HIGH": 2,
    "UNKNOWN": 3,
}


def rank_route_candidate_assessments(
    assessments: list[RouteCandidateAssessment],
) -> list[RouteCandidateAssessment]:
    """Rank candidates only after every candidate has passed the same evaluation stage."""

    return sorted(
        assessments,
        key=lambda item: (
            _RISK_ORDER[item.risk_level],
            item.risk_score,
            item.route.transfer_count,
            item.route.estimated_minutes or 9999,
            item.route.route_id,
        ),
    )


def build_alternative_routes(
    assessments: list[RouteCandidateAssessment],
) -> list[AlternativeRoute]:
    """Expose aligned risk levels for candidates that were not selected."""

    return [
        AlternativeRoute(
            title=f"대안 경로 {index}",
            description=(
                assessment.route.raw_summary
                or (
                    f"{assessment.route.origin}에서 "
                    f"{assessment.route.destination}까지의 대안 경로입니다."
                )
            ),
            route=assessment.route,
            expected_risk_level=assessment.risk_level,
        )
        for index, assessment in enumerate(assessments, start=1)
    ]
