from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.schemas.accessibility import MobilityProfile
from app.schemas.common import ResponseStatus
from app.services.accessibility_service import AccessibilityService

COVERAGE_CASES = Path(__file__).resolve().parents[1] / "fixtures" / "coverage_cases.yaml"


def _coverage_cases() -> dict[str, Any]:
    return yaml.safe_load(COVERAGE_CASES.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "case",
    _coverage_cases()["trip_cases"],
    ids=lambda case: case["name"],
)
async def test_mock_mode_trip_coverage_cases(case: dict[str, Any]) -> None:
    service = AccessibilityService()
    profile = MobilityProfile.model_validate(case["mobility_profile"])

    result = await service.check_accessible_trip(
        case["origin"],
        case["destination"],
        profile,
    )

    assert result.status == ResponseStatus(case["expected_status"])
    assert result.risk_level == case["expected_risk_level"]
    assert result.selected_route is not None
    assert result.route_candidates
    assert len(result.accessible_facilities) <= len(result.selected_route.stations)
    assert result.evidence_sources
    assert result.last_checked_at is not None
    assert len(result.model_dump_json()) < 15000
    assert result.accessibility_checks
    assert {check.role for check in result.accessibility_checks}.issubset(
        {"origin", "transfer", "destination"}
    )

    reason_codes = {reason.code for reason in result.risk_reasons}
    for expected_code in case.get("expected_risk_reason_codes", []):
        assert expected_code in reason_codes
    if result.user_message.startswith("판단: 주의 필요"):
        assert result.risk_level != "LOW"
        assert result.risk_score >= 35
    if result.user_message_summary.judgement == "주의 필요":
        assert result.risk_level in {"CAUTION", "HIGH", "UNKNOWN"}
    if profile.need_accessible_restroom and any(
        check.restroom_available is False for check in result.accessibility_checks
    ):
        assert "판단: 주의 필요" in result.user_message
        assert "장애인화장실 미확인 역" in result.user_message


@pytest.mark.parametrize(
    "case",
    _coverage_cases()["clarification_trip_cases"],
    ids=lambda case: case["name"],
)
async def test_mock_mode_ambiguous_trip_returns_clarification_failure(
    case: dict[str, Any],
) -> None:
    service = AccessibilityService()
    profile = MobilityProfile.model_validate(case["mobility_profile"])

    result = await service.check_accessible_trip(
        case["origin"],
        case["destination"],
        profile,
    )

    assert result.status == ResponseStatus(case["expected_status"])
    assert result.risk_level == case["expected_risk_level"]
    assert result.selected_route is None
    assert result.clarification_needed is True
    assert result.questions
    assert result.available_partial_info
    assert any(source.source_name == "station_resolution" for source in result.failed_sources)
