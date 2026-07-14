from __future__ import annotations

from app.core.config import Settings
from app.mcp.prompts import ANSWER_POLICY_RESOURCE_URI, accessibility_brief_prompt
from app.mcp.server import create_mcp_server
from app.mcp.tools import answer_accessibility_question, generate_accessibility_brief
from app.schemas.accessibility import AccessibilityQuestionResult, AccessibilityResult


def test_accessibility_result_schema_marks_user_message_as_canonical_answer() -> None:
    schema = AccessibilityResult.model_json_schema()
    properties = schema["properties"]

    assert "Canonical Markdown final answer" in properties["user_message"]["description"]
    assert "display this text verbatim" in properties["user_message"]["description"]
    assert "Supporting station-level accessibility checks" in (
        properties["accessibility_checks"]["description"]
    )
    assert "Supporting evidence metadata" in properties["evidence_sources"]["description"]
    assert "Structured support for user_message" in (
        properties["user_message_summary"]["description"]
    )


def test_accessibility_question_result_schema_marks_user_message_as_canonical_answer() -> None:
    schema = AccessibilityQuestionResult.model_json_schema()
    properties = schema["properties"]

    assert "Canonical Markdown final answer" in properties["user_message"]["description"]
    assert "display this text verbatim" in properties["user_message"]["description"]
    assert "trip accessibility result" in properties["result"]["description"]
    assert "station facility result" in properties["facility_result"]["description"]


def test_answer_policy_prompt_prioritizes_user_message_verbatim() -> None:
    prompt = accessibility_brief_prompt()

    assert "user_message" in prompt
    assert "Do not prepend a separate route summary or judgement" in prompt
    assert "questions[0]" in prompt
    assert "verbatim" in prompt
    assert "answer_accessibility_question" in prompt
    assert "generate_accessibility_brief" in prompt
    assert "안전하게 이동 가능합니다" in prompt
    assert "risk_score" in prompt
    assert "기준 시각" in prompt
    assert "facility_result" in prompt
    assert "확인 결과" in prompt
    assert "alternative_request" in prompt
    assert "previous conversation routes" in prompt
    assert "Markdown" in prompt
    assert "compact tables" in prompt
    assert "code block" in prompt


def test_generate_accessibility_brief_docstring_mentions_verbatim_user_message() -> None:
    docstring = generate_accessibility_brief.__doc__ or ""

    assert "Final-answer tool" in docstring
    assert "user_message" in docstring
    assert "verbatim" in docstring
    assert "Markdown" in docstring


def test_answer_accessibility_question_docstring_mentions_final_answer() -> None:
    docstring = answer_accessibility_question.__doc__ or ""

    assert "Final-answer tool" in docstring
    assert "natural-language" in docstring
    assert "Markdown" in docstring


async def test_mcp_server_registers_answer_policy_prompt_and_resource() -> None:
    server = create_mcp_server(Settings(_env_file=None))

    prompt_names = {prompt.name for prompt in await server.list_prompts()}
    resources = await server.list_resources()
    resource_uris = {str(resource.uri) for resource in resources}

    assert "barrier_free_answer_policy" in prompt_names
    assert ANSWER_POLICY_RESOURCE_URI in resource_uris

    resource = await server.read_resource(ANSWER_POLICY_RESOURCE_URI)
    content = resource.contents[0].content

    assert "user_message" in content
    assert "canonical final answer" in content
