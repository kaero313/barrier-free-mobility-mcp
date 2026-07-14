from __future__ import annotations

from pydantic import BaseModel, Field


class Station(BaseModel):
    station_id: str | None = None
    station_name: str
    line: str | None = None
    operator: str | None = None
    aliases: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class StationResolutionResult(BaseModel):
    query: str
    matched_station: Station | None
    candidates: list[Station] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_message: str | None = None
