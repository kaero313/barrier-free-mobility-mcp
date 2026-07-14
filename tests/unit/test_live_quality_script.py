from __future__ import annotations

from datetime import datetime

from app.schemas.accessibility import (
    AccessibilityQuestionResult,
    AccessibilityResult,
    AlternativeRequestKind,
    FacilityAnswerState,
    FacilityQuestionItem,
    FacilityQuestionKind,
    FacilityQuestionResult,
    MobilityProfile,
    ParsedAccessibilityQuestion,
    UserMessageSummary,
)
from app.schemas.common import FailedSource, ResponseStatus
from app.schemas.facility import FacilityType
from scripts.evaluate_live_quality import (
    evaluate_user_message_quality,
    extract_judgement,
    format_table,
    select_cases,
    summarize_error,
    summarize_performance_pass,
    summarize_response,
)


def fixture_data() -> dict:
    return {
        "required_sections": [
            "확인 결과",
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
                "execution": {"kind": "natural_language_question"},
                "expectations": {},
            },
        ],
    }


def complete_user_message() -> str:
    return "\n".join(
        [
            "**현재 확인된 범위에서는 이용할 수 있습니다.**",
            "엘리베이터 점검 또는 이용 제한은 확인되지 않았습니다.",
            "**지금 할 일:** 출발 직전에 운행 상태를 확인하세요.",
            "",
            "### 역별 확인 결과",
            "| 역 | 확인된 정보 | 추가 확인 |",
            "|---|---|---|",
            "| 홍대입구역 | 엘리베이터 확인 | 추가 확인 항목 없음 |",
            "",
            "### 기준 시각",
            "- 전체 조회 시각: 2026년 7월 2일 12:00",
            "",
            "### 주의사항",
            "> 출발 직전 다시 확인하세요.",
        ]
    )


def test_select_cases_filters_basic_all_category_name_and_limit() -> None:
    data = fixture_data()

    assert [case["name"] for case in select_cases(data, case_set="basic")] == [
        "trip",
        "place",
        "facility",
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


def test_extract_judgement_understands_simplified_clarification_heading() -> None:
    response = AccessibilityQuestionResult(
        question="어디로 가야 해?",
        status=ResponseStatus.NEEDS_CLARIFICATION,
        user_message="**한 가지만 더 알려주세요.**\n**확인할 내용:** 출발역을 알려 주세요.",
        clarification_needed=True,
    )

    assert extract_judgement(response) == "추가 정보 필요"


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


def test_summarize_facility_response_uses_facility_contract() -> None:
    message = "\n".join(
        [
            "**확인 결과: 정보 확인**",
            "",
            "### 역·호선",
            "- 2호선 강남역",
            "",
            "### 시설 정보",
            "| 시설 | 위치 | 상태 |",
            "|---|---|---|",
            "| 엘리베이터 | 1번 출구 | 이용 가능 |",
            "",
            "### 기준 시각",
            "- 전체 조회 시각: 2026년 7월 10일 12:00.",
            "",
            "### 주의사항",
            "> 출발 직전에 재확인하세요.",
        ]
    )
    facility_result = FacilityQuestionResult(
        station_name="강남",
        line="2",
        question_kind=FacilityQuestionKind.STATUS,
        items=[
            FacilityQuestionItem(
                facility_type=FacilityType.ELEVATOR,
                answer_state=FacilityAnswerState.AVAILABLE,
            )
        ],
        user_message=message,
    )
    response = AccessibilityQuestionResult(
        question="강남역 엘리베이터 상태 알려줘",
        status=ResponseStatus.SUCCESS,
        intent="facility_status",
        facility_result=facility_result,
        user_message=message,
    )

    summary = summarize_response(
        {"name": "facility", "category": "facility_status"},
        response,
        latency_ms=10,
        required_sections=fixture_data()["required_sections"],
        banned_phrases=fixture_data()["banned_phrases"],
    )

    assert summary.risk_level == "N/A"
    assert summary.judgement == "정보 확인"
    assert summary.has_checked_at_section is True
    assert summary.has_notice_section is True
    assert summary.issues == []


def test_summarize_station_alternative_uses_alternative_contract() -> None:
    message = "\n".join(
        [
            "확인 결과: 대체 시설 확인",
            "",
            "역·호선",
            "- 2호선 강남역",
            "",
            "현재 시설 상태",
            "- 요청한 엘리베이터는 점검 중입니다.",
            "",
            "대체 가능한 시설",
            "- 3번 출구 방향 엘리베이터: 이용 가능.",
            "",
            "기준 시각",
            "- 전체 조회 시각: 2026년 7월 10일 12:00.",
            "",
            "한계·주의사항",
            "- 승강기 상태는 출발 직전에 다시 확인하세요.",
        ]
    )
    facility_result = FacilityQuestionResult(
        station_name="강남",
        line="2",
        question_kind=FacilityQuestionKind.STATUS,
        items=[
            FacilityQuestionItem(
                facility_type=FacilityType.ELEVATOR,
                answer_state=FacilityAnswerState.MIXED,
            )
        ],
        user_message="기존 시설 조회 답변",
    )
    response = AccessibilityQuestionResult(
        question="강남역 엘리베이터 고장났는데 대안 있어?",
        status=ResponseStatus.SUCCESS,
        intent="alternative_request",
        parsed=ParsedAccessibilityQuestion(
            alternative_request_kind=AlternativeRequestKind.STATION_FACILITY
        ),
        facility_result=facility_result,
        user_message=message,
    )

    summary = summarize_response(
        {"name": "alternative", "category": "alternative_request"},
        response,
        latency_ms=10,
        required_sections=fixture_data()["required_sections"],
        banned_phrases=fixture_data()["banned_phrases"],
    )

    assert summary.status == "SUCCESS"
    assert summary.judgement == "대체 시설 확인"
    assert summary.has_checked_at_section is True
    assert summary.has_notice_section is True
    assert summary.issues == []


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


def test_performance_summary_reports_only_current_pass_deltas() -> None:
    summary = summarize_performance_pass(
        "warm",
        elapsed_seconds=0.125,
        before={
            "public_api_call_count": 5,
            "public_api_error_count": 1,
            "cache": {"HIT": 2, "MISS": 3, "STALE": 0},
        },
        after={
            "public_api_call_count": 5,
            "public_api_error_count": 1,
            "cache": {"HIT": 8, "MISS": 3, "STALE": 1},
        },
    )

    assert summary.label == "warm"
    assert summary.total_latency_ms == 125
    assert summary.public_api_call_count == 0
    assert summary.cache_hit_count == 6
    assert summary.cache_miss_count == 0
    assert summary.cache_stale_count == 1
