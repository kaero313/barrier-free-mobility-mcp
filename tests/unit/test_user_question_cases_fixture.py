from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.schemas.accessibility import MobilityProfile
from app.schemas.common import ResponseStatus

USER_QUESTION_CASES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "user_question_cases.yaml"
)

EXPECTED_SECTIONS = [
    "판단:",
    "이유",
    "추천 경로",
    "접근성 체크",
    "사용자 조건 반영",
    "기준 시각",
    "주의사항",
]
EXPECTED_BANNED_PHRASES = {
    "안전하게 이동 가능합니다",
    "문제 없습니다",
    "반드시 이용 가능합니다",
}
VALID_CATEGORIES = {
    "trip_accessibility",
    "restroom_required",
    "elevator_issue",
    "ambiguous_station",
    "place_name",
    "facility_status",
    "alternative_request",
}
VALID_EXECUTION_KINDS = {"trip_brief", "future_natural_language"}
VALID_RISK_LEVELS = {"LOW", "CAUTION", "HIGH", "UNKNOWN"}
VALID_JUDGEMENTS = {"가능", "주의 필요", "권장하지 않음", "확인 불가", "추가 정보 필요"}


def _question_cases() -> dict[str, Any]:
    return yaml.safe_load(USER_QUESTION_CASES.read_text(encoding="utf-8"))


def test_user_question_cases_define_global_answer_contract() -> None:
    data = _question_cases()

    assert data["version"] == 1
    assert data["required_sections"] == EXPECTED_SECTIONS
    assert EXPECTED_BANNED_PHRASES.issubset(set(data["banned_phrases"]))
    assert len(data["cases"]) >= 20
    assert sum(
        case["execution"]["kind"] == "trip_brief" for case in data["cases"]
    ) >= 10


def test_user_question_case_names_and_questions_are_unique() -> None:
    cases = _question_cases()["cases"]

    names = [case["name"] for case in cases]
    questions = [case["question"] for case in cases]

    assert len(names) == len(set(names))
    assert len(questions) == len(set(questions))


def test_user_question_cases_have_expected_schema() -> None:
    for case in _question_cases()["cases"]:
        assert case["name"]
        assert case["category"] in VALID_CATEGORIES
        assert case["question"]
        assert case["execution"]["kind"] in VALID_EXECUTION_KINDS
        assert isinstance(case["expectations"], dict)

        if case["execution"]["kind"] == "trip_brief":
            _assert_trip_brief_case(case)
        else:
            _assert_future_natural_language_case(case)


def _assert_trip_brief_case(case: dict[str, Any]) -> None:
    execution = case["execution"]
    expectations = case["expectations"]

    assert execution["origin"]
    assert execution["destination"]
    MobilityProfile.model_validate(execution["mobility_profile"])

    ResponseStatus(expectations["status"])
    assert expectations["risk_level"] in VALID_RISK_LEVELS
    assert expectations["judgement"] in VALID_JUDGEMENTS
    assert isinstance(expectations["clarification_needed"], bool)
    assert expectations["contains"]
    assert expectations["not_contains"]


def _assert_future_natural_language_case(case: dict[str, Any]) -> None:
    execution = case["execution"]
    expectations = case["expectations"]

    assert execution["target_capability"] == "answer_accessibility_question"
    assert expectations["future_reason"]
    assert expectations["expected_behavior"]
    assert expectations["contains"]
