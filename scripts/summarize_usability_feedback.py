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
REPEATED_ISSUE_MIN_COUNT = 2


def _rating_average(case: Any) -> float | None:
    values = [
        value for value in case.ratings.model_dump().values() if value is not None
    ]
    return round(sum(values) / len(values), 2) if values else None


def _score_delta(first: float | int | None, latest: float | int | None) -> float | None:
    if first is None or latest is None:
        return None
    return round(latest - first, 2)


def build_case_review_trend(reviews: list[Any]) -> dict[str, Any] | None:
    """Compare review rounds in the same order as the input documents."""
    if len(reviews) < 2:
        return None

    first = reviews[0]
    latest = reviews[-1]
    dimension_trends: dict[str, dict[str, int | float | None]] = {}
    repeated_dimensions: list[str] = []
    for dimension in RATING_DIMENSIONS:
        values = [
            getattr(review.ratings, dimension)
            for review in reviews
            if getattr(review.ratings, dimension) is not None
        ]
        first_value = values[0] if values else None
        latest_value = values[-1] if values else None
        below_target_count = sum(value < TARGET_SCORE for value in values)
        if below_target_count >= REPEATED_ISSUE_MIN_COUNT:
            repeated_dimensions.append(dimension)
        dimension_trends[dimension] = {
            "first": first_value,
            "latest": latest_value,
            "delta": _score_delta(first_value, latest_value),
            "below_target_count": below_target_count,
        }

    flag_counts = Counter(flag for review in reviews for flag in review.flags)
    repeated_flags = {
        flag: count
        for flag, count in sorted(flag_counts.items())
        if count >= REPEATED_ISSUE_MIN_COUNT
    }
    first_average = _rating_average(first)
    latest_average = _rating_average(latest)
    return {
        "response_changed": first.response_sha256 != latest.response_sha256,
        "first_average_score": first_average,
        "latest_average_score": latest_average,
        "average_score_delta": _score_delta(first_average, latest_average),
        "dimension_trends": dimension_trends,
        "repeated_below_target_dimensions": repeated_dimensions,
        "repeated_flags": repeated_flags,
        "needs_follow_up": bool(repeated_dimensions or repeated_flags),
    }


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
        flags = Counter(flag for review in reviews for flag in review.flags)
        review_averages = [
            average
            for review in reviews
            if (average := _rating_average(review)) is not None
        ]
        case_summaries.append(
            {
                "case_name": case_name,
                "review_count": len(reviews),
                "average_score": (
                    round(sum(review_averages) / len(review_averages), 2)
                    if review_averages
                    else None
                ),
                "response_variants": len(
                    {review.response_sha256 for review in reviews}
                ),
                "flag_counts": dict(sorted(flags.items())),
                "trend": build_case_review_trend(reviews),
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
        trend = case["trend"]
        if trend is None:
            continue
        changed = "변경됨" if trend["response_changed"] else "동일함"
        lines.append(
            "  수정 전후 평균: "
            f"{trend['first_average_score']} -> {trend['latest_average_score']} "
            f"(변화 {trend['average_score_delta']}, 답변 {changed})"
        )
        repeated_dimensions = trend["repeated_below_target_dimensions"]
        if repeated_dimensions:
            labels = ", ".join(
                f"{dimension}({trend['dimension_trends'][dimension]['below_target_count']}회)"
                for dimension in repeated_dimensions
            )
            lines.append(f"  반복된 4점 미만 항목: {labels}")
        if trend["repeated_flags"]:
            labels = ", ".join(
                f"{flag}({count}회)"
                for flag, count in trend["repeated_flags"].items()
            )
            lines.append(f"  반복된 문제 표시: {labels}")
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
