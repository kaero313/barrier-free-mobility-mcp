from __future__ import annotations

from app.schemas.accessibility import AccessibleRestroomRequirement, MobilityProfile
from app.schemas.common import ResponseStatus
from app.services.accessibility_service import AccessibilityService


async def test_any_route_station_requirement_accepts_one_confirmed_restroom() -> None:
    service = AccessibilityService()

    result = await service.check_accessible_trip(
        "홍대입구",
        "삼성",
        MobilityProfile(
            wheelchair=True,
            can_use_stairs=False,
            can_use_escalator=False,
            need_elevator_only=True,
            need_accessible_restroom=True,
            accessible_restroom_requirement=AccessibleRestroomRequirement.ANY_ROUTE_STATION,
        ),
    )

    assert result.status == ResponseStatus.SUCCESS
    assert not any(
        reason.code == "no_accessible_restroom_when_required"
        for reason in result.risk_reasons
    )
    assert all(check.restroom_required is False for check in result.accessibility_checks)
    assert "장애인화장실 미확인(필수)" not in result.user_message


async def test_destination_requirement_marks_destination_as_required() -> None:
    service = AccessibilityService()

    result = await service.check_accessible_trip(
        "홍대입구",
        "삼성",
        MobilityProfile(
            wheelchair=True,
            can_use_stairs=False,
            can_use_escalator=False,
            need_elevator_only=True,
            need_accessible_restroom=True,
            accessible_restroom_requirement=AccessibleRestroomRequirement.DESTINATION,
        ),
    )

    checks = {check.role: check for check in result.accessibility_checks}

    assert checks["origin"].restroom_required is False
    assert checks["destination"].restroom_required is True
    assert "도착역:" in result.user_message
    assert "삼성역" in result.user_message
    assert "장애인화장실 확인(필수)" in result.user_message
    assert "사용자 조건 반영" not in result.user_message


async def test_destination_requirement_missing_restroom_applies_caution() -> None:
    service = AccessibilityService()

    result = await service.check_accessible_trip(
        "9호선 고속터미널",
        "9호선 여의도",
        MobilityProfile(
            wheelchair=True,
            can_use_stairs=False,
            can_use_escalator=False,
            need_elevator_only=True,
            need_accessible_restroom=True,
            accessible_restroom_requirement=AccessibleRestroomRequirement.DESTINATION,
        ),
    )

    assert result.risk_level in {"CAUTION", "HIGH", "UNKNOWN"}
    assert any(
        reason.code == "no_accessible_restroom_when_required"
        and reason.station_name == "여의도"
        for reason in result.risk_reasons
    )
    destination_check = next(
        check for check in result.accessibility_checks if check.role == "destination"
    )
    assert destination_check.restroom_required is True
    assert destination_check.restroom_available is False
    assert "장애인화장실 미확인(필수)" in result.user_message


async def test_generate_accessibility_brief_uses_same_restroom_policy() -> None:
    service = AccessibilityService()

    result = await service.generate_accessibility_brief(
        "홍대입구",
        "삼성",
        MobilityProfile(
            wheelchair=True,
            can_use_stairs=False,
            can_use_escalator=False,
            need_elevator_only=True,
            need_accessible_restroom=True,
            accessible_restroom_requirement=AccessibleRestroomRequirement.DESTINATION,
        ),
    )

    assert result.user_message
    assert result.user_message_summary.judgement
    assert any(check.restroom_required is True for check in result.accessibility_checks)
