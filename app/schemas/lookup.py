from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import DataSourceMeta, FailedSource, ResponseStatus
from app.schemas.facility import AccessibleFacility
from app.schemas.route import RouteCandidate


class LookupOutcome(StrEnum):
    DATA = "DATA"
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    STALE = "STALE"


class LookupMetadata(BaseModel):
    schema_version: Literal[2] = 2
    status: ResponseStatus
    outcome: LookupOutcome
    data_sources: list[DataSourceMeta] = Field(default_factory=list)
    failed_sources: list[FailedSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FacilityLookupResult(LookupMetadata):
    station: str
    line: str | None = None
    data: list[AccessibleFacility] = Field(
        default_factory=list,
        description=(
            "Normalized facility records. In schema version 1 this list was returned "
            "as the entire tool response."
        ),
    )


class RouteLookupResult(LookupMetadata):
    origin: str
    destination: str
    data: list[RouteCandidate] = Field(
        default_factory=list,
        description=(
            "Normalized route candidates. In schema version 1 this list was returned "
            "as the entire tool response."
        ),
    )
