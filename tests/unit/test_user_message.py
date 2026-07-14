from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.accessibility import (
    AccessibilityCheck,
    AccessibilityEvidenceStatus,
    AccessibilityResult,
    ElevatorEvidenceItem,
    FacilityAnswerState,
    MobilityProfile,
    RiskReason,
)
from app.schemas.common import ResponseStatus
from app.schemas.facility import AccessibleFacility, FacilityIssue, FacilityStatus, FacilityType
from app.schemas.route import RouteCandidate, RouteSegment
from app.services.user_message import build_user_message_context

USE_DEFAULT_ROUTE = object()


@pytest.mark.parametrize(
    ("risk_level", "expected_text"),
    [
        ("LOW", "현재 확인된 범위에서는 이용할 수 있습니다"),
        ("CAUTION", "이용 여부를 확정하기 어렵습니다"),
        ("HIGH", "이 경로 이용을 권장하지 않습니다"),
        ("UNKNOWN", "이용 여부를 판단할 수 없습니다"),
    ],
)
def test_user_message_headline_changes_by_risk_level(
    risk_level: str,
    expected_text: str,
) -> None:
    result = _result(risk_level=risk_level)

    context = build_user_message_context(result)

    assert expected_text in context["user_message"]


def test_failed_result_uses_judgement_difficult_tone() -> None:
    result = _result(status=ResponseStatus.FAILED, risk_level="UNKNOWN", selected_route=None)

    context = build_user_message_context(result)

    assert "이용 여부를 판단할 수 없습니다" in context["user_message"]
    assert (
        context["user_message_summary"].route_overview
        == "확인 가능한 경로 후보를 찾지 못했습니다."
    )


def test_user_message_hides_technical_terms() -> None:
    result = _result(risk_level="LOW")

    message = build_user_message_context(result)["user_message"]

    for term in ("risk_level", "confidence_level", "cache", "payload", "failed_sources"):
        assert term not in message
    assert "이동 가능성이 높습니다" not in message
    assert "예상" not in message


def test_user_message_uses_fixed_section_order_and_avoids_banned_claims() -> None:
    result = _result(risk_level="LOW")

    message = build_user_message_context(result)["user_message"]

    section_markers = [
        "확인 결과",
        "기준 시각",
        "주의사항",
    ]
    indexes = [message.index(marker) for marker in section_markers]
    assert indexes == sorted(indexes)
    for banned in ("안전하게 이동 가능합니다", "문제 없습니다", "반드시 이용 가능합니다"):
        assert banned not in message


def test_caution_message_gives_direct_decision_before_details() -> None:
    result = _result(risk_level="CAUTION")

    message = build_user_message_context(result)["user_message"]

    assert message.startswith("**출발 전에 확인이 필요합니다.**")
    summary = message.split("### 확인 결과", 1)[0]
    assert "이용 여부를 확정하기 어렵습니다" in summary
    assert "**지금 할 일:**" in summary


def test_user_message_prioritizes_structured_accessibility_checks() -> None:
    result = _result(risk_level="LOW")
    result.accessibility_checks = [
        AccessibilityCheck(
            station="홍대입구",
            line="2",
            role="origin",
            elevator_status=FacilityStatus.AVAILABLE,
            elevator_location="8번 출입구",
            station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            line_matched_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            platform_to_concourse_verified=AccessibilityEvidenceStatus.CONFIRMED,
            exit_elevator_verified=AccessibilityEvidenceStatus.CONFIRMED,
            status_verified=AccessibilityEvidenceStatus.CONFIRMED,
        ),
        AccessibilityCheck(
            station="삼성",
            line="2",
            role="destination",
            elevator_status=FacilityStatus.AVAILABLE,
            elevator_location="6번 출입구",
            station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            line_matched_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            platform_to_concourse_verified=AccessibilityEvidenceStatus.CONFIRMED,
            exit_elevator_verified=AccessibilityEvidenceStatus.CONFIRMED,
            status_verified=AccessibilityEvidenceStatus.CONFIRMED,
        ),
    ]

    message = build_user_message_context(result)["user_message"]

    assert message.startswith("**현재 확인된 범위에서는 이용할 수 있습니다.**")
    assert "| 역 | 확인된 정보 | 추가 확인 |" in message
    assert "| 출발역: 2호선 홍대입구역 |" in message
    assert "8번 출입구" in message
    assert "현재 운행 중" in message
    assert "승강장→대합실 연결 확인" in message
    assert "| 도착역: 2호선 삼성역 |" in message
    assert "6번 출입구" in message
    assert "### 추천 경로" not in message
    assert "홍대입구역 → 삼성역" not in message
    assert "### 사용자 조건 반영" not in message
    assert "**지금 할 일:**" in message
    assert "### 출발 전 확인" not in message
    assert "표에 적힌 개별 엘리베이터의 상태" not in message


