from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from fastmcp import Client
from fastmcp.client.auth.bearer import BearerAuth

BASIC_PROFILE = {
    "wheelchair": True,
    "can_use_stairs": False,
    "can_use_escalator": False,
    "need_elevator_only": True,
    "max_transfer_count": 1,
}
DEFAULT_QUESTION = (
    "\ud720\uccb4\uc5b4\ub85c \ud64d\ub300\uc785\uad6c\uc5ed\uc5d0\uc11c "
    "\uc0bc\uc131\uc5ed\uae4c\uc9c0 \uac08 \uc218 \uc788\uc5b4?"
)

HONGDAE = "\ud64d\ub300\uc785\uad6c"
SAMSUNG = "\uc0bc\uc131"
SEOUL_LINE_1 = "1\ud638\uc120 \uc11c\uc6b8\uc5ed"
CITY_HALL_LINE_1 = "1\ud638\uc120 \uc2dc\uccad"
EXPRESS_TERMINAL_LINE_9 = "9\ud638\uc120 \uace0\uc18d\ud130\ubbf8\ub110"
YEOUIDO_LINE_9 = "9\ud638\uc120 \uc5ec\uc758\ub3c4"
SADANG_LINE_4 = "4\ud638\uc120 \uc0ac\ub2f9"
DDP_LINE_4 = "4\ud638\uc120 \ub3d9\ub300\ubb38\uc5ed\uc0ac\ubb38\ud654\uacf5\uc6d0"
KONKUK_LINE_7 = "7\ud638\uc120 \uac74\ub300\uc785\uad6c"

COVERAGE_CASES = [
    {
        "name": "hongdae_to_samsung",
        "origin": HONGDAE,
        "destination": SAMSUNG,
        "mobility_profile": BASIC_PROFILE,
    },
    {
        "name": "seoul_to_cityhall_line1",
        "origin": SEOUL_LINE_1,
        "destination": CITY_HALL_LINE_1,
        "mobility_profile": BASIC_PROFILE,
    },
    {
        "name": "express_terminal_to_yeouido_line9",
        "origin": EXPRESS_TERMINAL_LINE_9,
        "destination": YEOUIDO_LINE_9,
        "mobility_profile": BASIC_PROFILE,
    },
    {
        "name": "sadang_to_ddp_maintenance",
        "origin": SADANG_LINE_4,
        "destination": DDP_LINE_4,
        "mobility_profile": BASIC_PROFILE,
    },
    {
        "name": "restroom_required_missing",
        "origin": KONKUK_LINE_7,
        "destination": EXPRESS_TERMINAL_LINE_9,
        "mobility_profile": {
            **BASIC_PROFILE,
            "need_accessible_restroom": True,
        },
    },
]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Call the local MCP server.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--origin", default=HONGDAE)
    parser.add_argument("--destination", default=SAMSUNG)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--api-key", default=None, help="MCP bearer token")
    parser.add_argument("--case-set", choices=["basic", "coverage"], default="basic")
    parser.add_argument(
        "--tool",
        choices=[
            "check_accessible_trip",
            "generate_accessibility_brief",
            "answer_accessibility_question",
        ],
        default="check_accessible_trip",
        help=(
            "Tool to call. Use answer_accessibility_question for natural-language "
            "final user_message smoke."
        ),
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only user_message, status, risk_level, and evidence summary.",
    )
    args = parser.parse_args()

    auth = BearerAuth(args.api_key) if args.api_key else None

    async with Client(args.url, auth=auth) as client:
        tools = await client.list_tools()
        print("TOOLS", [tool.name for tool in tools])

        if args.case_set == "coverage":
            await _run_coverage_cases(client, tool_name=args.tool)
            return

        result = await _call_tool(
            client,
            tool_name=args.tool,
            question=args.question,
            origin=args.origin,
            destination=args.destination,
            mobility_profile=BASIC_PROFILE,
        )
        if args.summary_only:
            print(json.dumps(_summarize_result(result), ensure_ascii=False, indent=2))
            return
        print(json.dumps(result, ensure_ascii=False, indent=2))


async def _run_coverage_cases(client: Client, *, tool_name: str) -> None:
    summaries: list[dict[str, Any]] = []
    for case in COVERAGE_CASES:
        content = await _call_tool(
            client,
            tool_name=tool_name,
            question=(
                "\ud720\uccb4\uc5b4\ub85c "
                f"{case['origin']}\uc5d0\uc11c {case['destination']}\uae4c\uc9c0 "
                "\uac08 \uc218 \uc788\uc5b4?"
            ),
            origin=case["origin"],
            destination=case["destination"],
            mobility_profile=case["mobility_profile"],
        )
        nested = content.get("result") or content
        summaries.append(
            {
                "name": case["name"],
                "status": content.get("status"),
                "risk_level": nested.get("risk_level"),
                "risk_score": nested.get("risk_score"),
                "confidence_level": nested.get("confidence_level"),
                "last_checked_at": nested.get("last_checked_at"),
                "headline": nested.get("user_message_summary", {}).get("headline"),
                "failed_sources": [
                    source.get("source_name") for source in nested.get("failed_sources", [])
                ],
                "payload_chars": len(json.dumps(content, ensure_ascii=False)),
            }
        )

    print(json.dumps(summaries, ensure_ascii=False, indent=2))


async def _call_tool(
    client: Client,
    *,
    tool_name: str,
    question: str,
    origin: str,
    destination: str,
    mobility_profile: dict[str, Any],
) -> dict[str, Any]:
    if tool_name == "answer_accessibility_question":
        result = await client.call_tool(tool_name, {"question": question})
        return result.structured_content
    result = await client.call_tool(
        tool_name,
        {
            "origin": origin,
            "destination": destination,
            "mobility_profile": mobility_profile,
        },
    )
    return result.structured_content


def _summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    nested = result.get("result") or result
    return {
        "status": result.get("status"),
        "intent": result.get("intent"),
        "risk_level": nested.get("risk_level"),
        "confidence_level": nested.get("confidence_level"),
        "last_checked_at": nested.get("last_checked_at"),
        "user_message": result.get("user_message"),
        "evidence_sources": nested.get("evidence_sources", []),
        "failed_sources": nested.get("failed_sources", []),
        "limitations": nested.get("limitations", []),
    }


if __name__ == "__main__":
    asyncio.run(main())
