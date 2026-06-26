from __future__ import annotations

from app.core.config import Settings
from app.mcp.prompts import ANSWER_POLICY_RESOURCE_URI, accessibility_brief_prompt
from app.mcp.server import create_mcp_server
from app.mcp.tools import generate_accessibility_brief
from app.schemas.accessibility import AccessibilityResult


def test_accessibility_result_schema_marks_user_message_as_canonical_answer() -> None:
    schema = AccessibilityResult.model_json_schema()
    properties = schema["properties"]

    assert "Canonical final answer" in properties["user_message"]["description"]
    assert "display this text verbatim" in properties["user_message"]["description"]
    assert "Supporting station-level accessibility checks" in (
        properties["accessibility_checks"]["description"]
    )
    assert "Supporting evidence metadata" in properties["evidence_sources"]["description"]
    assert "Structured support for user_message" in (
        properties["user_message_summary"]["description"]
    )


def test_answer_policy_prompt_prioritizes_user_message_verbatim() -> None:
    prompt = accessibility_brief_prompt()

    assert "user_message" in prompt
    assert "verbatim" in prompt
    assert "안전하게 이동 가능합니다" in prompt
    assert "risk_score" in prompt
    assert "기준 시각" in prompt


def test_generate_accessibility_brief_docstring_mentions_verbatim_user_message() -> None:
    docstring = generate_accessibility_brief.__doc__ or ""

    assert "Final-answer tool" in docstring
    assert "user_message" in docstring
    assert "verbatim" in docstring


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
