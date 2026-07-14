from __future__ import annotations

from app.engine.route_ranking import (
    RouteCandidateAssessment,
    build_alternative_routes,
    rank_route_candidate_assessments,
)
from app.schemas.common import ResponseStatus
from app.schemas.route import RouteCandidate, RouteSegment


def test_ranking_prefers_aligned_accessibility_risk_before_travel_time() -> None:
    fast_unknown = _assessment("fast-unknown", "UNKNOWN", 10, transfers=0, minutes=5)
    slow_caution = _assessment("slow-caution", "CAUTION", 35, transfers=1, minutes=30)

    ranked = rank_route_candidate_assessments([fast_unknown, slow_caution])

    assert [item.route.route_id for item in ranked] == ["slow-caution", "fast-unknown"]


def test_ranking_breaks_equal_risk_by_score_transfers_and_time() -> None:
    high_score = _assessment("high-score", "CAUTION", 50, transfers=0, minutes=5)
    more_transfers = _assessment("more-transfers", "CAUTION", 35, transfers=2, minutes=10)
    slower = _assessment("slower", "CAUTION", 35, transfers=1, minutes=30)
    faster = _assessment("faster", "CAUTION", 35, transfers=1, minutes=20)

    ranked = rank_route_candidate_assessments(
        [high_score, more_transfers, slower, faster]
    )

    assert [item.route.route_id for item in ranked] == [
        "faster",
        "slower",
        "more-transfers",
        "high-score",
    ]


def test_alternatives_use_aligned_candidate_risk_level() -> None:
    assessment = _assessment("alternative", "UNKNOWN", 35, transfers=1, minutes=20)

    alternatives = build_alternative_routes([assessment])

    assert alternatives[0].route == assessment.route
    assert alternatives[0].expected_risk_level == "UNKNOWN"


def _assessment(
    route_id: str,
    risk_level: str,
    risk_score: int,
    *,
    transfers: int,
    minutes: int,
) -> RouteCandidateAssessment:
    route = RouteCandidate(
        route_id=route_id,
        origin="홍대입구",
        destination="삼성",
        segments=[
            RouteSegment(
                from_station="홍대입구",
                to_station="삼성",
                line="2호선",
                transfer=transfers > 0,
            )
        ],
        transfer_count=transfers,
        estimated_minutes=minutes,
        stations=["홍대입구", "삼성"],
    )
    return RouteCandidateAssessment(
        route=route,
        status=ResponseStatus.SUCCESS,
        risk_score=risk_score,
        risk_level=risk_level,  # type: ignore[arg-type]
    )
