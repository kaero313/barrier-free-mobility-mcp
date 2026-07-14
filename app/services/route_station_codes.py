from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.normalizers.helpers import normalize_line_name, normalize_station_name

ROUTE_STATION_CODE_FILE = (
    Path(__file__).resolve().parents[1] / "data" / "route_station_codes.yaml"
)


@lru_cache(maxsize=1)
def load_route_station_codes() -> dict[tuple[str, str], str]:
    payload = yaml.safe_load(ROUTE_STATION_CODE_FILE.read_text(encoding="utf-8")) or {}
    mappings: dict[tuple[str, str], str] = {}
    for row in payload.get("stations", []):
        station = normalize_station_name(row.get("station_name"))
        line = normalize_line_name(row.get("line"))
        code = str(row.get("route_station_code") or "").strip()
        if not station or not line or not code:
            continue
        key = (station, line)
        if key in mappings:
            raise ValueError(f"duplicate route station code mapping: {station}/{line}")
        mappings[key] = code
    return mappings


def resolve_route_station_code(station_name: str, line: str | None) -> str | None:
    station = normalize_station_name(station_name)
    normalized_line = normalize_line_name(line)
    if not station or not normalized_line:
        return None
    return load_route_station_codes().get((station, normalized_line))