def test_caution_message_distinguishes_operating_elevator_from_full_path() -> None:
    result = _result(risk_level="CAUTION")
    result.accessibility_checks = [
        AccessibilityCheck(
            station="홍대입구",
            line="2",
            role="origin",
            elevator_status=FacilityStatus.AVAILABLE,
            station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            line_matched_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            platform_to_concourse_verified=AccessibilityEvidenceStatus.UNVERIFIED,
            exit_elevator_verified=AccessibilityEvidenceStatus.CONFIRMED,
            status_verified=AccessibilityEvidenceStatus.CONFIRMED,
        ),
        AccessibilityCheck(
            station="삼성",
            line="2",
            role="destination",
            elevator_status=FacilityStatus.AVAILABLE,
            station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            line_matched_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            platform_to_concourse_verified=AccessibilityEvidenceStatus.UNVERIFIED,
            exit_elevator_verified=AccessibilityEvidenceStatus.CONFIRMED,
            status_verified=AccessibilityEvidenceStatus.CONFIRMED,
        ),
    ]

    message = build_user_message_context(result)["user_message"]

    headline = message.split("### 역별 확인 결과", 1)[0]
    assert headline.startswith("**출발 전에 확인이 필요합니다.**")
    assert "홍대입구역과 삼성역의 엘리베이터는 현재 운행 중" in headline
    assert "승강장에서 출구까지 엘리베이터만으로 이어지는지는" in headline
    assert "**지금 할 일:**" in headline


def test_user_message_does_not_repeat_full_mobility_profile() -> None:
    result = _result(
        risk_level="LOW",
        mobility_profile=MobilityProfile(
            wheelchair=True,
            stroller=True,
            can_use_stairs=False,
            can_use_escalator=False,
            need_elevator_only=True,
            need_accessible_restroom=True,
            max_transfer_count=1,
        ),
    )

    message = build_user_message_context(result)["user_message"]

    assert "휠체어: 사용" not in message
    assert "유모차: 사용" not in message
    assert "### 사용자 조건 반영" not in message


def test_user_message_uses_short_source_summary() -> None:
    result = _result(risk_level="LOW")
    result.evidence_sources = [
        _evidence("shortest_route"),
        _evidence("elevator_status"),
        _evidence("facility_info"),
    ]

    context = build_user_message_context(result)

    assert "최단경로 정보: 확인" in context["user_message_summary"].source_summary
    assert "엘리베이터 위치·운행상태: 확인" in context["user_message_summary"].source_summary
    assert "편의시설 정보: 확인" in context["user_message_summary"].source_summary
    assert "저상버스 등 지상 대체 경로는 포함하지 않았습니다" in (
        context["user_message_summary"].source_summary
    )
    assert "서울교통공사_최단경로이동정보" not in context["user_message"]


def test_user_message_includes_checked_time_when_available() -> None:
    result = _result(risk_level="LOW")
    checked_at = datetime(2026, 6, 9, 6, 25, tzinfo=UTC)
    result.last_checked_at = checked_at
    result.evidence_sources = [
        _evidence("shortest_route", checked_at=checked_at),
        _evidence("elevator_status", checked_at=checked_at),
    ]

    context = build_user_message_context(result)

    assert "전체 조회 시각: 2026년 6월 9일 15:25" in (
        context["user_message_summary"].source_summary
    )
    assert "최단경로 정보: 15:25 확인" in context["user_message"]
    assert "엘리베이터 위치·운행상태: 15:25 확인" in context["user_message"]


