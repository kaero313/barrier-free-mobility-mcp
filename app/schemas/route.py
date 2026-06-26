from __future__ import annotations

from pydantic import BaseModel, Field


class RouteSegment(BaseModel):
    from_station: str
    to_station: str
    line: str | None = None
    transfer: bool = False
    estimated_minutes: int | None = None


class RouteCandidate(BaseModel):
    route_id: str
    origin: str
    destination: str
    segments: list[RouteSegment]
    transfer_count: int = 0
    estimated_minutes: int | None = None
    distance_meters: int | None = None
    stations: list[str] = Field(default_factory=list)
    raw_summary: str | None = None

