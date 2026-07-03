from __future__ import annotations

from datetime import datetime

from app.schemas.accessibility import (
    AccessibilityQuestionResult,
    AccessibilityResult,
    MobilityProfile,
    UserMessageSummary,
)
from app.schemas.common import FailedSource, ResponseStatus
from scripts.evaluate_live_quality import (
    evaluate_user_message_quality,
    format_table,
    select_cases,
    summarize_error,
    summarize_response,
)


def fixture_data() -> dict:
    return {
        "required_sections": [
            "판단:",
            "이유",
            "추천 경로",
            "접근성 체크",
            "사용자 조건 반영",
            "기준 시각",
            "주의사항",
        ],
        "banned_phrases": ["안전하게 이동 가능합니다"],
        "cases": [
            {
                "name": "trip",
                "category": "trip_accessibility",
                "question": "q1",
                "execution": {"kind": "trip_brief"},
                "expectations": {},
            },
            {
                "name": "place",
                "category": "place_name",
                "question": "q2",
                "execution": {"kind": "future_natural_language"},
                "expectations": {
                    "future_reason": "place_candidate_clarification_supported"
                },
            },
            {
                "name": "facility",
                "category": "facility_status",
                "question": "q3",
                "execution": {"kind": "future_natural_language"},
                "expectations": {"future_reason": "requires_facility_question_routing"},
            },
        ],
    }


def complete_user_message() -> str:
    return "\n".join(
        [
            "판단: 가능",
            "",
            "이유",
            "- 엘리베이터 정보가 확인됐습니다.",
            "",
            "추천 경로",
            "홍대입구역 → 삼성역",
            "",
            "접근성 체크",
            "- 홍대입구역: 엘리베이터 확인",
            "",
            "사용자 조건 반영",
            "- 휠체어 이용 조건",
            "",
            "기준 시각",
            "- 전체 조회 시각: 2026년 7월 2일 12:00",
            "",
            "주의사항",
            "- 출발 직전 다시 확인하세요.",
        ]
    )


def test_select_cases_filters_basic_all_category_name_and_limit() -> None:
    data = fixture_data()

    assert [case["name"] for case in select_cases(data, case_set="basic")] == [
        "trip",
        "place",
    ]
    assert [case["name"] for case in select_cases(data, case_set="all")] == [
        "trip",
        "place",
        "facility",
    ]
    assert [
        case["name"]
        for case in select_cases(data, case_set="all", category="facility_status")
    ] == ["facility"]
    assert [
        case["name"] for case in select_cases(data, case_set="all", names={"place"})
    ] == ["place"]
    assert [case["name"] for case in select_cases(data, case_set="all", limit=1)] == [
        "trip"
    ]


def test_summarize_response_extracts_quality_fields_without_raw_payload() -> None:
    result = AccessibilityResult(
        status=ResponseStatus.SUCCESS,
        origin="홍대입구",
        destination="삼성",
        mobility_profile=MobilityProfile(wheelchair=True),
        risk_level="LOW",
        risk_score=10,
        route_summary="홍대입구역에서 삼성역",
        failed_sources=[FailedSource(source_name="facility_info", reason="timeout")],
        unverified_parts=["일부 정보 미확인"],
        last_checked_at=datetime(2026, 7, 2, 12, 0),
        user_message=complete_user_message(),
        user_message_summary=UserMessageSummary(judgement="가능"),
    )
    response = AccessibilityQuestionResult(
        question="휠체어로 홍대입구역에서 삼성역까지 갈 수 있어?",
        status=ResponseStatus.SUCCESS,
        result=result,
        user_message=result.user_message,
    )

    summary = summarize_response(
        {"name": "trip", "category": "trip_accessibility"},
        response,
        latency_ms=123,
        required_sections=fixture_data()["required_sections"],
        banned_phrases=fixture_data()["banned_phrases"],
    )

    assert summary.status == "SUCCESS"
    assert summary.risk_level == "LOW"
    assert summary.judgement == "가능"
    assert summary.payload_bytes > 0
    assert summary.failed_source_count == 1
    assert summary.unverified_count == 1
    assert summary.has_checked_at_section is True
    assert summary.has_notice_section is True
    assert summary.issues == []


def test_quality_check_reports_missing_sections_banned_terms_and_technical_terms() -> None:
    issues = evaluate_user_message_quality(
        "판단: 가능\n안전하게 이동 가능합니다\nrisk_level=LOW",
        required_sections=["판단:", "이유"],
        banned_phrases=["안전하게 이동 가능합니다"],
        require_full_sections=True,
    )

    assert "missing_section:이유" in issues
    assert "banned_phrase:안전하게 이동 가능합니다" in issues
    assert "technical_term:risk_level" in issues


def test_summarize_error_redacts_secret_like_error_text() -> None:
    marker = "PUBLIC_DATA" + "_SERVICE_KEY"
    summary = summarize_error(
        {"name": "trip", "category": "trip_accessibility"},
        RuntimeError(f"{marker}=real-secret-value"),
        latency_ms=1,
    )

    assert summary.status == "ERROR"
    assert summary.issues == ["exception"]
    assert "real-secret-value" not in str(summary)
    assert "[REDACTED]" in (summary.error or "")


def test_format_table_omits_issue_details_by_default() -> None:
    result = AccessibilityResult(
        origin="홍대입구",
        destination="삼성",
        mobility_profile=MobilityProfile(),
        risk_level="LOW",
        risk_score=10,
        route_summary="route",
        user_message=complete_user_message(),
        user_message_summary=UserMessageSummary(judgement="가능"),
    )
    response = AccessibilityQuestionResult(
        question="q",
        status=ResponseStatus.SUCCESS,
        result=result,
        user_message=result.user_message,
    )
    summary = summarize_response(
        {"name": "trip", "category": "trip_accessibility"},
        response,
        latency_ms=1,
        required_sections=fixture_data()["required_sections"],
        banned_phrases=fixture_data()["banned_phrases"],
    )

    table = format_table([summary])

    assert "trip" in table
    assert "payload" not in table
    assert "risk_level" not in table
