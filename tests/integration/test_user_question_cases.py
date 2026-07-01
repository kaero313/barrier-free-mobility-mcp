from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.schemas.accessibility import MobilityProfile
from app.schemas.common import ResponseStatus
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
    assert "판단: 추가 정보 필요" in response.user_message
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
    assert "판단: 가능" in response.user_message
