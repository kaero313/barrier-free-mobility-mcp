from __future__ import annotations

from app.normalizers.facility_identity import (
    facility_display_identity,
    facility_record_identity,
)
from app.normalizers.helpers import normalize_line_name, normalize_station_name
from app.schemas.accessibility import (
    AccessibilityEvidenceStatus,
    ElevatorEvidenceItem,
)
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType

OPERATIONAL_SOURCES = {None, "elevator_status"}


def build_elevator_evidence_items(
    facilities: list[AccessibleFacility],
) -> list[ElevatorEvidenceItem]:
    elevators = _dedupe_records(
        [
            facility
            for facility in facilities
            if facility.facility_type == FacilityType.ELEVATOR
        ]
    )
    operational = [
        facility for facility in elevators if facility.source_name in OPERATIONAL_SOURCES
    ]
    references = _dedupe_references(
        [
            facility
            for facility in elevators
            if facility.source_name not in OPERATIONAL_SOURCES
        ]
    )
    used_reference_indexes: set[int] = set()
    items: list[ElevatorEvidenceItem] = []

    for facility in operational:
        match_index, match_method = _match_reference(facility, references)
        reference = references[match_index] if match_index is not None else None
        if match_index is not None:
            used_reference_indexes.add(match_index)

        location = facility.location_description
        location_source = facility.source_name if location else None
        if location is None and reference is not None:
            location = reference.location_description
            location_source = reference.source_name

        operation_section = facility.operation_section
        if operation_section is None and reference is not None:
            operation_section = reference.operation_section

        items.append(
            ElevatorEvidenceItem(
                facility_id=(
                    facility.facility_id
                    or (reference.facility_id if reference is not None else None)
                ),
                facility_name=(
                    facility.facility_name
                    or (reference.facility_name if reference is not None else None)
                ),
                location=location,
                operation_section=operation_section,
                status=facility.status,
                status_verified=(
                    AccessibilityEvidenceStatus.CONFIRMED
                    if facility.status != FacilityStatus.UNKNOWN
                    else AccessibilityEvidenceStatus.UNVERIFIED
                ),
                status_source_name=facility.source_name,
                location_source_name=location_source,
                match_method=(
                    match_method
                    if match_method != "unmatched"
                    else "same_record"
                    if facility.location_description or facility.operation_section
                    else "unmatched"
                ),
            )
        )

    for index, reference in enumerate(references):
        if index in used_reference_indexes:
            continue
        items.append(
            ElevatorEvidenceItem(
                facility_id=reference.facility_id,
                facility_name=reference.facility_name,
                location=reference.location_description,
                operation_section=reference.operation_section,
                status=FacilityStatus.UNKNOWN,
                status_verified=AccessibilityEvidenceStatus.UNVERIFIED,
                location_source_name=reference.source_name,
                match_method="unmatched",
            )
        )

    return _dedupe_evidence_items(items)


def _match_reference(
    facility: AccessibleFacility,
    references: list[AccessibleFacility],
) -> tuple[int | None, str]:
    facility_id = _normalize_exact(facility.facility_id)
    if facility_id:
        id_matches = [
            index
            for index, reference in enumerate(references)
            if _normalize_exact(reference.facility_id) == facility_id
        ]
        if len(id_matches) == 1:
            return id_matches[0], "facility_id"

    facility_name = _normalize_exact(facility.facility_name)
    if facility_name:
        name_matches = [
            index
            for index, reference in enumerate(references)
            if _normalize_exact(reference.facility_name) == facility_name
        ]
        if len(name_matches) == 1:
            return name_matches[0], "exact_name"
    return None, "unmatched"


def _dedupe_records(
    facilities: list[AccessibleFacility],
) -> list[AccessibleFacility]:
    seen: set[tuple[str, ...]] = set()
    deduped: list[AccessibleFacility] = []
    for facility in facilities:
        identity = facility_record_identity(facility)
        if identity is not None and identity in seen:
            continue
        if identity is not None:
            seen.add(identity)
        deduped.append(facility)
    return deduped


def _dedupe_references(
    facilities: list[AccessibleFacility],
) -> list[AccessibleFacility]:
    deduped: list[AccessibleFacility] = []
    positions: dict[tuple[str, ...], int] = {}
    for facility in facilities:
        identity = _reference_identity(facility)
        if identity is None:
            deduped.append(facility)
            continue
        position = positions.get(identity)
        if position is None:
            positions[identity] = len(deduped)
            deduped.append(facility)
            continue
        if _evidence_richness(facility) > _evidence_richness(deduped[position]):
            deduped[position] = facility
    return deduped


def _reference_identity(facility: AccessibleFacility) -> tuple[str, ...] | None:
    facility_id = _normalize_exact(facility.facility_id)
    if facility_id:
        return (
            "id",
            normalize_station_name(facility.station_name) or "",
            normalize_line_name(facility.line) or "",
            facility_id,
        )
    return facility_display_identity(facility)


def _evidence_richness(facility: AccessibleFacility) -> int:
    return sum(
        value is not None
        for value in (
            facility.facility_id,
            facility.facility_name,
            facility.location_description,
            facility.operation_section,
        )
    )


def _dedupe_evidence_items(
    items: list[ElevatorEvidenceItem],
) -> list[ElevatorEvidenceItem]:
    seen: set[tuple[object, ...]] = set()
    deduped: list[ElevatorEvidenceItem] = []
    for item in items:
        key = (
            _normalize_exact(item.facility_id),
            _normalize_exact(item.facility_name),
            _normalize_exact(item.location),
            _normalize_exact(item.operation_section),
            item.status,
            item.status_source_name,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_exact(value: object) -> str:
    return "".join(str(value or "").strip().lower().split())
