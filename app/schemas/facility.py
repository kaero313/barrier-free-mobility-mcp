from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class FacilityType(StrEnum):
    ELEVATOR = "ELEVATOR"
    ESCALATOR = "ESCALATOR"
    WHEELCHAIR_LIFT = "WHEELCHAIR_LIFT"
    ACCESSIBLE_RESTROOM = "ACCESSIBLE_RESTROOM"
    RESTROOM = "RESTROOM"
    WHEELCHAIR_CHARGER = "WHEELCHAIR_CHARGER"
    UNKNOWN = "UNKNOWN"


class FacilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    UNKNOWN = "UNKNOWN"


class AccessibleFacility(BaseModel):
    facility_id: str | None = None
    facility_name: str | None = None
    station_name: str
    line: str | None = None
    facility_type: FacilityType
    status: FacilityStatus = FacilityStatus.UNKNOWN
    location_description: str | None = None
    operation_section: str | None = None
    source_name: str | None = None
    inside_gate: bool | None = None
    open_time: str | None = None
    has_emergency_bell: bool | None = None
    raw_status_text: str | None = None


class FacilityIssue(BaseModel):
    station_name: str
    line: str | None = None
    facility_type: FacilityType
    status: FacilityStatus
    severity: str
    reason: str
