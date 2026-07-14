from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.config import AppMode, Settings
from app.schemas.accessibility import FacilityAnswerState, MobilityProfile
from app.schemas.common import ResponseStatus
from app.schemas.facility import FacilityType
from app.services.accessibility_service import AccessibilityService

USER_QUESTION_CASES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "user_question_cases.yaml"
)
TECHNICAL_TERMS = ("risk_level", "confidence_level", "cache", "payload")


def _question_cases() -> dict[str, Any]:
    return yaml.safe_load(USER_QUESTION_CASES.read_text(encoding="utf-8"))


def _trip_brief_cases() -> list[dict[str, Any]]:
    return [
        case
        for case in _question_cases()["cases"]
        if case["execution"]["kind"] == "trip_brief"
    ]


def _natural_language_question_cases() -> list[dict[str, Any]]:
    return [
        case
        for case in _question_cases()["cases"]
        if case["execution"]["kind"] == "natural_language_question"
    ]


@pytest.mark.parametrize("case", _trip_brief_cases(), ids=lambda case: case["name"])
async def test_trip_brief_user_question_cases_match_expected_answer_contract(
    case: dict[str, Any],
) -> None:
    service = AccessibilityService()
    execution = case["execution"]
    expectations = case["expectations"]
    profile = MobilityProfile.model_validate(execution["mobility_profile"])

    result = await service.generate_accessibility_brief(
        execution["origin"],
        execution["destination"],
        profile,
    )

    assert result.status == ResponseStatus(expectations["status"])
    assert result.risk_level == expectations["risk_level"]
    assert result.user_message_summary.judgement == expectations["judgement"]
    assert result.clarification_needed is expectations["clarification_needed"]
    assert len(result.model_dump_json()) < 15000

    _assert_message_contract(
        message=result.user_message,
        data=_question_cases(),
        expectations=expectations,
    )

    reason_codes = {reason.code for reason in result.risk_reasons}
    for expected_code in expectations.get("risk_reason_codes", []):
        assert expected_code in reason_codes


@pytest.mark.parametrize("case", _trip_brief_cases(), ids=lambda case: case["name"])
async def test_natural_language_answer_tool_handles_user_question_cases(
    case: dict[str, Any],
) -> None:
    service = AccessibilityService()
    expectations = case["expectations"]

    response = await service.answer_accessibility_question(case["question"])

    assert response.status == ResponseStatus(expectations["status"])
    assert response.clarification_needed is expectations["clarification_needed"]
    assert response.user_message
    _assert_message_contract(
        message=response.user_message,
        data=_question_cases(),
        expectations=expectations,
    )

    if expectations["clarification_needed"]:
        assert response.result is None
        assert response.questions
        assert response.parsed.missing_fields
        return

    assert response.result is not None
    assert response.user_message == response.result.user_message
    assert response.result.risk_level == expectations["risk_level"]
    assert response.result.user_message_summary.judgement == expectations["judgement"]

    reason_codes = {reason.code for reason in response.result.risk_reasons}
    for expected_code in expectations.get("risk_reason_codes", []):
        assert expected_code in reason_codes


@pytest.mark.parametrize(
    "case",
    _natural_language_question_cases(),
    ids=lambda case: case["name"],
)
async def test_natural_language_facility_cases_match_expected_contract(
    case: dict[str, Any],
) -> None:
    service = AccessibilityService()
    expectations = case["expectations"]

    response = await service.answer_accessibility_question(case["question"])

    assert response.status == ResponseStatus(expectations["status"])
    assert response.clarification_needed is expectations["clarification_needed"]
    for expected_text in expectations["contains"]:
        assert expected_text in response.user_message
    for unexpected_text in expectations["not_contains"]:
        assert unexpected_text not in response.user_message
    for term in TECHNICAL_TERMS:
        assert term not in response.user_message

    if expectations.get("facility_type"):
        assert response.result is None
        assert response.facility_result is not None
        if case["category"] == "facility_status":
            assert response.user_message == response.facility_result.user_message
        else:
            assert response.user_message != response.facility_result.user_message
        item = response.facility_result.items[0]
        assert item.facility_type == FacilityType(expectations["facility_type"])
        assert item.answer_state == FacilityAnswerState(expectations["answer_state"])
    elif expectations.get("result_kind") == "trip":
        assert response.result is not None
        assert response.facility_result is None
        assert response.result.selected_route is not None
    else:
        assert response.facility_result is None
        assert response.questions


def _assert_message_contract(
    *,
    message: str,
    data: dict[str, Any],
    expectations: dict[str, Any],
) -> None:
    section_indexes = []
    for section in data["required_sections"]:
        assert section in message
        section_indexes.append(message.index(section))
    assert section_indexes == sorted(section_indexes)

    for phrase in data["banned_phrases"]:
        assert phrase not in message
    for term in TECHNICAL_TERMS:
        assert term not in message
    for expected_text in expectations["contains"]:
        assert expected_text in message
    for unexpected_text in expectations["not_contains"]:
        assert unexpected_text not in message


