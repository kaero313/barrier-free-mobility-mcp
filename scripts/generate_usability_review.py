from __future__ import annotations

import argparse
import asyncio
import re
import sys
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import AppMode, CacheBackend, Settings  # noqa: E402
from app.core.security import redact_sensitive_text  # noqa: E402
from app.services.accessibility_service import AccessibilityService  # noqa: E402
from scripts.usability_review_common import (  # noqa: E402
    ALLOWED_FEEDBACK_FLAGS,
    FLAG_LABELS,
    RATING_DIMENSIONS,
    RATING_LABELS,
    STATUS_LABELS,
    load_yaml_mapping,
    response_fingerprint,
    select_review_cases,
    validate_review_fixture,
)
from scripts.usability_review_html import render_review_html  # noqa: E402

REVIEW_CASE_FILE = PROJECT_ROOT / "tests" / "fixtures" / "usability_review_cases.yaml"
SOURCE_CASE_FILE = PROJECT_ROOT / "tests" / "fixtures" / "user_question_cases.yaml"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "usability"
URL_PATTERN = re.compile(r"https?://[^\s)>]+", re.IGNORECASE)
KST = timezone(timedelta(hours=9), name="KST")

@dataclass(frozen=True)
class ReviewEntry:
    case_name: str
    category: str
    persona: str
    review_focus: list[str]
    question: str
    status: str
    user_message: str
    response_sha256: str


def sanitize_review_text(value: str) -> str:
    redacted = redact_sensitive_text(value)
    return URL_PATTERN.sub("[내부 URL 제거]", redacted)


def build_review_service(
    mode: str,
    mock_failure_sources: set[str],
) -> AccessibilityService:
    settings = Settings(
        app_mode=AppMode(mode),
        cache_backend=CacheBackend.MEMORY,
        mock_failure_sources=mock_failure_sources if mode == "mock" else set(),
    )
    return AccessibilityService(settings=settings)


async def collect_review_entries(
    cases: list[dict[str, Any]],
    *,
    mode: str,
    service_factory: Callable[[str, set[str]], AccessibilityService] = build_review_service,
) -> list[ReviewEntry]:
    services: dict[frozenset[str], AccessibilityService] = {}
    entries: list[ReviewEntry] = []
    for case in cases:
        failure_sources = frozenset(case.get("mock_failure_sources", []))
        service = services.get(failure_sources)
        if service is None:
            service = service_factory(mode, set(failure_sources))
            services[failure_sources] = service

        question = sanitize_review_text(str(case["question"]))
        try:
            response = await service.answer_accessibility_question(question)
            status = str(response.status)
            user_message = sanitize_review_text(response.user_message)
        except Exception:  # pragma: no cover - defensive CLI boundary
            status = "ERROR"
            user_message = (
                "답변 생성 중 오류가 발생했습니다. 원인 정보는 리뷰 문서에 저장하지 않습니다."
            )

        entries.append(
            ReviewEntry(
                case_name=str(case["name"]),
                category=str(case.get("category", "unknown")),
                persona=sanitize_review_text(str(case["persona"])),
                review_focus=[
                    sanitize_review_text(str(item))
                    for item in case.get("review_focus", [])
                ],
                question=question,
                status=status,
                user_message=user_message,
                response_sha256=response_fingerprint(user_message),
            )
        )
    return entries


