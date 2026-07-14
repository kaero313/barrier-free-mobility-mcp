from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.accessibility import (
    AccessibilityCheck,
    AccessibilityResult,
    AlternativeRoute,
    FacilityAnswerState,
    FacilityQuestionItem,
    FacilityQuestionResult,
    MobilityProfile,
    UserMessageSummary,
)
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.schemas.route import RouteCandidate, RouteSegment
from app.services.alternative_message import (
    build_route_alternative_message,
    build_station_facility_alternative_message,
)


def test_station_alternative_lists_only_available_facilities_with_locations() -> None:
    available = _facility("A", FacilityStatus.AVAILABLE, "1번 출구")
    unavailable = _facility("B", FacilityStatus.MAINTENANCE, "2번 출구")
    unknown_location = _facility("C", FacilityStatus.AVAILABLE, None)
    result = FacilityQuestionResult(
        station_name="강남",
        line="2",
        items=[
            FacilityQuestionItem(
                facility_type=FacilityType.ELEVATOR,
                answer_state=FacilityAnswerState.MIXED,
                facilities=[available, unavailable, unknown_location],
            )
        ],
        last_checked_at=datetime(2026, 7, 10, 5, 30, tzinfo=UTC),
    )

    message = build_station_facility_alternative_message(result)

    assert "확인 결과: 대체 시설 확인" in message
    assert "1번 출구" in message
    assert "2번 출구" not in message.split("대체 가능한 시설", 1)[1]
    assert "위치가 없거나 상태가 미확인인 시설은 대안으로 추천하지 않았습니다" in message


def test_station_alternative_reports_no_confirmed_option_without_claiming_absence() -> None:
    result = FacilityQuestionResult(
        station_name="강남",
        line="2",
        items=[
            FacilityQuestionItem(
                facility_type=FacilityType.ELEVATOR,
                answer_state=FacilityAnswerState.UNKNOWN,
                facilities=[_facility("A", FacilityStatus.UNKNOWN, "1번 출구")],
            )
        ],
    )

    message = build_station_facility_alternative_message(result)

    assert "확인 결과: 확인된 대안 없음" in message
    assert "정상 상태와 위치가 모두 확인된 대체 시설이 없습니다" in message
    assert "엘리베이터가 없습니다" not in message


def test_route_alternative_message_uses_selected_route_and_other_candidates() -> None:
    selected = _route("selected", transfer_count=0)
    other = _route("other", transfer_count=1)
    result = AccessibilityResult(
        origin="홍대입구",
        destination="삼성",
        mobility_profile=MobilityProfile(
            wheelchair=True,
            can_use_stairs=False,
            need_elevator_only=True,
        ),
        risk_level="CAUTION",
        risk_score=35,
        route_summary="2호선 경로",
        selected_route=selected,
        alternatives=[
            AlternativeRoute(
                title="대안 경로 1",
                description="환승 경로",
                route=other,
                expected_risk_level="HIGH",
            )
        ],
        accessibility_checks=[
            AccessibilityCheck(
                station="홍대입구",
                role="origin",
                elevator_status=FacilityStatus.AVAILABLE,
                elevator_location="8번 출구",
            ),
            AccessibilityCheck(
                station="삼성",
                role="destination",
                elevator_status=FacilityStatus.AVAILABLE,
                elevator_location="6번 출구",
            ),
        ],
        user_message_summary=UserMessageSummary(
            recommended_route="홍대입구역 → 삼성역"
        ),
    )

    message = build_route_alternative_message(result)

    sections = [
        "판단:",
        "대안 요청 조건",
        "추천 대안",
        "접근성 근거",
        "다른 후보",
        "기준 시각",
        "주의사항",
    ]
    assert [message.index(section) for section in sections] == sorted(
        message.index(section) for section in sections
    )
    assert "판단: 주의가 필요한 대안" in message
    assert "홍대입구역 → 삼성역" in message
    assert "접근성 판단 어려움 큼" in message
    assert "risk_level" not in message


def test_high_risk_route_is_not_presented_as_recommended() -> None:
    result = AccessibilityResult(
        origin="홍대입구",
        destination="삼성",
        mobility_profile=MobilityProfile(wheelchair=True),
        risk_level="HIGH",
        risk_score=75,
        route_summary="확인 경로",
        selected_route=_route("selected", transfer_count=0),
    )

    message = build_route_alternative_message(result)

    assert "판단: 권장할 대안 없음" in message
    assert "검토 후보" in message
    assert "추천 경로로 단정하지 않습니다" in message


def _facility(
    facility_id: str,
    status: FacilityStatus,
    location: str | None,
) -> AccessibleFacility:
    return AccessibleFacility(
        facility_id=facility_id,
        station_name="강남",
        line="2",
        facility_type=FacilityType.ELEVATOR,
        status=status,
        location_description=location,
    )


def _route(route_id: str, transfer_count: int) -> RouteCandidate:
    return RouteCandidate(
        route_id=route_id,
        origin="홍대입구",
        destination="삼성",
        segments=[
            RouteSegment(
                from_station="홍대입구",
                to_station="삼성",
                line="2",
                transfer=transfer_count > 0,
            )
        ],
        stations=["홍대입구", "삼성"],
        transfer_count=transfer_count,
    )
