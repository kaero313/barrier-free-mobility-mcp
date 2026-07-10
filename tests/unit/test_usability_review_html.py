from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.security import redact_sensitive_text
from scripts.generate_usability_review import ReviewEntry
from scripts.usability_review_common import (
    ALLOWED_FEEDBACK_FLAGS,
    RATING_DIMENSIONS,
    ReviewFeedbackDocument,
)
from scripts.usability_review_html import (
    build_review_html_payload,
    decode_review_payload,
    encode_review_payload,
    extract_review_payload,
    render_review_html,
)

KST = timezone(timedelta(hours=9), name="KST")


def _entry(
    *,
    question: str = "휠체어로 홍대입구역에서 삼성역까지 갈 수 있어?",
    message: str = "판단: 주의 필요\n기준 시각\n주의사항",
) -> ReviewEntry:
    return ReviewEntry(
        case_name="wheelchair_direct_route_review",
        category="trip_accessibility",
        persona="휠체어 이용자",
        review_focus=["확인·미확인 정보 구분"],
        question=question,
        status="SUCCESS",
        user_message=message,
        response_sha256="a" * 64,
    )


def _generated_at() -> datetime:
    return datetime(2026, 7, 10, 13, 0, tzinfo=KST)


def test_html_payload_round_trip_preserves_review_contract() -> None:
    payload = build_review_html_payload([_entry()], mode="mock", generated_at=_generated_at())

    decoded = decode_review_payload(encode_review_payload(payload))

    assert decoded == payload
    assert [item["key"] for item in decoded["dimensions"]] == list(RATING_DIMENSIONS)
    assert [item["key"] for item in decoded["flags"]] == list(
        ALLOWED_FEEDBACK_FLAGS
    )
    assert decoded["cases"][0]["status_label"] == "정상 생성"


def test_html_keeps_untrusted_question_and_answer_out_of_executable_markup() -> None:
    question = '<img src=x onerror="alert(1)">'
    message = '</script><script>document.body.textContent="unsafe"</script>'

    html = render_review_html(
        [_entry(question=question, message=message)],
        mode="mock",
        generated_at=_generated_at(),
    )
    payload = extract_review_payload(html)

    assert question not in html
    assert message not in html
    assert payload["cases"][0]["question"] == question
    assert payload["cases"][0]["user_message"] == message
    assert ".innerHTML" not in html
    assert "textContent" in html


def test_html_blocks_network_access_and_has_no_external_assets() -> None:
    html = render_review_html([_entry()], mode="mock", generated_at=_generated_at())

    assert "connect-src 'none'" in html
    assert "object-src 'none'" in html
    assert "base-uri 'none'" in html
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html
    assert "https://" not in html
    assert "http://" not in html


def test_html_contains_accessible_review_controls_and_import_limits() -> None:
    html = render_review_html([_entry()], mode="mock", generated_at=_generated_at())

    for control_id in (
        'id="review-progress"',
        'id="case-jump"',
        'id="formatted-view"',
        'id="raw-view"',
        'id="answer-raw"',
        'id="rating-list"',
        'id="flags-section"',
        'id="comment"',
        'id="import-file"',
        'id="export-draft"',
        'id="export-complete"',
    ):
        assert control_id in html
    assert 'aria-live="polite"' in html
    assert 'input.type = "radio"' in html
    assert 'input.type = "checkbox"' in html
    assert "renderMarkdownMessage" in html
    assert 'document.createElement("table")' in html
    assert "elements.answerRaw.textContent" in html
    assert "MAX_IMPORT_BYTES = 1048576" in html
    assert "comment.length > 1000" in html
    assert "item.response_sha256 !== review.response_sha256" in html


def test_browser_export_shape_is_accepted_by_feedback_schema() -> None:
    payload = build_review_html_payload([_entry()], mode="mock", generated_at=_generated_at())
    case = payload["cases"][0]
    feedback = {
        "version": 1,
        "reviewer_id": "reviewer-01",
        "reviewed_at": "2026-07-10T04:00:00.000Z",
        "mode": payload["mode"],
        "cases": [
            {
                "case_name": case["case_name"],
                "response_sha256": case["response_sha256"],
                "ratings": {key: 4 for key in RATING_DIMENSIONS},
                "flags": ["unclear_facility_location"],
                "comment": "위치 설명을 더 구체적으로 보여주세요.",
            }
        ],
    }

    document = ReviewFeedbackDocument.model_validate(feedback)

    assert document.cases[0].ratings.understandability == 4
    assert document.cases[0].flags == ["unclear_facility_location"]


def test_rendered_html_does_not_expose_secret_after_entry_sanitization() -> None:
    secret_message = redact_sensitive_text("MCP_API_KEY=real-secret-value")
    html = render_review_html(
        [_entry(message=secret_message)],
        mode="mock",
        generated_at=_generated_at(),
    )

    assert "real-secret-value" not in html
    assert extract_review_payload(html)["cases"][0]["user_message"].endswith(
        "[REDACTED]"
    )