def test_restroom_missing_downgrades_user_judgement_to_caution() -> None:
    result = _result(
        risk_level="LOW",
        mobility_profile=MobilityProfile(
            wheelchair=True,
            need_accessible_restroom=True,
            can_use_stairs=False,
            can_use_escalator=False,
        ),
    )
    result.accessibility_checks = [
        AccessibilityCheck(
            station="홍대입구",
            role="origin",
            elevator_status=FacilityStatus.AVAILABLE,
            station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            platform_to_concourse_verified=AccessibilityEvidenceStatus.CONFIRMED,
            exit_elevator_verified=AccessibilityEvidenceStatus.CONFIRMED,
            status_verified=AccessibilityEvidenceStatus.CONFIRMED,
            restroom_available=False,
            restroom_required=True,
        ),
        AccessibilityCheck(
            station="삼성",
            role="destination",
            elevator_status=FacilityStatus.AVAILABLE,
            station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            platform_to_concourse_verified=AccessibilityEvidenceStatus.CONFIRMED,
            exit_elevator_verified=AccessibilityEvidenceStatus.CONFIRMED,
            status_verified=AccessibilityEvidenceStatus.CONFIRMED,
            restroom_available=True,
            restroom_required=True,
        ),
    ]

    message = build_user_message_context(result)["user_message"]

    assert "필수 장애인화장실 정보가 확인되지 않아" in message
    assert "장애인화장실 미확인(필수)" in message
    assert "| 출발역: 홍대입구역 |" in message
    assert "엘리베이터 있음" in message
    assert "장애인화장실 미확인(필수)" in message
    assert "| 도착역: 삼성역 |" in message
    assert "장애인화장실 확인(필수)" in message


def test_unknown_elevator_downgrades_user_judgement_to_caution() -> None:
    result = _result(risk_level="LOW", mobility_profile=MobilityProfile(wheelchair=True))
    result.accessibility_checks = [
        AccessibilityCheck(
            station="홍대입구",
            role="origin",
            elevator_status=FacilityStatus.UNKNOWN,
        ),
        AccessibilityCheck(
            station="삼성",
            role="destination",
            elevator_status=FacilityStatus.AVAILABLE,
        ),
    ]

    message = build_user_message_context(result)["user_message"]

    assert message.startswith("**출발 전에 확인이 필요합니다.**")
    assert "출발역: 홍대입구역" in message
    assert "| 출발역: 홍대입구역 | 확인된 항목 없음 |" in message
    assert "엘리베이터 정보 확인 불가" in message


@pytest.mark.parametrize(
    ("answer_state", "station_evidence", "expected", "not_expected"),
    [
        (
            FacilityAnswerState.NOT_FOUND,
            AccessibilityEvidenceStatus.FAILED,
            "공공데이터 조회 결과 엘리베이터 미확인",
            "현재 데이터 제공 범위 밖",
        ),
        (
            FacilityAnswerState.UNSUPPORTED,
            AccessibilityEvidenceStatus.UNVERIFIED,
            "현재 데이터 제공 범위 밖",
            "공공데이터 조회 결과 엘리베이터 미확인",
        ),
        (
            FacilityAnswerState.UNKNOWN,
            AccessibilityEvidenceStatus.UNVERIFIED,
            "엘리베이터 정보 확인 불가",
            "공공데이터 조회 결과 엘리베이터 미확인",
        ),
    ],
)
def test_user_message_distinguishes_empty_unsupported_and_unknown_elevator_data(
    answer_state: FacilityAnswerState,
    station_evidence: AccessibilityEvidenceStatus,
    expected: str,
    not_expected: str,
) -> None:
    result = _result(risk_level="CAUTION", mobility_profile=MobilityProfile(wheelchair=True))
    result.accessibility_checks = [
        AccessibilityCheck(
            station="홍대입구",
            role="origin",
            elevator_answer_state=answer_state,
            station_has_elevator=station_evidence,
        )
    ]

    message = build_user_message_context(result)["user_message"]

    assert expected in message
    assert not_expected not in message


def test_mixed_elevator_status_names_station_and_does_not_claim_all_operating() -> None:
    result = _result(risk_level="CAUTION", mobility_profile=MobilityProfile(wheelchair=True))
    result.accessibility_checks = [
        AccessibilityCheck(
            station="홍대입구",
            role="origin",
            elevator_status=FacilityStatus.UNKNOWN,
            elevator_answer_state=FacilityAnswerState.MIXED,
            station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            status_verified=AccessibilityEvidenceStatus.CONFIRMED,
        ),
        AccessibilityCheck(
            station="삼성",
            role="destination",
            elevator_status=FacilityStatus.AVAILABLE,
            elevator_answer_state=FacilityAnswerState.AVAILABLE,
            station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            status_verified=AccessibilityEvidenceStatus.CONFIRMED,
        ),
    ]

    message = build_user_message_context(result)["user_message"]

    assert "홍대입구역에서 엘리베이터 점검 또는 이용 제한" in message
    assert "운행상태: 일부 이용 가능, 일부 점검 또는 이용 불가" in message
    assert "현재 운행 중인 엘리베이터는" not in message


