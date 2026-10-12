from __future__ import annotations

from pathlib import Path

import yaml

from scripts.test_mcp_client import COVERAGE_CASES

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "coverage_cases.yaml"


def test_coverage_smoke_cases_match_coverage_fixture() -> None:
    fixture = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))
    expected = [
        {
            "name": case["name"],
            "origin": case["origin"],
            "destination": case["destination"],
            "mobility_profile": case["mobility_profile"],
        }
        for case in fixture["trip_cases"]
    ]

    assert expected == COVERAGE_CASES
