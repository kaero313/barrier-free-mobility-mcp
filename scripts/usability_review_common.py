from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

RATING_DIMENSIONS = (
    "understandability",
    "actionability",
    "uncertainty_clarity",
    "accessibility_relevance",
    "brevity",
)

ALLOWED_FEEDBACK_FLAGS = (
    "unsafe_certainty",
    "missing_station_name",
    "unclear_facility_location",
    "unclear_source_or_time",
    "route_details_over_accessibility",
    "unclear_clarification_question",
)

STATUS_LABELS = {
    "SUCCESS": "정상 생성",
    "PARTIAL": "일부 정보로 생성",
    "FAILED": "생성 실패",
    "NEEDS_CLARIFICATION": "추가 정보 필요",
    "ERROR": "실행 오류",
}

RATING_LABELS = {
    "understandability": "이해하기 쉬운가",
    "actionability": "실제 행동 결정에 도움이 되는가",
    "uncertainty_clarity": "확인·미확인 정보가 구분되는가",
    "accessibility_relevance": "교통약자 접근성 정보가 중심인가",
    "brevity": "불필요하게 길지 않은가",
}

FLAG_LABELS = {
    "unsafe_certainty": "위험하게 단정적인 표현이 있음",
    "missing_station_name": "필요한 역명이 누락됨",
    "unclear_facility_location": "시설 위치가 불명확함",
    "unclear_source_or_time": "출처 또는 조회 시각이 불명확함",
    "route_details_over_accessibility": "길찾기 정보가 접근성 정보보다 과도함",
    "unclear_clarification_question": "추가 질문이 이해하기 어려움",
}

FINGERPRINT_TIME_PATTERNS = (
    re.compile(r"20\d{2}년\s*\d{1,2}월\s*\d{1,2}일\s*\d{1,2}:\d{2}"),
    re.compile(r"20\d{2}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?"),
    re.compile(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)"),
)


class ReviewRatings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    understandability: int | None = Field(default=None, ge=1, le=5)
    actionability: int | None = Field(default=None, ge=1, le=5)
    uncertainty_clarity: int | None = Field(default=None, ge=1, le=5)
    accessibility_relevance: int | None = Field(default=None, ge=1, le=5)
    brevity: int | None = Field(default=None, ge=1, le=5)


class ReviewCaseFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_name: str = Field(min_length=1)
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ratings: ReviewRatings = Field(default_factory=ReviewRatings)
    flags: list[str] = Field(default_factory=list)
    comment: str = ""

    @field_validator("flags")
    @classmethod
    def validate_flags(cls, flags: list[str]) -> list[str]:
        unknown = sorted(set(flags) - set(ALLOWED_FEEDBACK_FLAGS))
        if unknown:
            raise ValueError(f"unsupported feedback flags: {', '.join(unknown)}")
        return list(dict.fromkeys(flags))


class ReviewFeedbackDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    reviewer_id: str = ""
    reviewed_at: str | None = None
    mode: Literal["mock", "live"]
    cases: list[ReviewCaseFeedback] = Field(default_factory=list)


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML root must be an object: {path}")
    return payload


def validate_review_fixture(
    fixture: dict[str, Any],
    source_fixture: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if fixture.get("version") != 1:
        errors.append("version must be 1")

    rubric = fixture.get("rubric", {})
    dimensions = rubric.get("dimensions", {}) if isinstance(rubric, dict) else {}
    missing_dimensions = sorted(set(RATING_DIMENSIONS) - set(dimensions))
    if missing_dimensions:
        errors.append(f"missing rubric dimensions: {', '.join(missing_dimensions)}")

    configured_flags = fixture.get("allowed_flags", [])
    if set(configured_flags) != set(ALLOWED_FEEDBACK_FLAGS):
        errors.append("allowed_flags must match the supported feedback flag contract")

    source_names = {
        case.get("name")
        for case in source_fixture.get("cases", [])
        if isinstance(case, dict)
    }
    cases = fixture.get("cases", [])
    if not isinstance(cases, list) or len(cases) < 12:
        errors.append("at least 12 usability review cases are required")
        return errors

    seen_names: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"case[{index}] must be an object")
            continue
        name = str(case.get("name", "")).strip()
        label = name or f"case[{index}]"
        if not name:
            errors.append(f"case[{index}] is missing name")
        elif name in seen_names:
            errors.append(f"duplicate case name: {name}")
        seen_names.add(name)

        source_case = case.get("source_case")
        question = str(case.get("question", "")).strip()
        if bool(source_case) == bool(question):
            errors.append(f"{label}: set exactly one of source_case or question")
        if source_case and source_case not in source_names:
            errors.append(f"{label}: unknown source_case {source_case}")
        if not str(case.get("persona", "")).strip():
            errors.append(f"{label}: persona is required")
        if not case.get("review_focus"):
            errors.append(f"{label}: review_focus is required")

        modes = case.get("modes", [])
        if not modes or set(modes) - {"mock", "live"}:
            errors.append(f"{label}: modes must contain mock or live")
        if case.get("mock_failure_sources") and modes != ["mock"]:
            errors.append(f"{label}: simulated failures must be mock-only")
    return errors


def select_review_cases(
    fixture: dict[str, Any],
    source_fixture: dict[str, Any],
    *,
    mode: str,
    case_set: str = "basic",
    category: str | None = None,
    names: set[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if mode not in {"mock", "live"}:
        raise ValueError(f"unsupported review mode: {mode}")
    if case_set not in {"basic", "all"}:
        raise ValueError(f"unsupported case set: {case_set}")
    if limit is not None and limit < 0:
        raise ValueError("limit must be greater than or equal to 0")

    source_by_name = {
        case["name"]: case
        for case in source_fixture.get("cases", [])
        if isinstance(case, dict) and case.get("name")
    }
    selected: list[dict[str, Any]] = []
    for review_case in fixture.get("cases", []):
        if mode not in review_case.get("modes", []):
            continue
        if case_set == "basic" and not review_case.get("basic", False):
            continue
        if names and review_case.get("name") not in names:
            continue

        resolved = dict(review_case)
        source_name = resolved.get("source_case")
        if source_name:
            source = source_by_name[source_name]
            resolved["question"] = source["question"]
            resolved.setdefault("category", source.get("category", "unknown"))
        if category and resolved.get("category") != category:
            continue
        selected.append(resolved)

    if limit is not None:
        selected = selected[:limit]
    return selected


def response_fingerprint(user_message: str) -> str:
    normalized = user_message
    for pattern in FINGERPRINT_TIME_PATTERNS:
        normalized = pattern.sub("<checked-at>", normalized)
    return sha256(normalized.encode("utf-8")).hexdigest()


def load_feedback_document(path: Path) -> ReviewFeedbackDocument:
    return ReviewFeedbackDocument.model_validate(load_yaml_mapping(path))


def validate_completed_feedback(document: ReviewFeedbackDocument) -> list[str]:
    errors: list[str] = []
    if not document.cases:
        return ["feedback document has no cases"]
    for case in document.cases:
        ratings = case.ratings.model_dump()
        missing = [name for name, value in ratings.items() if value is None]
        if missing:
            errors.append(f"{case.case_name}: missing ratings: {', '.join(missing)}")
    return errors
