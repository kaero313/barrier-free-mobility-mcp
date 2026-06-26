from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.schemas.accessibility import MobilityProfile
from app.services.accessibility_service import AccessibilityService
from app.services.route_accuracy import check_route_accuracy
from app.services.route_service import RouteService

ROUTE_ACCURACY_CASES = Path(__file__).resolve().parents[1] / "fixtures" / (
    "route_accuracy_cases.yaml"
)


def _route_accuracy_cases() -> dict[str, Any]:
    return yaml.safe_load(ROUTE_ACCURACY_CASES.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "case",
    _route_accuracy_cases()["strict_cases"],
    ids=lambda case: case["name"],
)
async def test_mock_route_service_keeps_strict_route_accuracy_cases(
    case: dict[str, Any],
) -> None:
    service = RouteService()

    result = await service.get_route_candidates(case["origin"], case["destination"])

    assert result.value
    best_route = min(
        result.value,
        key=lambda route: (
            route.transfer_count,
            route.estimated_minutes if route.estimated_minutes is not None else 9999,
        ),
    )
    assert check_route_accuracy(best_route, case) == []


async def test_mock_accessibility_trip_does_not_select_forbidden_hongdae_samsung_route() -> None:
    case = _route_accuracy_cases()["strict_cases"][0]
    service = AccessibilityService()
    profile = MobilityProfile(
        wheelchair=True,
        can_use_stairs=False,
        can_use_escalator=False,
        need_elevator_only=True,
        max_transfer_count=1,
    )

    result = await service.check_accessible_trip(
        case["origin"],
        case["destination"],
        profile,
    )

    assert result.selected_route is not None
    assert result.selected_route.transfer_count == 0
    assert check_route_accuracy(result.selected_route, case) == []
