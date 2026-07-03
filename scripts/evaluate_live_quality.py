from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import AppMode, CacheBackend, Settings  # noqa: E402
from app.core.security import redact_sensitive_text  # noqa: E402
from app.schemas.accessibility import AccessibilityQuestionResult  # noqa: E402
from app.services.accessibility_service import AccessibilityService  # noqa: E402

CASE_FILE = PROJECT_ROOT / "tests" / "fixtures" / "user_question_cases.yaml"
TECHNICAL_TERMS = ("risk_level", "confidence_level", "cache", "payload")


@dataclass(frozen=True)
class EvaluationSummary:
    name: str
    category: str
    status: str
    risk_level: str
    judgement: str
    clarification_needed: bool
    latency_ms: int
    payload_bytes: int
    failed_source_count: int
    unverified_count: int
    has_checked_at_section: bool
    has_notice_section: bool
    issue_count: int
    issues: list[str]
    error: str | None = None


def load_case_fixture(path: Path = CASE_FILE) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def select_cases(
    fixture: dict[str, Any],
    *,
    case_set: str = "basic",
    category: str | None = None,
    names: set[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    cases = list(fixture.get("cases", []))
    if case_set == "basic":
        cases = [case for case in cases if is_basic_live_case(case)]
    elif case_set != "all":
        raise ValueError(f"Unsupported case set: {case_set}")

    if category:
        cases = [case for case in cases if case.get("category") == category]
    if names:
        cases = [case for case in cases if case.get("name") in names]
    if limit is not None:
        cases = cases[:limit]
    return cases


def is_basic_live_case(case: dict[str, Any]) -> bool:
    execution = case.get("execution", {})
    expectations = case.get("expectations", {})
    return execution.get("kind") == "trip_brief" or (
        execution.get("kind") == "future_natural_language"
        and expectations.get("future_reason") == "place_candidate_clarification_supported"
    )


async def evaluate_cases(
    service: AccessibilityService,
    cases: list[dict[str, Any]],
    *,
    required_sections: list[str],
    banned_phrases: list[str],
) -> list[EvaluationSummary]:
    summaries: list[EvaluationSummary] = []
    for case in cases:
        start = perf_counter()
        try:
            response = await service.answer_accessibility_question(case["question"])
        except Exception as exc:  # pragma: no cover - exercised by direct unit test
            latency_ms = int((perf_counter() - start) * 1000)
            summaries.append(summarize_error(case, exc, latency_ms))
            continue
        latency_ms = int((perf_counter() - start) * 1000)
        summaries.append(
            summarize_response(
                case,
                response,
                latency_ms=latency_ms,
                required_sections=required_sections,
                banned_phrases=banned_phrases,
            )
        )
    return summaries


def summarize_response(
    case: dict[str, Any],
    response: AccessibilityQuestionResult,
    *,
    latency_ms: int,
    required_sections: list[str],
    banned_phrases: list[str],
) -> EvaluationSummary:
    user_message = response.user_message or ""
    result = response.result
    risk_level = result.risk_level if result else "UNKNOWN"
    failed_source_count = len(result.failed_sources) if result else 0
    unverified_count = len(result.unverified_parts) if result else 0
    require_full_sections = result is not None and not response.clarification_needed
    issues = evaluate_user_message_quality(
        user_message,
        required_sections=required_sections,
        banned_phrases=banned_phrases,
        require_full_sections=require_full_sections,
    )
    payload_bytes = len(response.model_dump_json(exclude_none=True).encode("utf-8"))

    return EvaluationSummary(
        name=str(case.get("name", "")),
        category=str(case.get("category", "")),
        status=str(response.status),
        risk_level=str(risk_level),
        judgement=extract_judgement(response),
        clarification_needed=response.clarification_needed,
        latency_ms=latency_ms,
        payload_bytes=payload_bytes,
        failed_source_count=failed_source_count,
        unverified_count=unverified_count,
        has_checked_at_section="기준 시각" in user_message,
        has_notice_section="주의사항" in user_message,
        issue_count=len(issues),
        issues=issues,
    )


def summarize_error(
    case: dict[str, Any],
    exc: Exception,
    latency_ms: int,
) -> EvaluationSummary:
    error = redact_sensitive_text(f"{exc.__class__.__name__}: {exc}")
    return EvaluationSummary(
        name=str(case.get("name", "")),
        category=str(case.get("category", "")),
        status="ERROR",
        risk_level="UNKNOWN",
        judgement="",
        clarification_needed=False,
        latency_ms=latency_ms,
        payload_bytes=0,
        failed_source_count=0,
        unverified_count=0,
        has_checked_at_section=False,
        has_notice_section=False,
        issue_count=1,
        issues=["exception"],
        error=error,
    )


def evaluate_user_message_quality(
    user_message: str,
    *,
    required_sections: list[str],
    banned_phrases: list[str],
    require_full_sections: bool,
) -> list[str]:
    issues: list[str] = []
    if not user_message.strip():
        issues.append("missing_user_message")
        return issues
    if "판단:" not in user_message:
        issues.append("missing_section:판단:")
    if require_full_sections:
        for section in required_sections:
            if section not in user_message:
                issues.append(f"missing_section:{section}")
    for phrase in banned_phrases:
        if phrase in user_message:
            issues.append(f"banned_phrase:{phrase}")
    lowered = user_message.lower()
    for term in TECHNICAL_TERMS:
        if term.lower() in lowered:
            issues.append(f"technical_term:{term}")
    if redact_sensitive_text(user_message) != user_message:
        issues.append("secret_like_text")
    return issues


def extract_judgement(response: AccessibilityQuestionResult) -> str:
    if response.result and response.result.user_message_summary.judgement:
        return response.result.user_message_summary.judgement
    for line in response.user_message.splitlines():
        if line.startswith("판단:"):
            return line.split(":", 1)[1].strip()
    return ""


def summaries_to_dicts(summaries: list[EvaluationSummary]) -> list[dict[str, Any]]:
    return [asdict(summary) for summary in summaries]


def format_table(summaries: list[EvaluationSummary]) -> str:
    headers = [
        "name",
        "category",
        "status",
        "risk",
        "judgement",
        "clarify",
        "ms",
        "bytes",
        "failed",
        "unverified",
        "time",
        "notice",
        "issues",
    ]
    rows = [
        [
            shorten(summary.name, 34),
            shorten(summary.category, 18),
            summary.status,
            summary.risk_level,
            shorten(summary.judgement, 12),
            "Y" if summary.clarification_needed else "N",
            str(summary.latency_ms),
            str(summary.payload_bytes),
            str(summary.failed_source_count),
            str(summary.unverified_count),
            "Y" if summary.has_checked_at_section else "N",
            "Y" if summary.has_notice_section else "N",
            str(summary.issue_count),
        ]
        for summary in summaries
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows)) if rows else len(header)
        for index, header in enumerate(headers)
    ]
    lines = [
        " | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)),
        "-+-".join("-" * width for width in widths),
    ]
    lines.extend(
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    )
    return "\n".join(lines)


def shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def build_live_service() -> AccessibilityService:
    settings = Settings(app_mode=AppMode.LIVE, cache_backend=CacheBackend.MEMORY)
    return AccessibilityService(settings=settings)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate live API answer quality for natural-language cases."
    )
    parser.add_argument("--case-set", choices=["basic", "all"], default="basic")
    parser.add_argument("--category", default=None)
    parser.add_argument("--name", action="append", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be greater than or equal to 0.")
    return args


async def run_cli(args: argparse.Namespace) -> int:
    fixture = load_case_fixture()
    cases = select_cases(
        fixture,
        case_set=args.case_set,
        category=args.category,
        names=set(args.name) if args.name else None,
        limit=args.limit,
    )
    service = build_live_service()
    summaries = await evaluate_cases(
        service,
        cases,
        required_sections=list(fixture.get("required_sections", [])),
        banned_phrases=list(fixture.get("banned_phrases", [])),
    )
    issue_count = sum(summary.issue_count for summary in summaries)
    report = {
        "case_count": len(summaries),
        "issue_count": issue_count,
        "results": summaries_to_dicts(summaries),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_table(summaries))
        print(f"\ncase_count={len(summaries)} issue_count={issue_count}")
        if issue_count:
            print("Use --json to inspect issue details.")
    return 1 if args.strict and issue_count else 0


def main() -> int:
    return asyncio.run(run_cli(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