def test_mixed_elevator_details_show_restricted_and_available_locations() -> None:
    result = _result(risk_level="CAUTION", mobility_profile=MobilityProfile(wheelchair=True))
    result.accessibility_checks = [
        AccessibilityCheck(
            station="삼성",
            line="2",
            role="destination",
            elevator_status=FacilityStatus.UNKNOWN,
            elevator_answer_state=FacilityAnswerState.MIXED,
            elevator_location="4번 출입구",
            elevator_details=[
                _elevator_detail("1번 출입구", FacilityStatus.MAINTENANCE),
                _elevator_detail("4번 출입구", FacilityStatus.AVAILABLE),
                _elevator_detail("6번 출입구", FacilityStatus.AVAILABLE),
                _elevator_detail("8번 출입구", FacilityStatus.AVAILABLE),
                _elevator_detail("승강장 내부", FacilityStatus.AVAILABLE),
            ],
            station_has_elevator=AccessibilityEvidenceStatus.CONFIRMED,
            status_verified=AccessibilityEvidenceStatus.CONFIRMED,
            notes=["정상 운행과 점검 또는 이용불가 상태의 엘리베이터가 함께 있습니다."],
        )
    ]

    message = build_user_message_context(result)["user_message"]

    assert message.startswith("**출발 전에 확인이 필요합니다.**")
    assert "1번 출입구의 엘리베이터는 점검 또는 이용 제한 상태" in message
    assert "**지금 할 일:**" in message
    assert "삼성역 1번 출입구의 엘리베이터는 점검 또는 이용 제한 상태" in message
    assert "필요한 이동 동선과 연결되는지 출발 전에 확인하세요" in message
    assert "운행 중: 4번 출입구" in message
    assert "운행 중: 6번 출입구" in message
    assert "점검 중: 1번 출입구" in message
    assert "그 외 엘리베이터 2건은 상세 결과에서 확인" in message
    assert "정상 운행과 점검 또는 이용불가 상태" not in message
    assert "점검 또는 이용 제한 위치를 피하세요: 삼성역 1번 출입구" in message


def test_transfer_condition_reason_downgrades_user_judgement_to_caution() -> None:
    result = _result(
        risk_level="LOW",
        risk_reasons=[
            RiskReason(
                code="too_many_transfers",
                message="환승 제한 초과",
                score=30,
                severity="CAUTION",
            )
        ],
        mobility_profile=MobilityProfile(wheelchair=True, max_transfer_count=1),
    )

    message = build_user_message_context(result)["user_message"]

    assert message.startswith("**출발 전에 확인이 필요합니다.**")
    assert "환승이 많아 엘리베이터 동선 확인이 더 중요합니다" in message


def test_user_message_names_stations_with_and_without_elevator_info() -> None:
    result = _result(
        risk_level="HIGH",
        risk_reasons=[
            RiskReason(
                code="elevator_not_found",
                message="엘리베이터 정보 없음",
                score=30,
                severity="UNKNOWN",
                station_name="서강대",
            ),
            RiskReason(
                code="elevator_not_found",
                message="엘리베이터 정보 없음",
                score=30,
                severity="UNKNOWN",
                station_name="용산",
            ),
            RiskReason(
                code="transfer_required",
                message="환승 필요",
                score=10,
                severity="CAUTION",
            ),
        ],
        accessible_facilities=[
            AccessibleFacility(
                station_name="홍대입구",
                facility_type=FacilityType.ELEVATOR,
                status=FacilityStatus.AVAILABLE,
                location_description="8번 출입구",
            ),
            AccessibleFacility(
                station_name="삼성",
                facility_type=FacilityType.ELEVATOR,
                status=FacilityStatus.AVAILABLE,
                location_description="6번 출입구",
            ),
        ],
        selected_route=RouteCandidate(
            route_id="route-a",
            origin="홍대입구",
            destination="삼성",
            segments=[
                RouteSegment(from_station="홍대입구", to_station="삼성", line="2호선"),
            ],
            transfer_count=1,
            estimated_minutes=40,
            stations=["홍대입구", "서강대", "용산", "삼성"],
        ),
    )

    message = build_user_message_context(result)["user_message"]

    assert "엘리베이터 위치: 홍대입구(8번 출입구), 삼성(6번 출입구)" in message
    assert "엘리베이터 정보 미확인: 서강대, 용산" in message
    assert "일부 역의 엘리베이터 정보를 찾지 못했습니다" not in message


