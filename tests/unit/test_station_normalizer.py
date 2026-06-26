from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.normalizers.helpers import normalize_line_name, normalize_station_name
from app.normalizers.station_normalizer import StationNormalizer

COVERAGE_CASES = Path(__file__).resolve().parents[1] / "fixtures" / "coverage_cases.yaml"


def _coverage_cases() -> dict[str, Any]:
    return yaml.safe_load(COVERAGE_CASES.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "case",
    _coverage_cases()["station_cases"],
    ids=lambda case: case["name"],
)
def test_station_normalizer_coverage_cases(case: dict[str, Any]) -> None:
    normalizer = StationNormalizer()

    result = normalizer.resolve(case["query"])

    if case.get("needs_clarification"):
        assert result.matched_station is None
        assert result.needs_clarification is True
        if "expected_candidate_count" in case:
            assert len(result.candidates) == case["expected_candidate_count"]
        return

    assert result.matched_station is not None
    assert result.matched_station.station_name == case["expected_station"]
    assert result.matched_station.line == case["expected_line"]
    assert result.needs_clarification is False


def test_line_name_and_station_text_normalization_regression() -> None:
    assert normalize_line_name("2호선") == "2"
    assert normalize_line_name("Line 2") == "2"
    assert normalize_line_name("02") == "2"
    assert normalize_line_name("2") == "2"
    assert normalize_station_name("삼성(무역센터)") == "삼성"
    assert normalize_station_name("삼성（무역센터）") == "삼성"
    assert normalize_station_name("강남역") == "강남"
