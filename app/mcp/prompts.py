from __future__ import annotations

from typing import Any

ANSWER_POLICY_RESOURCE_URI = "barrier-free://answer-policy"

ANSWER_POLICY_TEXT = "\n".join(
    [
        "Barrier-Free Mobility MCP answer policy:",
        "- For ordinary Korean end-user questions, call answer_accessibility_question first.",
        (
            "- If origin, destination, and mobility_profile are already structured, "
            "call generate_accessibility_brief."
        ),
        "- The canonical final answer is the tool result field user_message.",
        "- Return user_message verbatim to the user whenever possible.",
        (
            "- Do not prepend a separate route summary or judgement. The opening of "
            "user_message already contains the current conclusion and the first action."
        ),
        (
            "- Preserve Markdown headings, lists, blockquotes, and compact tables from "
            "user_message. Do not wrap the answer in a code block."
        ),
        (
            "- For station elevator or accessible-restroom questions, use "
            "facility_result as structured evidence and keep its 확인 결과, location, "
            "status, source timing, and notice sections."
        ),
        (
            "- For alternative_request results, the top-level user_message is canonical. "
            "Use result for route evidence or facility_result for same-station facility "
            "evidence; do not assume previous conversation routes are stored."
        ),
        (
            "- Do not rewrite the judgement, route, accessibility checks, source timing, "
            "or safety notice unless the user explicitly asks for a shorter summary."
        ),
        "- If clarification_needed is true, ask only the single question in questions[0].",
        (
            '- Do not claim safety is guaranteed. Avoid phrases like "안전하게 이동 가능합니다", '
            '"문제 없습니다", or "반드시 이용 가능합니다".'
        ),
        (
            "- Do not expose risk_score, risk_level, confidence_level, cache metadata, "
            "endpoint URLs, raw request parameters, API keys, service keys, or bearer "
            "tokens to ordinary users."
        ),
        (
            "- If extra explanation is needed, use result or facility_result plus "
            "accessibility_checks, evidence_sources, failed_sources, limitations, and "
            "user_message_summary as supporting evidence."
        ),
        "- Keep the 기준 시각 and source status from user_message when answering.",
    ]
)


def accessibility_brief_prompt() -> str:
    return ANSWER_POLICY_TEXT


def wheelchair_trip_check_prompt() -> str:
    return (
        ANSWER_POLICY_TEXT
        + "\n휠체어 사용자 질문에서는 엘리베이터 확인 여부, 환승역 엘리베이터 동선, "
        "계단/에스컬레이터 이용 불가 조건을 우선 확인하세요."
    )


def stroller_trip_check_prompt() -> str:
    return (
        ANSWER_POLICY_TEXT
        + "\n유모차 사용자 질문에서는 엘리베이터 위치, 환승 부담, 출발역/도착역 접근성 체크를 "
        "우선 확인하세요."
    )


def elevator_failure_alternative_prompt() -> str:
    return (
        ANSWER_POLICY_TEXT
        + "\n엘리베이터 실패 또는 미확인 정보가 있으면 역명을 직접 언급하고, "
        "failed_sources, limitations, alternatives를 근거로 설명하세요."
    )


def answer_policy_resource() -> str:
    return ANSWER_POLICY_TEXT


def register_prompts(mcp: Any) -> None:
    mcp.prompt(
        name="barrier_free_answer_policy",
        description=(
            "Use this policy when presenting Barrier-Free Mobility MCP results. "
            "The user_message field is the canonical final answer."
        ),
    )(accessibility_brief_prompt)
    mcp.prompt(
        name="wheelchair_trip_check",
        description="Prompt policy for wheelchair accessibility trip answers.",
    )(wheelchair_trip_check_prompt)
    mcp.prompt(
        name="stroller_trip_check",
        description="Prompt policy for stroller accessibility trip answers.",
    )(stroller_trip_check_prompt)
    mcp.prompt(
        name="elevator_failure_alternative",
        description="Prompt policy for elevator failure or partial-data answers.",
    )(elevator_failure_alternative_prompt)


def register_resources(mcp: Any) -> None:
    mcp.resource(
        ANSWER_POLICY_RESOURCE_URI,
        name="barrier_free_answer_policy",
        description=(
            "Answer policy for MCP clients. Shows how to use user_message as the "
            "canonical final answer."
        ),
        mime_type="text/plain",
    )(answer_policy_resource)
