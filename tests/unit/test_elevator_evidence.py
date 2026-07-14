from __future__ import annotations

from app.schemas.accessibility import AccessibilityEvidenceStatus
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.services.elevator_evidence import build_elevator_evidence_items


def test_exact_name_match_adds_reference_id_to_operational_record() -> None:
    operational = _facility(
        facility_id=None,
        name="승강기)엘리베이터-삼성 1번 출구측 외부#1",
        location=None,
        status=FacilityStatus.MAINTENANCE,
        source="elevator_status",
    )
    reference = _facility(
        facility_id="1042193",
        name="승강기)엘리베이터-삼성 1번 출구측 외부#1",
        location="1번 출입구",
        status=FacilityStatus.UNKNOWN,
        source="elevator_info",
    )

    items = build_elevator_evidence_items([operational, reference])

    assert len(items) == 1
    assert items[0].facility_id == "1042193"
    assert items[0].location == "1번 출입구"
    assert items[0].status == FacilityStatus.MAINTENANCE
    assert items[0].status_verified == AccessibilityEvidenceStatus.CONFIRMED
    assert items[0].match_method == "exact_name"


def test_facility_id_match_takes_priority_over_different_name() -> None:
    operational = _facility(
        facility_id="EL-1",
        name="실시간 명칭",
        location=None,
        status=FacilityStatus.AVAILABLE,
        source="elevator_status",
    )
    reference = _facility(
        facility_id="EL-1",
        name="정적 명칭",
        location="8번 출입구",
        status=FacilityStatus.UNKNOWN,
        source="elevator_info",
    )

    item = build_elevator_evidence_items([operational, reference])[0]

    assert item.location == "8번 출입구"
    assert item.match_method == "facility_id"


def test_ambiguous_exact_name_candidates_are_not_joined() -> None:
    operational = _facility(
        facility_id=None,
        name="중복 명칭",
        location=None,
        status=FacilityStatus.AVAILABLE,
        source="elevator_status",
    )
    references = [
        _facility(
            facility_id="EL-1",
            name="중복 명칭",
            location="1번 출입구",
            status=FacilityStatus.UNKNOWN,
            source="elevator_info",
        ),
        _facility(
            facility_id="EL-2",
            name="중복 명칭",
            location="8번 출입구",
            status=FacilityStatus.UNKNOWN,
            source="facility_info",
        ),
    ]

    items = build_elevator_evidence_items([operational, *references])

    assert len(items) == 3
    assert items[0].match_method == "unmatched"
    assert items[0].facility_id is None
    assert items[0].location is None
    assert {item.location for item in items[1:]} == {"1번 출입구", "8번 출입구"}


def test_duplicate_reference_id_is_emitted_once() -> None:
    operational = _facility(
        facility_id=None,
        name="동일 시설",
        location="4번 출입구",
        status=FacilityStatus.AVAILABLE,
        source="elevator_status",
    )
    first_reference = _facility(
        facility_id="EL-4",
        name="동일 시설",
        location="4번 출입구",
        status=FacilityStatus.AVAILABLE,
        source="elevator_info",
    )
    second_reference = first_reference.model_copy(update={"source_name": "facility_info"})

    items = build_elevator_evidence_items(
        [operational, first_reference, second_reference]
    )

    assert len(items) == 1
    assert items[0].facility_id == "EL-4"


def _facility(
    *,
    facility_id: str | None,
    name: str,
    location: str | None,
    status: FacilityStatus,
    source: str,
) -> AccessibleFacility:
    return AccessibleFacility(
        facility_id=facility_id,
        facility_name=name,
        station_name="삼성",
        line="2",
        facility_type=FacilityType.ELEVATOR,
        status=status,
        location_description=location,
        source_name=source,
    )
