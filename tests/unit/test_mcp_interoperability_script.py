from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from scripts.check_mcp_interoperability import (
    ANSWER_POLICY_RESOURCE_URI,
    REQUIRED_PROMPTS,
    REQUIRED_TOOLS,
    ClientReport,
    ScenarioReport,
    _extract_structured_content,
    build_interoperability_report,
    compare_client_reports,
    render_text_report,
    summarize_tool_payload,
    validate_client_report,
)


def test_summarize_tool_payload_normalizes_checked_at_values() -> None:
    first = summarize_tool_payload(
        "natural_question",
        _wrapped_payload("2026년 7월 14일 09:30", "09:30"),
    )
    second = summarize_tool_payload(
        "natural_question",
        _wrapped_payload("2026년 7월 14일 10:45", "10:45"),
    )

    assert first.status == "SUCCESS"
    assert first.intent == "trip_accessibility"
    assert first.risk_level == "CAUTION"
    assert first.judgement == "주의 필요"
    assert first.message_sections == ["역별 확인 결과", "기준 시각", "주의사항"]
    assert first.stable_user_message_sha256 == second.stable_user_message_sha256


def test_validate_client_report_accepts_complete_contract() -> None:
    report = _client_report("fastmcp")

    assert validate_client_report(report) == []
    assert build_interoperability_report([report]).compatible is True


def test_validate_client_report_reports_missing_contract_and_bad_clarification() -> None:
    report = _client_report("fastmcp")
    clarification = replace(
        report.scenarios[-1],
        clarification_needed=False,
        question_count=2,
    )
    broken = replace(
        report,
        tools=[],
        prompts=[],
        resources=[],
        policy_contract_ok=False,
        scenarios=[*report.scenarios[:-1], clarification],
    )

    issues = validate_client_report(broken)

    assert any("missing tools" in issue for issue in issues)
    assert any("missing prompts" in issue for issue in issues)
    assert any("answer policy resource is missing" in issue for issue in issues)
    assert any("exactly one question" in issue for issue in issues)


def test_compare_client_reports_detects_structured_result_difference() -> None:
    baseline = _client_report("fastmcp")
    changed_scenario = replace(
        baseline.scenarios[0],
        stable_user_message_sha256="different",
    )
    changed = replace(
        baseline,
        client_name="mcp-python-sdk",
        scenarios=[changed_scenario, *baseline.scenarios[1:]],
    )

    issues = compare_client_reports([baseline, changed])

    assert issues == [
        "mcp-python-sdk: scenario 'natural_question' differs from fastmcp"
    ]


def test_text_report_contains_only_summary_metadata() -> None:
    report = build_interoperability_report(
        [_client_report("fastmcp"), _client_report("mcp-python-sdk")]
    )

    rendered = render_text_report(report)

    assert "MCP interoperability: PASS" in rendered
    assert "http://127.0.0.1" not in rendered
    assert "Bearer" not in rendered
    assert "secret-token" not in rendered


def test_extract_structured_content_supports_both_client_field_names() -> None:
    fastmcp_result = SimpleNamespace(structured_content={"status": "SUCCESS"})
    sdk_result = SimpleNamespace(structuredContent={"status": "SUCCESS"})

    assert _extract_structured_content(fastmcp_result) == {"status": "SUCCESS"}
    assert _extract_structured_content(sdk_result) == {"status": "SUCCESS"}


def _client_report(client_name: str) -> ClientReport:
    full_sections = ["역별 확인 결과", "기준 시각", "주의사항"]
    scenarios = [
        ScenarioReport(
            name="natural_question",
            status="SUCCESS",
            intent="trip_accessibility",
            risk_level="CAUTION",
            judgement="주의 필요",
            clarification_needed=False,
            question_count=0,
            has_user_message=True,
            message_sections=full_sections,
            stable_user_message_sha256="natural-hash",
        ),
        ScenarioReport(
            name="structured_trip",
            status="SUCCESS",
            intent=None,
            risk_level="CAUTION",
            judgement="주의 필요",
            clarification_needed=False,
            question_count=0,
            has_user_message=True,
            message_sections=full_sections,
            stable_user_message_sha256="structured-hash",
        ),
        ScenarioReport(
            name="clarification",
            status="NEEDS_CLARIFICATION",
            intent="trip_accessibility",
            risk_level=None,
            judgement=None,
            clarification_needed=True,
            question_count=1,
            has_user_message=True,
            message_sections=["확인 결과", "기준 시각", "주의사항"],
            stable_user_message_sha256="clarification-hash",
        ),
    ]
    return ClientReport(
        client_name=client_name,
        client_version="test-version",
        server_name="Barrier-Free Mobility MCP",
        tools=sorted(REQUIRED_TOOLS),
        prompts=sorted(REQUIRED_PROMPTS),
        resources=[ANSWER_POLICY_RESOURCE_URI],
        prompt_policy_sha256="policy-hash",
        resource_policy_sha256="policy-hash",
        policy_contract_ok=True,
        scenarios=scenarios,
    )


def _wrapped_payload(checked_at: str, time_only: str) -> dict:
    user_message = "\n".join(
        [
            "**출발 전에 확인이 필요합니다.**",
            "### 역별 확인 결과",
            "### 기준 시각",
            f"- 전체 조회 시각: {checked_at}",
            f"- 엘리베이터 위치·운행상태: {time_only} 확인",
            "### 주의사항",
        ]
    )
    return {
        "status": "SUCCESS",
        "intent": "trip_accessibility",
        "result": {
            "status": "SUCCESS",
            "risk_level": "CAUTION",
            "user_message": user_message,
            "user_message_summary": {"judgement": "주의 필요"},
        },
        "user_message": user_message,
        "clarification_needed": False,
        "questions": [],
    }
