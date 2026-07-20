from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from importlib.metadata import version as package_version
from typing import Any, Protocol

import httpx
from fastmcp import Client as FastMCPClient
from fastmcp.client.auth.bearer import BearerAuth
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Implementation
from pydantic import AnyUrl

ANSWER_POLICY_RESOURCE_URI = "barrier-free://answer-policy"
ANSWER_POLICY_PROMPT = "barrier_free_answer_policy"

REQUIRED_TOOLS = {
    "resolve_station",
    "get_station_facilities",
    "get_elevator_status",
    "get_accessible_restroom",
    "get_route_candidates",
    "check_accessible_trip",
    "generate_accessibility_brief",
    "answer_accessibility_question",
}
REQUIRED_PROMPTS = {
    ANSWER_POLICY_PROMPT,
    "wheelchair_trip_check",
    "stroller_trip_check",
    "elevator_failure_alternative",
}

BASIC_PROFILE = {
    "wheelchair": True,
    "can_use_stairs": False,
    "can_use_escalator": False,
    "need_elevator_only": True,
    "max_transfer_count": 1,
}

VOLATILE_MESSAGE_PATTERNS = (
    re.compile(r"\d{4}년 \d{1,2}월 \d{1,2}일 \d{2}:\d{2}"),
    re.compile(r"\b\d{2}:\d{2}\b"),
)


@dataclass(frozen=True)
class Scenario:
    name: str
    tool_name: str
    arguments: dict[str, Any]


SCENARIOS = (
    Scenario(
        name="natural_question",
        tool_name="answer_accessibility_question",
        arguments={
            "question": "휠체어로 홍대입구역에서 삼성역까지 갈 수 있어?",
        },
    ),
    Scenario(
        name="structured_trip",
        tool_name="generate_accessibility_brief",
        arguments={
            "origin": "홍대입구",
            "destination": "삼성",
            "mobility_profile": BASIC_PROFILE,
        },
    ),
    Scenario(
        name="clarification",
        tool_name="answer_accessibility_question",
        arguments={
            "question": "휠체어로 고속터미널역에서 여의도역까지 갈 수 있어?",
        },
    ),
)


@dataclass(frozen=True)
class ScenarioReport:
    name: str
    status: str | None
    intent: str | None
    risk_level: str | None
    judgement: str | None
    clarification_needed: bool
    question_count: int
    has_user_message: bool
    message_sections: list[str]
    stable_user_message_sha256: str


@dataclass(frozen=True)
class ClientReport:
    client_name: str
    client_version: str
    server_name: str | None
    tools: list[str]
    prompts: list[str]
    resources: list[str]
    prompt_policy_sha256: str
    resource_policy_sha256: str
    policy_contract_ok: bool
    scenarios: list[ScenarioReport]


@dataclass(frozen=True)
class InteroperabilityReport:
    compatible: bool
    issues: list[str]
    clients: list[ClientReport]


class ClientAdapter(Protocol):
    async def list_tools(self) -> list[str]: ...

    async def list_prompts(self) -> list[str]: ...

    async def list_resources(self) -> list[str]: ...

    async def get_prompt_text(self, name: str) -> str: ...

    async def read_resource_text(self, uri: str) -> str: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class FastMCPAdapter:
    def __init__(self, client: FastMCPClient) -> None:
        self._client = client

    async def list_tools(self) -> list[str]:
        return sorted(tool.name for tool in await self._client.list_tools())

    async def list_prompts(self) -> list[str]:
        return sorted(prompt.name for prompt in await self._client.list_prompts())

    async def list_resources(self) -> list[str]:
        return sorted(str(resource.uri) for resource in await self._client.list_resources())

    async def get_prompt_text(self, name: str) -> str:
        return _extract_prompt_text(await self._client.get_prompt(name))

    async def read_resource_text(self, uri: str) -> str:
        contents = await self._client.read_resource(uri)
        return _extract_resource_text(contents)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._client.call_tool(name, arguments)
        return _extract_structured_content(result)