def render_review_markdown(
    entries: list[ReviewEntry],
    *,
    mode: str,
    generated_at: datetime,
) -> str:
    generated_at_label = generated_at.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
    lines = [
        "# Barrier-Free Mobility MCP 사용성 리뷰",
        "",
        f"- 생성 모드: `{mode}`",
        f"- 생성 시각: {generated_at_label}",
        f"- 검토 케이스: {len(entries)}개",
        "",
        "아래 답변은 MCP의 canonical `user_message`입니다. 각 항목을 일반 사용자 "
        "관점에서 읽고 1~5점으로 평가하세요.",
        "이름, 이메일, 장애 진단명 등 개인 식별 정보는 작성하지 마세요.",
    ]
    for index, entry in enumerate(entries, start=1):
        lines.extend(
            [
                "",
                f"## {index}. {entry.case_name}",
                "",
                f"- 사용자 상황: {entry.persona}",
                f"- 답변 생성 상태: {STATUS_LABELS.get(entry.status, entry.status)}",
                f"- 응답 식별자: `{entry.response_sha256}`",
                "- 검토 초점:",
                *[f"  - {focus}" for focus in entry.review_focus],
                "",
                "### 사용자 질문",
                "",
                f"> {entry.question}",
                "",
                "### MCP 답변",
                "",
                entry.user_message,
                "",
                "### 평가",
                "",
                "| 항목 | 점수(1~5) |",
                "|---|---|",
                *[
                    f"| {RATING_LABELS[dimension]} |  |"
                    for dimension in RATING_DIMENSIONS
                ],
                "",
                "문제가 있으면 표시하세요.",
                *[
                    f"- [ ] {FLAG_LABELS[flag]} (`{flag}`)"
                    for flag in ALLOWED_FEEDBACK_FLAGS
                ],
                "",
                "자유 의견:",
                "",
                "---",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_feedback_template(
    entries: list[ReviewEntry],
    *,
    mode: str,
) -> dict[str, Any]:
    return {
        "version": 1,
        "reviewer_id": "",
        "reviewed_at": None,
        "mode": mode,
        "cases": [
            {
                "case_name": entry.case_name,
                "response_sha256": entry.response_sha256,
                "ratings": {dimension: None for dimension in RATING_DIMENSIONS},
                "flags": [],
                "comment": "",
            }
            for entry in entries
        ],
    }


def write_review_outputs(
    entries: list[ReviewEntry],
    *,
    mode: str,
    output_dir: Path,
    generated_at: datetime,
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_path = output_dir / f"usability-review-{mode}.md"
    feedback_path = output_dir / f"usability-feedback-{mode}.yaml"
    html_path = output_dir / f"usability-review-{mode}.html"
    packet_path.write_text(
        render_review_markdown(entries, mode=mode, generated_at=generated_at),
        encoding="utf-8",
    )
    feedback_path.write_text(
        yaml.safe_dump(
            build_feedback_template(entries, mode=mode),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    html_path.write_text(
        render_review_html(entries, mode=mode, generated_at=generated_at),
        encoding="utf-8",
    )
    return packet_path, feedback_path, html_path


def open_review_in_browser(
    html_path: Path,
    *,
    opener: Callable[[str], bool] | None = None,
) -> bool:
    open_url = opener or webbrowser.open
    return bool(open_url(html_path.resolve().as_uri()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a human usability review packet from MCP user messages."
    )
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--case-set", choices=["basic", "all"], default="basic")
    parser.add_argument("--category", default=None)
    parser.add_argument("--name", action="append", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be greater than or equal to 0")
    return args


async def run_cli(args: argparse.Namespace) -> int:
    fixture = load_yaml_mapping(REVIEW_CASE_FILE)
    source_fixture = load_yaml_mapping(SOURCE_CASE_FILE)
    fixture_errors = validate_review_fixture(fixture, source_fixture)
    if fixture_errors:
        for error in fixture_errors:
            print(f"fixture error: {error}", file=sys.stderr)
        return 2

    cases = select_review_cases(
        fixture,
        source_fixture,
        mode=args.mode,
        case_set=args.case_set,
        category=args.category,
        names=set(args.name) if args.name else None,
        limit=args.limit,
    )
    if not cases:
        print("선택된 리뷰 케이스가 없습니다.", file=sys.stderr)
        return 2

    entries = await collect_review_entries(cases, mode=args.mode)
    packet_path, feedback_path, html_path = write_review_outputs(
        entries,
        mode=args.mode,
        output_dir=args.output_dir,
        generated_at=datetime.now(tz=KST),
    )
    print(f"review packet: {packet_path}")
    print(f"feedback template: {feedback_path}")
    print(f"interactive review: {html_path}")
    print(f"case_count={len(entries)}")
    if args.open_browser and not open_review_in_browser(html_path):
        print("브라우저를 자동으로 열지 못했습니다. HTML 파일을 직접 여세요.", file=sys.stderr)
    return 0


def main() -> int:
    return asyncio.run(run_cli(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
