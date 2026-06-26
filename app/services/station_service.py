from __future__ import annotations

from app.normalizers.station_normalizer import resolve_station
from app.schemas.station import StationResolutionResult


class StationService:
    def resolve_station(self, query: str) -> StationResolutionResult:
        return resolve_station(query)