class OfficialSdkAdapter:
    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def list_tools(self) -> list[str]:
        result = await self._session.list_tools()
        return sorted(tool.name for tool in result.tools)

    async def list_prompts(self) -> list[str]:
        result = await self._session.list_prompts()
        return sorted(prompt.name for prompt in result.prompts)

    async def list_resources(self) -> list[str]:
        result = await self._session.list_resources()
        return sorted(str(resource.uri) for resource in result.resources)

    async def get_prompt_text(self, name: str) -> str:
        return _extract_prompt_text(await self._session.get_prompt(name))

    async def read_resource_text(self, uri: str) -> str:
        result = await self._session.read_resource(AnyUrl(uri))
        return _extract_resource_text(result.contents)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError(f"Official MCP SDK returned an error for tool '{name}'.")
        return _extract_structured_content(result)


async def run_fastmcp_client(url: str, api_key: str | None) -> ClientReport:
    auth = BearerAuth(api_key) if api_key else None
    async with FastMCPClient(url, auth=auth) as client:
        initialize_result = client.initialize_result
        server_name = _server_name(initialize_result)
        return await collect_client_report(
            FastMCPAdapter(client),
            client_name="fastmcp",
            client_version=package_version("fastmcp"),
            server_name=server_name,
        )


async def run_official_sdk_client(
    url: str,
    api_key: str | None,
    *,
    timeout_seconds: float,
) -> ClientReport:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    timeout = httpx.Timeout(timeout_seconds)
    async with (
        httpx.AsyncClient(headers=headers, timeout=timeout) as http_client,
        streamable_http_client(url, http_client=http_client) as streams,
    ):
        read_stream, write_stream, _ = streams
        client_version = package_version("mcp")
        async with ClientSession(
            read_stream,
            write_stream,
            client_info=Implementation(
                name="barrier-free-interoperability-check",
                version=client_version,
            ),
        ) as session:
            initialize_result = await session.initialize()
            return await collect_client_report(
                OfficialSdkAdapter(session),
                client_name="mcp-python-sdk",
                client_version=client_version,
                server_name=_server_name(initialize_result),
            )


async def collect_client_report(
    client: ClientAdapter,
    *,
    client_name: str,
    client_version: str,
    server_name: str | None,
) -> ClientReport:
    tools = await client.list_tools()
    prompts = await client.list_prompts()
    resources = await client.list_resources()
    prompt_policy = await client.get_prompt_text(ANSWER_POLICY_PROMPT)
    resource_policy = await client.read_resource_text(ANSWER_POLICY_RESOURCE_URI)
    scenario_reports = [
        summarize_tool_payload(
            scenario.name,
            await client.call_tool(scenario.tool_name, scenario.arguments),
        )
        for scenario in SCENARIOS
    ]
    return ClientReport(
        client_name=client_name,
        client_version=client_version,
        server_name=server_name,
        tools=tools,
        prompts=prompts,
        resources=resources,
        prompt_policy_sha256=_sha256(prompt_policy),
        resource_policy_sha256=_sha256(resource_policy),
        policy_contract_ok=_policy_contract_ok(prompt_policy, resource_policy),
        scenarios=scenario_reports,
    )


def summarize_tool_payload(name: str, payload: dict[str, Any]) -> ScenarioReport:
    nested = payload.get("result")
    result = nested if isinstance(nested, dict) else payload
    summary = result.get("user_message_summary")
    summary = summary if isinstance(summary, dict) else {}
    message = payload.get("user_message") or result.get("user_message") or ""
    questions = payload.get("questions") or result.get("questions") or []
    return ScenarioReport(
        name=name,
        status=_optional_string(payload.get("status") or result.get("status")),
        intent=_optional_string(payload.get("intent")),
        risk_level=_optional_string(result.get("risk_level")),
        judgement=_optional_string(summary.get("judgement")),
        clarification_needed=bool(
            payload.get("clarification_needed", result.get("clarification_needed", False))
        ),
        question_count=len(questions) if isinstance(questions, list) else 0,
        has_user_message=bool(message.strip()),
        message_sections=_message_sections(message),
        stable_user_message_sha256=_sha256(_normalize_user_message(message)),
    )