@pytest.mark.parametrize(
    ("question", "expected_texts"),
    [
        (
            "휠체어로 코엑스 갈 수 있어?",
            ["코엑스", "2호선 삼성역", "9호선 봉은사역", "어느 역을 기준"],
        ),
        (
            "홍대에서 코엑스 가는데 계단 못 써.",
            ["홍대입구", "코엑스", "2호선 삼성역", "9호선 봉은사역"],
        ),
        (
            "서울역 KTX에서 잠실까지 유모차로 갈만해?",
            ["서울역 KTX", "1호선 서울역", "4호선 서울역", "잠실"],
        ),
        (
            "DDP까지 휠체어로 갈 수 있어?",
            [
                "DDP",
                "2호선 동대문역사문화공원역",
                "4호선 동대문역사문화공원역",
                "5호선 동대문역사문화공원역",
            ],
        ),
    ],
)
async def test_natural_language_answer_tool_reports_place_candidates(
    question: str,
    expected_texts: list[str],
) -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(question)

    assert response.status == ResponseStatus.NEEDS_CLARIFICATION
    assert response.result is None
    assert response.clarification_needed is True
    assert response.questions
    assert response.parsed.place_mentions
    assert "한 가지만 더 알려주세요" in response.user_message
    assert len(response.questions) == 1
    for expected_text in expected_texts:
        assert expected_text in response.user_message
    for term in TECHNICAL_TERMS:
        assert term not in response.user_message


async def test_existing_station_based_natural_language_trip_still_succeeds() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "휠체어로 홍대입구역에서 삼성역까지 갈 수 있어?"
    )

    assert response.status == ResponseStatus.SUCCESS
    assert response.result is not None
    assert response.user_message == response.result.user_message
    assert response.user_message.startswith("**출발 전에 확인이 필요합니다.**")
    assert "연결 확인 필요" in response.user_message


async def test_natural_language_answer_tool_handles_elevator_status_question() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question("강남역 엘베 고장났어?")

    assert response.status == ResponseStatus.SUCCESS
    assert response.intent == "facility_status"
    assert response.result is None
    assert response.facility_result is not None
    assert response.user_message == response.facility_result.user_message
    assert response.parsed.target_station == "강남"
    assert response.parsed.target_line == "2"
    assert response.facility_result.items[0].answer_state == FacilityAnswerState.AVAILABLE
    assert "확인 결과: 정보 확인" in response.user_message
    assert "엘리베이터" in response.user_message
    assert "기준 시각" in response.user_message


async def test_natural_language_answer_tool_handles_accessible_restroom_location() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "2호선 삼성역 장애인화장실 어디 있어?"
    )

    assert response.status == ResponseStatus.SUCCESS
    assert response.facility_result is not None
    item = response.facility_result.items[0]
    assert item.facility_type == FacilityType.ACCESSIBLE_RESTROOM
    assert item.answer_state == FacilityAnswerState.AVAILABLE
    assert "개찰구 내부" in response.user_message
    assert "장애인화장실 정보" in response.user_message


async def test_successful_empty_restroom_query_does_not_claim_facility_absence() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "2호선 잠실역 장애인화장실 있어?"
    )

    assert response.status == ResponseStatus.SUCCESS
    assert response.facility_result is not None
    assert response.facility_result.items[0].answer_state == FacilityAnswerState.NOT_FOUND
    assert "현재 공공데이터에서 시설을 확인하지 못했습니다" in response.user_message
    assert "장애인화장실이 없습니다" not in response.user_message


async def test_facility_question_requires_line_for_ambiguous_station() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "고속터미널역 엘리베이터 상태 알려줘."
    )

    assert response.status == ResponseStatus.NEEDS_CLARIFICATION
    assert response.facility_result is None
    assert response.clarification_needed is True
    assert "한 가지만 더 알려주세요" in response.user_message
    assert len(response.questions) == 1
    assert "9호선 고속터미널" in response.user_message
    assert "호선" in response.questions[0]


async def test_generic_restroom_question_requests_accessible_restroom_confirmation() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "2호선 잠실역 화장실 어디 있어?"
    )

    assert response.status == ResponseStatus.NEEDS_CLARIFICATION
    assert response.facility_result is None
    assert response.questions == ["장애인화장실 정보를 확인할까요?"]
    assert "일반 화장실과 장애인화장실" in response.user_message


async def test_combined_facility_question_returns_both_items() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "2호선 삼성역 엘리베이터와 장애인화장실 위치 알려줘."
    )

    assert response.status == ResponseStatus.SUCCESS
    assert response.facility_result is not None
    assert [item.facility_type for item in response.facility_result.items] == [
        FacilityType.ELEVATOR,
        FacilityType.ACCESSIBLE_RESTROOM,
    ]
    assert "엘리베이터" in response.user_message
    assert "장애인화장실" in response.user_message


