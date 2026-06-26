from __future__ import annotations

from app.normalizers.helpers import normalize_line_name
from app.schemas.accessibility import MobilityProfile
from app.schemas.common import ResponseStatus
from app.services.accessibility_service import AccessibilityService
from app.services.facility_service import FacilityService


async def test_facility_service_resolves_embedded_line_in_station_query() -> None:
    service = FacilityService()

    result = await service.get_station_facilities("9호선 고속터미널")

    assert result.value
    assert {facility.facility_id for facility in result.value} == {"EXPRESS-EV-1"}
    assert all(normalize_line_name(facility.line) == "9" for facility in result.value)


async def test_facility_service_explicit_line_filters_transfer_station() -> None:
    service = FacilityService()

    result = await service.get_elevator_status("서울역", line="1")

    assert result.value
    assert all(facility.station_name == "서울역" for facility in result.value)
    assert all(normalize_line_name(facility.line) == "1" for facility in result.value)


async def test_facility_service_broad_lookup_still_works_for_ambiguous_station() -> None:
    service = FacilityService()

    result = await service.get_station_facilities("고속터미널")

    assert result.value
    assert any(facility.station_name == "고속터미널" for facility in result.value)


async def test_accessible_trip_preserves_line_for_line_aware_endpoints() -> None:
    service = AccessibilityService()
    profile = MobilityProfile(
        wheelchair=True,
        can_use_stairs=False,
        can_use_escalator=False,
        need_elevator_only=True,
    )

    result = await service.check_accessible_trip(
        "9호선 고속터미널",
        "9호선 여의도",
        profile,
    )

    assert result.status == ResponseStatus.SUCCESS
    checks = {check.station: check for check in result.accessibility_checks}
    assert checks["고속터미널"].line == "9"
    assert checks["고속터미널"].station_id == "0923"
    assert checks["여의도"].line == "9"
    assert checks["여의도"].station_id == "0915"
    assert all(
        normalize_line_name(facility.line) == "9"
        for facility in result.accessible_facilities
    )


async def test_accessible_trip_preserves_line_one_for_seoul_to_cityhall() -> None:
    service = AccessibilityService()
    profile = MobilityProfile(
        wheelchair=True,
        can_use_stairs=False,
        can_use_escalator=False,
        need_elevator_only=True,
    )

    result = await service.check_accessible_trip(
        "1호선 서울역",
        "1호선 시청",
        profile,
    )

    assert result.status == ResponseStatus.SUCCESS
    checks = {check.station: check for check in result.accessibility_checks}
    assert checks["서울역"].line == "1"
    assert checks["서울역"].station_id == "0150"
    assert checks["시청"].line == "1"
    assert checks["시청"].station_id == "0132"


async def test_accessible_trip_keeps_ambiguous_transfer_station_clarification() -> None:
    service = AccessibilityService()

    result = await service.check_accessible_trip(
        "고속터미널",
        "여의도",
        MobilityProfile(wheelchair=True, can_use_stairs=False, need_elevator_only=True),
    )

    assert result.status == ResponseStatus.NEEDS_CLARIFICATION
    assert result.clarification_needed is True