def build_interoperability_report(clients: list[ClientReport]) -> InteroperabilityReport:
    issues: list[str] = []
    for client in clients:
        issues.extend(validate_client_report(client))
    if len(clients) > 1:
        issues.extend(compare_client_reports(clients))
    return InteroperabilityReport(
        compatible=not issues,
        issues=issues,
        clients=clients,
    )


def validate_client_report(report: ClientReport) -> list[str]:
    issues: list[str] = []
    missing_tools = sorted(REQUIRED_TOOLS - set(report.tools))
    if missing_tools:
        issues.append(f"{report.client_name}: missing tools {missing_tools}")
    missing_prompts = sorted(REQUIRED_PROMPTS - set(report.prompts))
    if missing_prompts:
        issues.append(f"{report.client_name}: missing prompts {missing_prompts}")
    if ANSWER_POLICY_RESOURCE_URI not in report.resources:
        issues.append(f"{report.client_name}: answer policy resource is missing")
    if not report.policy_contract_ok:
        issues.append(f"{report.client_name}: prompt/resource answer policy mismatch")

    scenarios = {scenario.name: scenario for scenario in report.scenarios}
    for name in ("natural_question", "structured_trip"):
        scenario = scenarios.get(name)
        if scenario is None:
            issues.append(f"{report.client_name}: scenario '{name}' is missing")
            continue
        if scenario.status != "SUCCESS":
            issues.append(
                f"{report.client_name}: scenario '{name}' status is {scenario.status!r}"
            )
        if not scenario.has_user_message:
            issues.append(f"{report.client_name}: scenario '{name}' has no user_message")
        for required_section in ("기준 시각", "주의사항"):
            if required_section not in scenario.message_sections:
                issues.append(
                    f"{report.client_name}: scenario '{name}' is missing "
                    f"'{required_section}' section"
                )

    clarification = scenarios.get("clarification")
    if clarification is None:
        issues.append(f"{report.client_name}: clarification scenario is missing")
    else:
        if clarification.status != "NEEDS_CLARIFICATION":
            issues.append(
                f"{report.client_name}: clarification status is "
                f"{clarification.status!r}"
            )
        if not clarification.clarification_needed or clarification.question_count != 1:
            issues.append(
                f"{report.client_name}: clarification must contain exactly one question"
            )
        if not clarification.has_user_message:
            issues.append(f"{report.client_name}: clarification has no user_message")
    return issues


def compare_client_reports(reports: list[ClientReport]) -> list[str]:
    issues: list[str] = []
    baseline = reports[0]
    baseline_scenarios = {scenario.name: scenario for scenario in baseline.scenarios}
    for current in reports[1:]:
        if current.tools != baseline.tools:
            issues.append(
                f"{current.client_name}: tool discovery differs from {baseline.client_name}"
            )
        if current.prompts != baseline.prompts:
            issues.append(
                f"{current.client_name}: prompt discovery differs from {baseline.client_name}"
            )
        if current.resources != baseline.resources:
            issues.append(
                f"{current.client_name}: resource discovery differs from {baseline.client_name}"
            )
        if current.prompt_policy_sha256 != baseline.prompt_policy_sha256:
            issues.append(
                f"{current.client_name}: prompt policy differs from {baseline.client_name}"
            )
        if current.resource_policy_sha256 != baseline.resource_policy_sha256:
            issues.append(
                f"{current.client_name}: resource policy differs from {baseline.client_name}"
            )

        for scenario in current.scenarios:
            reference = baseline_scenarios.get(scenario.name)
            if reference is None or _scenario_contract(scenario) != _scenario_contract(
                reference
            ):
                issues.append(
                    f"{current.client_name}: scenario '{scenario.name}' differs from "
                    f"{baseline.client_name}"
                )
    return issues


