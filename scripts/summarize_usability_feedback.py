from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.usability_review_common import (  # noqa: E402
    RATING_DIMENSIONS,
    ReviewFeedbackDocument,
    load_feedback_document,
    validate_completed_feedback,
)

TARGET_SCORE = 4


def summarize_feedback_documents(
    documents: list[ReviewFeedbackDocument],
) -> dict[str, Any]:
    rating_values: dict[str, list[int]] = {
        dimension: [] for dimension in RATING_DIMENSIONS
    }
    below_target_counts: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()
    by_case: dict[str, list[Any]] = defaultdict(list)

    for document in documents:
        for case in document.cases:
            by_case[case.case_name].append(case)
            for dimension, value in case.ratings.model_dump().items():
                if value is None:
                    continue
                rating_values[dimension].append(value)
                if value < TARGET_SCORE:
                    below_target_counts[dimension] += 1
            flag_counts.update(case.flags)

    case_summaries: list[dict[str, Any]] = []
    for case_name, reviews in by_case.items():
        values = [
            value
            for review in reviews
            for value in review.ratings.model_dump().values()
            if value is not None
        ]
        flags = Counter(flag for review in reviews for flag in review.flags)
        case_summaries.append(
            {
                "case_name": case_name,
                "review_count": len(reviews),
                "average_score": round(sum(values) / len(values), 2) if values else None,
                "response_variants": len(
                    {review.response_sha256 for review in reviews}
                ),
                "flag_counts": dict(sorted(flags.items())),
            }
        )
    case_summaries.sort(
        key=lambda item: (
            item["average_score"] is None,
            item["average_score"] if item["average_score"] is not None else 99,
            item["case_name"],
        )
    )

    return {
        "review_document_count": len(documents),
        "reviewed_response_count": sum(len(document.cases) for document in documents),
        "unique_case_count": len(by_case),
        "rating_averages": {
            dimension: round(sum(values) / len(values), 2) if values else None
            for dimension, values in rating_values.items()
        },
        "below_target_counts": {
            dimension: below_target_counts.get(dimension, 0)
            for dimension in RATING_DIMENSIONS
        },
        "flag_counts": dict(sorted(flag_counts.items())),
        "cases": case_summaries,
    }


def format_summary(summary: dict[str, Any]) -> str:
    lines = [
        "사용성 피드백 요약",
        f"- 피드백 문서: {summary['review_document_count']}개",
        f"- 평가 응답: {summary['reviewed_response_count']}개",
        f"- 고유 케이스: {summary['unique_case_count']}개",
        "",
        "항목별 평균 및 4점 미만 응답 수",
    ]
    for dimension in RATING_DIMENSIONS:
        average = summary["rating_averages"][dimension]
        below_target = summary["below_target_counts"][dimension]
        lines.append(f"- {dimension}: 평균 {average}, 4점 미만 {below_target}건")

    lines.extend(["", "문제 표시 집계"])
    if summary["flag_counts"]:
        lines.extend(
            f"- {flag}: {count}건"
            for flag, count in summary["flag_counts"].items()
        )
    else:
        lines.append("- 표시된 문제 없음")

    lines.extend(["", "우선 검토 케이스"])
    for case in summary["cases"]:
        lines.append(
            f"- {case['case_name']}: 평균 {case['average_score']}, "
            f"리뷰 {case['review_count']}건, 답변 버전 {case['response_variants']}개"
        )
    return "\n".join(lines)


def validation_error_locations(error: ValidationError) -> list[str]:
    return [
        ".".join(str(part) for part in item["loc"])
        for item in error.errors(include_input=False)
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and summarize completed usability feedback YAML or JSON files."
    )
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def run_cli(args: argparse.Namespace) -> int:
    documents: list[ReviewFeedbackDocument] = []
    errors: list[str] = []
    for path in args.paths:
        try:
            document = load_feedback_document(path)
        except (OSError, ValueError, ValidationError) as exc:
            if isinstance(exc, ValidationError):
                locations = ", ".join(validation_error_locations(exc)) or "unknown"
                errors.append(f"{path}: invalid fields: {locations}")
            else:
                errors.append(f"{path}: feedback file could not be read")
            continue
        completion_errors = validate_completed_feedback(document)
        errors.extend(f"{path}: {error}" for error in completion_errors)
        documents.append(document)

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2

    summary = summarize_feedback_documents(documents)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_summary(summary))
    return 0


def main() -> int:
    return run_cli(parse_args())


if __name__ == "__main__":
    sys.exit(main())
