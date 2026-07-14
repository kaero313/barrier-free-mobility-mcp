from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.schemas.accessibility import FacilityAnswerState, MobilityProfile
from app.schemas.common import ResponseStatus
from app.schemas.facility import FacilityType

USER_QUESTION_CASES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "user_question_cases.yaml"
)

EXPECTED_SECTIONS = [
    "확인 결과",
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
VALID_EXECUTION_KINDS = {
    "trip_brief",
    "natural_language_question",
    "future_natural_language",
}
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
        elif case["execution"]["kind"] == "natural_language_question":
            _assert_natural_language_question_case(case)
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


def _assert_natural_language_question_case(case: dict[str, Any]) -> None:
    expectations = case["expectations"]

    ResponseStatus(expectations["status"])
    assert isinstance(expectations["clarification_needed"], bool)
    assert expectations["contains"]
    assert isinstance(expectations["not_contains"], list)
    if expectations.get("facility_type"):
        FacilityType(expectations["facility_type"])
    if expectations.get("answer_state"):
        FacilityAnswerState(expectations["answer_state"])
    if expectations.get("result_kind"):
        assert expectations["result_kind"] in {"trip", "facility"}