def render_text_report(report: InteroperabilityReport) -> str:
    lines = [
        "MCP interoperability: " + ("PASS" if report.compatible else "FAIL"),
    ]
    for client in report.clients:
        lines.append(
            f"- {client.client_name} {client.client_version}: "
            f"tools={len(client.tools)}, prompts={len(client.prompts)}, "
            f"resources={len(client.resources)}, policy="
            f"{'ok' if client.policy_contract_ok else 'mismatch'}"
        )
        for scenario in client.scenarios:
            lines.append(
                f"  - {scenario.name}: status={scenario.status}, "
                f"judgement={scenario.judgement}, "
                f"clarification={scenario.clarification_needed}, "
                f"message={scenario.stable_user_message_sha256[:12]}"
            )
    lines.extend(f"- issue: {issue}" for issue in report.issues)
    return "\n".join(lines)


def _extract_structured_content(result: Any) -> dict[str, Any]:
    payload = getattr(result, "structured_content", None)
    if payload is None:
        payload = getattr(result, "structuredContent", None)
    if isinstance(payload, dict):
        return payload

    for content in getattr(result, "content", []):
        text = getattr(content, "text", None)
        if not isinstance(text, str):
            continue
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            return decoded
    raise ValueError("MCP tool result did not contain structured JSON content.")


def _extract_prompt_text(result: Any) -> str:
    texts: list[str] = []
    for message in getattr(result, "messages", []):
        text = getattr(getattr(message, "content", None), "text", None)
        if isinstance(text, str):
            texts.append(text)
    return "\n".join(texts)


def _extract_resource_text(contents: Any) -> str:
    texts = [
        text
        for content in contents
        if isinstance((text := getattr(content, "text", None)), str)
    ]
    return "\n".join(texts)


def _policy_contract_ok(prompt_text: str, resource_text: str) -> bool:
    required_phrases = (
        "user_message",
        "verbatim",
        "Do not claim safety is guaranteed",
        "기준 시각",
    )
    return prompt_text == resource_text and all(
        phrase in prompt_text for phrase in required_phrases
    )


def _scenario_contract(scenario: ScenarioReport) -> tuple[Any, ...]:
    return (
        scenario.status,
        scenario.intent,
        scenario.risk_level,
        scenario.judgement,
        scenario.clarification_needed,
        scenario.question_count,
        scenario.message_sections,
        scenario.stable_user_message_sha256,
    )


def _message_sections(message: str) -> list[str]:
    return [
        line.removeprefix("### ").strip()
        for line in message.splitlines()
        if line.startswith("### ")
    ]


def _normalize_user_message(message: str) -> str:
    normalized = message.strip().replace("\r\n", "\n")
    for pattern in VOLATILE_MESSAGE_PATTERNS:
        normalized = pattern.sub("<checked-at>", normalized)
    return normalized


def _server_name(initialize_result: Any) -> str | None:
    server_info = getattr(initialize_result, "serverInfo", None)
    name = getattr(server_info, "name", None)
    return name if isinstance(name, str) else None


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def run(args: argparse.Namespace) -> InteroperabilityReport:
    reports: list[ClientReport] = []
    if args.client in {"all", "fastmcp"}:
        reports.append(await run_fastmcp_client(args.url, args.api_key))
    if args.client in {"all", "sdk"}:
        reports.append(
            await run_official_sdk_client(
                args.url,
                args.api_key,
                timeout_seconds=args.timeout_seconds,
            )
        )
    return build_interoperability_report(reports)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the MCP contract through two HTTP client APIs."
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--api-key", default=None, help="Optional MCP bearer token")
    parser.add_argument(
        "--client",
        choices=["all", "fastmcp", "sdk"],
        default="all",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = asyncio.run(run(args))
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print(render_text_report(report))
    if not report.compatible:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
