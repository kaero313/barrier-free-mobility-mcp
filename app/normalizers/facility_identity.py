from __future__ import annotations

from app.normalizers.helpers import normalize_line_name, normalize_station_name
from app.schemas.facility import AccessibleFacility


def facility_record_identity(facility: AccessibleFacility) -> tuple[str, ...] | None:
    """Identify one source record without merging uncertain physical facilities."""

    source = _normalize_text(facility.source_name)
    station = normalize_station_name(facility.station_name) or ""
    line = normalize_line_name(facility.line) or ""
    facility_type = str(facility.facility_type)
    status = str(facility.status)
    raw_status = _normalize_text(facility.raw_status_text)

    facility_id = _normalize_text(facility.facility_id)
    if facility_id:
        return (
            "id",
            source,
            station,
            line,
            facility_type,
            facility_id,
            status,
            raw_status,
        )

    facility_name = _normalize_text(facility.facility_name)
    location = _normalize_text(facility.location_description)
    operation_section = _normalize_text(facility.operation_section)
    if not any((facility_name, location, operation_section)):
        return None
    return (
        "fallback",
        source,
        station,
        line,
        facility_type,
        facility_name,
        location,
        operation_section,
        status,
        raw_status,
    )


def facility_display_identity(facility: AccessibleFacility) -> tuple[str, ...] | None:
    """Match likely duplicate display rows across source datasets conservatively."""

    station = normalize_station_name(facility.station_name) or ""
    line = normalize_line_name(facility.line) or ""
    facility_type = str(facility.facility_type)
    location = _normalize_text(facility.location_description)
    name = _normalize_text(facility.facility_name)
    if location:
        return (station, line, facility_type, "location", location)
    if name:
        return (station, line, facility_type, "name", name)
    return None


def _normalize_text(value: object) -> str:
    return "".join(str(value or "").strip().lower().split())