async def test_facility_question_preserves_partial_and_failed_source_metadata() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.MOCK,
        mock_failure_sources={"elevator_status"},
    )
    service = AccessibilityService(settings=settings)

    response = await service.answer_accessibility_question(
        "2호선 삼성역 엘리베이터 상태 알려줘."
    )

    assert response.status == ResponseStatus.PARTIAL
    assert response.facility_result is not None
    assert response.facility_result.items[0].answer_state == FacilityAnswerState.UNKNOWN
    assert any(
        source.source_name == "elevator_status"
        for source in response.facility_result.failed_sources
    )
    assert "운행 상태 미확인" in response.user_message
    assert "| 엘리베이터 | 6번 출입구 | 이용 가능 |" not in response.user_message
    assert "일부 데이터 출처" in response.user_message


async def test_facility_question_reports_failed_when_all_sources_fail() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.MOCK,
        mock_failure_sources={"elevator_status", "elevator_info"},
    )
    service = AccessibilityService(settings=settings)

    response = await service.answer_accessibility_question(
        "2호선 삼성역 엘리베이터 상태 알려줘."
    )

    assert response.status == ResponseStatus.FAILED
    assert response.facility_result is not None
    assert response.facility_result.items[0].answer_state == FacilityAnswerState.UNKNOWN
    assert len(response.facility_result.failed_sources) == 2
    assert "확인 결과: 확인 불가" in response.user_message


async def test_station_facility_alternative_uses_available_facility_results() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "강남역 엘베 고장났는데 대안 있어?"
    )

    assert response.status == ResponseStatus.SUCCESS
    assert response.intent == "alternative_request"
    assert response.result is None
    assert response.facility_result is not None
    assert "확인 결과: 현재 고장 정보 없음" in response.user_message
    assert "대체 가능한 시설" in response.user_message
    assert "대합실-승강장 연결" in response.user_message
    assert response.user_message != response.facility_result.user_message


async def test_station_facility_alternative_does_not_recommend_maintenance_only() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "4호선 동대문역사문화공원역 엘리베이터 고장 대안 있어?"
    )

    assert response.status == ResponseStatus.SUCCESS
    assert response.facility_result is not None
    assert response.facility_result.items[0].answer_state == FacilityAnswerState.MAINTENANCE
    assert "확인 결과: 확인된 대안 없음" in response.user_message
    assert "정상 상태와 위치가 모두 확인된 대체 시설이 없습니다" in response.user_message


async def test_station_facility_alternative_requires_line_for_ambiguous_station() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "고속터미널역에 다른 엘리베이터 있어?"
    )

    assert response.status == ResponseStatus.NEEDS_CLARIFICATION
    assert response.intent == "alternative_request"
    assert response.result is None
    assert response.facility_result is None
    assert response.clarification_needed is True
    assert "9호선 고속터미널" in response.user_message
    assert any("호선" in question for question in response.questions)


async def test_route_alternative_returns_accessibility_result_and_candidates() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "휠체어로 홍대입구에서 삼성까지 환승 적은 대안 경로 알려줘."
    )

    assert response.status == ResponseStatus.SUCCESS
    assert response.intent == "alternative_request"
    assert response.result is not None
    assert response.facility_result is None
    assert response.result.selected_route is not None
    assert response.result.alternatives
    assert "대안 요청 조건" in response.user_message
    assert "추천 대안" in response.user_message
    assert "다른 후보" in response.user_message
    assert "공공 API가 반환한 경로 후보 안에서만 비교" in response.user_message


async def test_route_alternative_infers_elevator_requirement() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "홍대입구에서 삼성까지 엘리베이터 고장난 역 피해서 갈 수 있어?"
    )

    assert response.result is not None
    assert response.result.mobility_profile.need_elevator_only is True
    assert "엘리베이터가 필요한 경로 조건" in response.user_message


async def test_unbound_route_alternative_requests_origin_and_destination() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "엘리베이터 고장난 역 피해서 갈 수 있어?"
    )

    assert response.status == ResponseStatus.NEEDS_CLARIFICATION
    assert response.result is None
    assert response.facility_result is None
    assert "출발역" in response.user_message
    assert "도착역" in response.user_message
    assert response.questions


async def test_current_route_alternative_does_not_assume_conversation_state() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "현재 경로에서 승강기 문제 있는 역 있어?"
    )

    assert response.status == ResponseStatus.NEEDS_CLARIFICATION
    assert "이전 대화의 경로를 저장하지 않습니다" in response.user_message
    assert "출발역" in response.questions[0]


async def test_route_alternative_without_mobility_condition_requests_profile() -> None:
    service = AccessibilityService()

    response = await service.answer_accessibility_question(
        "홍대입구에서 삼성까지 다른 경로 알려줘."
    )

    assert response.status == ResponseStatus.NEEDS_CLARIFICATION
    assert "이동 조건" in response.user_message
    assert any("휠체어" in question for question in response.questions)