def test_user_message_does_not_list_every_available_elevator_station() -> None:
    result = _result(
        risk_level="LOW",
        accessible_facilities=[
            AccessibleFacility(
                station_name=station_name,
                facility_type=FacilityType.ELEVATOR,
                status=FacilityStatus.AVAILABLE,
                location_description=f"{station_name} 위치",
            )
            for station_name in ["홍대입구", "합정", "당산", "영등포구청", "삼성"]
        ],
        selected_route=RouteCandidate(
            route_id="route-a",
            origin="홍대입구",
            destination="삼성",
            segments=[
                RouteSegment(from_station="홍대입구", to_station="삼성", line="2호선"),
            ],
            transfer_count=0,
            estimated_minutes=42,
            stations=["홍대입구", "합정", "당산", "영등포구청", "삼성"],
        ),
    )

    message = build_user_message_context(result)["user_message"]

    assert "엘리베이터 위치: 홍대입구(홍대입구 위치), 삼성(삼성 위치)" in message
    assert "합정, 당산, 영등포구청" not in message
    assert "예상" not in message


def test_user_message_mentions_blocked_facility_and_notice() -> None:
    result = _result(
        risk_level="HIGH",
        blocked_facilities=[
            FacilityIssue(
                station_name="삼성",
                facility_type=FacilityType.ELEVATOR,
                status=FacilityStatus.MAINTENANCE,
                severity="HIGH",
                reason="점검 중",
            )
        ],
        risk_reasons=[
            RiskReason(
                code="elevator_unavailable",
                message="엘리베이터 이용 제한",
                score=50,
                severity="HIGH",
                station_name="삼성",
            )
        ],
    )

    message = build_user_message_context(result)["user_message"]

    assert "삼성" in message
    assert "엘리베이터 이용 제한: 삼성" in message
    assert "출발 직전 재확인" in message


def test_user_message_hides_sensitive_source_details_from_limitations() -> None:
    result = _result(risk_level="LOW")
    result.limitations = [
        "https://apis.data.go.kr/example?serviceKey=SECRET",
        "Authorization: Bearer SECRET",
    ]

    message = build_user_message_context(result)["user_message"]

    assert "https://apis.data.go.kr" not in message
    assert "serviceKey" not in message
    assert "Bearer SECRET" not in message
    assert "일부 출처 세부 정보는 보안상 표시하지 않았습니다" in message


def _result(
    *,
    status: ResponseStatus = ResponseStatus.SUCCESS,
    risk_level: str = "LOW",
    selected_route: RouteCandidate | None | object = USE_DEFAULT_ROUTE,
    blocked_facilities: list[FacilityIssue] | None = None,
    risk_reasons: list[RiskReason] | None = None,
    accessible_facilities: list[AccessibleFacility] | None = None,
    mobility_profile: MobilityProfile | None = None,
) -> AccessibilityResult:
    route = _route() if selected_route is USE_DEFAULT_ROUTE else selected_route
    return AccessibilityResult(
        status=status,
        origin="홍대입구",
        destination="삼성",
        mobility_profile=mobility_profile or MobilityProfile(wheelchair=True),
        risk_level=risk_level,
        risk_score=0 if risk_level == "LOW" else 50,
        route_summary="홍대입구에서 삼성까지 0회 환승 경로",
        selected_route=route,
        blocked_facilities=blocked_facilities or [],
        risk_reasons=risk_reasons or [],
        accessible_facilities=accessible_facilities
        or [
            AccessibleFacility(
                station_name="홍대입구",
                facility_type=FacilityType.ELEVATOR,
                status=FacilityStatus.AVAILABLE,
            )
        ],
    )


def _route() -> RouteCandidate:
    return RouteCandidate(
        route_id="route-a",
        origin="홍대입구",
        destination="삼성",
        segments=[
            RouteSegment(from_station="홍대입구", to_station="삼성", line="2호선"),
        ],
        transfer_count=0,
        estimated_minutes=42,
        stations=["홍대입구", "삼성"],
    )


def _evidence(source_name: str, *, checked_at: datetime | None = None):
    from app.schemas.accessibility import EvidenceSource
    from app.schemas.common import CacheStatus

    return EvidenceSource(
        source_name=source_name,
        display_name=source_name,
        source_type="public_api",
        checked_at=checked_at,
        cache_status=CacheStatus.MISS,
        success=True,
    )


def _elevator_detail(
    location: str,
    status: FacilityStatus,
) -> ElevatorEvidenceItem:
    return ElevatorEvidenceItem(
        facility_name=f"엘리베이터 {location}",
        location=location,
        status=status,
        status_verified=AccessibilityEvidenceStatus.CONFIRMED,
        status_source_name="elevator_status",
        location_source_name="elevator_status",
        match_method="same_record",
    )
