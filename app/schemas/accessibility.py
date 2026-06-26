from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import CacheStatus, DataSourceMeta, FailedSource, ResponseStatus
from app.schemas.facility import AccessibleFacility, FacilityIssue, FacilityStatus
from app.schemas.route import RouteCandidate

RiskLevel = Literal["LOW", "CAUTION", "HIGH", "UNKNOWN"]
ConfidenceLevel = Literal["HIGH", "MEDIUM", "LOW"]
SourceType = Literal["public_api", "cache", "fixture", "internal"]

DEFAULT_SAFETY_NOTICE = (
    "엘리베이터 운행 상태는 바뀔 수 있으니 출발 직전 재확인하세요."
)


class AccessibleRestroomRequirement(StrEnum):
    ANY_ROUTE_STATION = "any_route_station"
    ORIGIN = "origin"
    TRANSFER = "transfer"
    DESTINATION = "destination"
    ORIGIN_OR_DESTINATION = "origin_or_destination"
    ALL_KEY_STATIONS = "all_key_stations"


class MobilityProfile(BaseModel):
    wheelchair: bool = False
    stroller: bool = False
    cane_or_walker: bool = False
    can_use_stairs: bool = True
    can_use_escalator: bool = True
    need_elevator_only: bool = False
    need_accessible_restroom: bool = False
    accessible_restroom_requirement: AccessibleRestroomRequirement = (
        AccessibleRestroomRequirement.ALL_KEY_STATIONS
    )
    need_wheelchair_charger: bool = False
    avoid_many_transfers: bool = True
    max_transfer_count: int | None = None


class RiskReason(BaseModel):
    code: str
    message: str
    score: int
    severity: Literal["LOW", "CAUTION", "HIGH", "UNKNOWN"]
    station_name: str | None = None


class AlternativeRoute(BaseModel):
    title: str
    description: str
    route: RouteCandidate | None = None
    expected_risk_level: RiskLevel = "UNKNOWN"


class EvidenceSource(BaseModel):
    source_name: str
    display_name: str
    source_type: SourceType
    checked_at: datetime | None = None
    cache_status: CacheStatus = CacheStatus.BYPASS
    staleness_seconds: int | None = None
    success: bool = True
    note: str | None = None


class UserMessageSummary(BaseModel):
    judgement: str = ""
    headline: str = ""
    route_overview: str = ""
    key_points: list[str] = Field(default_factory=list)
    source_summary: str = ""
    pre_departure_notice: str = DEFAULT_SAFETY_NOTICE
    reasons: list[str] = Field(default_factory=list)
    recommended_route: str | None = None
    mobility_condition_summary: list[str] = Field(default_factory=list)
    data_basis: list[str] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)


class AccessibilityCheck(BaseModel):
    station: str
    line: str | None = None
    station_id: str | None = None
    role: Literal["origin", "transfer", "destination"]
    elevator_status: FacilityStatus = FacilityStatus.UNKNOWN
    elevator_location: str | None = None
    restroom_available: bool | None = None
    restroom_required: bool | None = None
    notes: list[str] = Field(default_factory=list)


class AccessibilityResult(BaseModel):
    status: ResponseStatus = ResponseStatus.SUCCESS
    origin: str
    destination: str
    mobility_profile: MobilityProfile

    risk_level: RiskLevel
    risk_score: int = Field(ge=0, le=100)
    route_summary: str

    selected_route: RouteCandidate | None = None
    route_candidates: list[RouteCandidate] = Field(default_factory=list)
    risk_reasons: list[RiskReason] = Field(default_factory=list)
    caution_points: list[str] = Field(default_factory=list)

    blocked_facilities: list[FacilityIssue] = Field(default_factory=list)
    accessible_facilities: list[AccessibleFacility] = Field(default_factory=list)
    alternatives: list[AlternativeRoute] = Field(default_factory=list)

    data_sources: list[DataSourceMeta] = Field(default_factory=list)
    failed_sources: list[FailedSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    confidence_level: ConfidenceLevel = "LOW"
    confidence_reasons: list[str] = Field(default_factory=list)
    last_checked_at: datetime | None = None
    evidence_sources: list[EvidenceSource] = Field(
        default_factory=list,
        description=(
            "Supporting evidence metadata for API/fixture/cache sources. Use this to "
            "explain provenance, not as the primary end-user answer."
        ),
    )
    unverified_parts: list[str] = Field(default_factory=list)
    accessibility_checks: list[AccessibilityCheck] = Field(
        default_factory=list,
        description=(
            "Supporting station-level accessibility checks for origin, transfer, and "
            "destination stations."
        ),
    )
    clarification_needed: bool = False
    questions: list[str] = Field(default_factory=list)
    available_partial_info: list[str] = Field(default_factory=list)
    safety_notice: str = DEFAULT_SAFETY_NOTICE
    user_message: str = Field(
        default="",
        description=(
            "Canonical final answer for ordinary end users. MCP clients and LLM agents "
            "should display this text verbatim whenever possible."
        ),
    )
    user_message_summary: UserMessageSummary = Field(
        default_factory=UserMessageSummary,
        description=(
            "Structured support for user_message. Use only when a client must inspect "
            "or adapt the canonical final answer."
        ),
    )
