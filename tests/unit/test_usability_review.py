from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.accessibility import AccessibilityQuestionResult
from app.schemas.common import ResponseStatus
from scripts.generate_usability_review import (
    ReviewEntry,
    build_feedback_template,
    collect_review_entries,
    open_review_in_browser,
    render_review_markdown,
    sanitize_review_text,
    write_review_outputs,
)
from scripts.summarize_usability_feedback import (
    format_summary,
    summarize_feedback_documents,
    validation_error_locations,
)
from scripts.summarize_usability_feedback import (
    run_cli as run_summary_cli,
)
from scripts.usability_review_common import (
    ALLOWED_FEEDBACK_FLAGS,
    RATING_DIMENSIONS,
    ReviewFeedbackDocument,
    load_yaml_mapping,
    response_fingerprint,
    select_review_cases,
    validate_completed_feedback,
    validate_review_fixture,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REVIEW_CASE_FILE = PROJECT_ROOT / "tests" / "fixtures" / "usability_review_cases.yaml"
SOURCE_CASE_FILE = PROJECT_ROOT / "tests" / "fixtures" / "user_question_cases.yaml"


def _fixtures() -> tuple[dict, dict]:
    return load_yaml_mapping(REVIEW_CASE_FILE), load_yaml_mapping(SOURCE_CASE_FILE)


def _completed_document(
    *,
    fingerprint: str = "a" * 64,
    ratings: dict[str, int] | None = None,
    flags: list[str] | None = None,
    comment: str = "개인 의견은 집계에 포함하지 않음",
) -> ReviewFeedbackDocument:
    values = ratings or {
        "understandability": 5,
        "actionability": 4,
        "uncertainty_clarity": 3,
        "accessibility_relevance": 5,
        "brevity": 4,
    }
    return ReviewFeedbackDocument.model_validate(
        {
            "version": 1,
            "reviewer_id": "reviewer-01",
            "reviewed_at": "2026-07-10",
            "mode": "mock",
            "cases": [
                {
                    "case_name": "case-a",
                    "response_sha256": fingerprint,
                    "ratings": values,
                    "flags": flags or [],
                    "comment": comment,
                }
            ],
        }
    )


def test_usability_fixture_is_valid_and_covers_required_scenarios() -> None:
    fixture, source_fixture = _fixtures()

    assert validate_review_fixture(fixture, source_fixture) == []
    assert len(fixture["cases"]) >= 12
    assert set(fixture["rubric"]["dimensions"]) == set(RATING_DIMENSIONS)
    assert set(fixture["allowed_flags"]) == set(ALLOWED_FEEDBACK_FLAGS)

    names = {case["name"] for case in fixture["cases"]}
    assert "wheelchair_direct_route_review" in names
    assert "station_elevator_alternative_review" in names
    assert "ambiguous_place_review" in names
    assert "partial_elevator_source_failure_review" in names


def test_select_review_cases_filters_mode_set_category_name_and_limit() -> None:
    fixture, source_fixture = _fixtures()

    basic_mock = select_review_cases(
        fixture, source_fixture, mode="mock", case_set="basic"
    )
    basic_live = select_review_cases(
        fixture, source_fixture, mode="live", case_set="basic"
    )
    all_live = select_review_cases(
        fixture, source_fixture, mode="live", case_set="all"
    )
    partial = select_review_cases(
        fixture,
        source_fixture,
        mode="mock",
        case_set="all",
        category="partial_failure",
    )
    named = select_review_cases(
        fixture,
        source_fixture,
        mode="mock",
        case_set="all",
        names={"wheelchair_direct_route_review"},
        limit=1,
    )

    assert len(basic_mock) == 10
    assert len(basic_live) == 10
    assert all(case["name"] != "partial_elevator_source_failure_review" for case in all_live)
    assert [case["name"] for case in partial] == [
        "partial_elevator_source_failure_review"
    ]
    assert named[0]["question"].startswith("휠체어로 홍대입구역")


def test_sanitize_review_text_removes_secret_and_endpoint() -> None:
    text = sanitize_review_text(
        "PUBLIC_DATA_SERVICE_KEY=real-secret https://api.example.test/path"
    )

    assert "real-secret" not in text
    assert "api.example.test" not in text
    assert "[REDACTED]" in text
    assert "[내부 URL 제거]" in text


def test_response_fingerprint_ignores_lookup_time_but_not_message_changes() -> None:
    first = "전체 조회 시각: 2026년 7월 10일 12:13. 엘리베이터 확인."
    second = "전체 조회 시각: 2026년 7월 11일 09:45. 엘리베이터 확인."
    changed = "전체 조회 시각: 2026년 7월 11일 09:45. 엘리베이터 미확인."

    assert response_fingerprint(first) == response_fingerprint(second)
    assert response_fingerprint(first) != response_fingerprint(changed)


@pytest.mark.asyncio
async def test_collect_review_entries_uses_canonical_message_and_failure_profile() -> None:
    captured_failures: list[set[str]] = []

    class FakeService:
        async def answer_accessibility_question(
            self, question: str
        ) -> AccessibilityQuestionResult:
            return AccessibilityQuestionResult(
                question=question,
                status=ResponseStatus.PARTIAL,
                intent="facility_status",
                user_message="확인 결과: 일부 확인\n기준 시각\n주의사항",
            )

    def factory(mode: str, failure_sources: set[str]) -> FakeService:
        assert mode == "mock"
        captured_failures.append(failure_sources)
        return FakeService()

    entries = await collect_review_entries(
        [
            {
                "name": "partial",
                "category": "partial_failure",
                "persona": "검토자",
                "review_focus": ["실패와 부재 구분"],
                "question": "강남역 엘리베이터 상태 알려줘",
                "mock_failure_sources": ["elevator_status"],
            }
        ],
        mode="mock",
        service_factory=factory,
    )

    assert captured_failures == [{"elevator_status"}]
    assert entries[0].status == "PARTIAL"
    assert entries[0].user_message.startswith("확인 결과: 일부 확인")
    assert entries[0].response_sha256 == response_fingerprint(entries[0].user_message)


@pytest.mark.asyncio
async def test_mock_review_case_runs_without_live_api() -> None:
    fixture, source_fixture = _fixtures()
    cases = select_review_cases(
        fixture,
        source_fixture,
        mode="mock",
        case_set="all",
        names={"wheelchair_direct_route_review"},
    )

    entries = await collect_review_entries(cases, mode="mock")

    assert len(entries) == 1
    assert entries[0].status == "SUCCESS"
    assert "출발 전에 엘리베이터 연결 동선을 확인해 주세요" in entries[0].user_message
    assert len(entries[0].response_sha256) == 64


def test_markdown_and_feedback_template_include_review_contract(tmp_path: Path) -> None:
    entry = ReviewEntry(
        case_name="case-a",
        category="trip_accessibility",
        persona="휠체어 이용자",
        review_focus=["미확인 동선 구분"],
        question="질문",
        status="SUCCESS",
        user_message="판단: 주의 필요\n기준 시각\n주의사항",
        response_sha256="a" * 64,
    )
    generated_at = datetime(
        2026,
        7,
        10,
        12,
        0,
        tzinfo=timezone(timedelta(hours=9), name="KST"),
    )

    markdown = render_review_markdown(
        [entry], mode="mock", generated_at=generated_at
    )
    template = build_feedback_template([entry], mode="mock")
    packet_path, feedback_path, html_path = write_review_outputs(
        [entry],
        mode="mock",
        output_dir=tmp_path,
        generated_at=generated_at,
    )

    assert "### MCP 답변" in markdown
    assert "이해하기 쉬운가" in markdown
    assert "개인 식별 정보는 작성하지 마세요" in markdown
    assert template["cases"][0]["ratings"]["understandability"] is None
    assert packet_path.read_text(encoding="utf-8") == markdown
    assert "response_sha256" in feedback_path.read_text(encoding="utf-8")
    assert "<!doctype html>" in html_path.read_text(encoding="utf-8")


def test_open_review_in_browser_uses_local_file_uri(tmp_path: Path) -> None:
    html_path = tmp_path / "review.html"
    html_path.write_text("<!doctype html>", encoding="utf-8")
    opened: list[str] = []

    result = open_review_in_browser(
        html_path,
        opener=lambda url: opened.append(url) or True,
    )

    assert result is True
    assert opened == [html_path.resolve().as_uri()]


def test_feedback_schema_rejects_out_of_range_score_and_unknown_flag() -> None:
    payload = _completed_document().model_dump(mode="json")
    payload["cases"][0]["ratings"]["brevity"] = 6
    payload["cases"][0]["flags"] = ["unknown_flag"]

    with pytest.raises(ValidationError) as exc_info:
        ReviewFeedbackDocument.model_validate(payload)

    locations = validation_error_locations(exc_info.value)
    assert "cases.0.ratings.brevity" in locations
    assert "cases.0.flags" in locations


def test_incomplete_feedback_reports_missing_ratings() -> None:
    document = ReviewFeedbackDocument.model_validate(
        {
            "version": 1,
            "mode": "mock",
            "cases": [
                {
                    "case_name": "case-a",
                    "response_sha256": "a" * 64,
                    "ratings": {},
                }
            ],
        }
    )

    errors = validate_completed_feedback(document)

    assert errors
    assert "understandability" in errors[0]
    assert "brevity" in errors[0]


def test_feedback_summary_aggregates_scores_flags_and_response_versions() -> None:
    first = _completed_document(
        fingerprint="a" * 64,
        flags=["unclear_facility_location"],
    )
    second = _completed_document(
        fingerprint="b" * 64,
        ratings={
            "understandability": 3,
            "actionability": 4,
            "uncertainty_clarity": 5,
            "accessibility_relevance": 3,
            "brevity": 4,
        },
        flags=["unclear_facility_location", "route_details_over_accessibility"],
        comment="민감할 수 있는 자유 의견",
    )

    summary = summarize_feedback_documents([first, second])
    formatted = format_summary(summary)

    assert summary["review_document_count"] == 2
    assert summary["rating_averages"]["understandability"] == 4.0
    assert summary["below_target_counts"]["accessibility_relevance"] == 1
    assert summary["flag_counts"]["unclear_facility_location"] == 2
    assert summary["cases"][0]["response_variants"] == 2
    assert "민감할 수 있는 자유 의견" not in str(summary)
    assert "사용성 피드백 요약" in formatted


def test_summary_cli_accepts_completed_feedback_without_printing_comments(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = _completed_document(comment="집계 출력에서 제외할 자유 의견")
    path = tmp_path / "feedback.yaml"
    path.write_text(document.model_dump_json(indent=2), encoding="utf-8")

    exit_code = run_summary_cli(Namespace(paths=[path], json=False))
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "사용성 피드백 요약" in captured.out
    assert "집계 출력에서 제외할 자유 의견" not in captured.out


def test_summary_cli_reports_only_invalid_field_location(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "invalid-feedback.yaml"
    path.write_text(
        '{"version":1,"mode":"mock","cases":[{"case_name":"case-a",'
        '"response_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"ratings":{"understandability":9},"comment":"real-secret-value"}]}',
        encoding="utf-8",
    )

    exit_code = run_summary_cli(Namespace(paths=[path], json=False))
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "cases.0.ratings.understandability" in captured.err
    assert "real-secret-value" not in captured.err
