from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import process

from app.schemas.station import Station, StationResolutionResult

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
LINE_PATTERN = re.compile(
    r"(?:(?:line)\s*(?P<line_after>\d+)|(?P<line_before>\d+)\s*호선)",
    re.IGNORECASE,
)


def _clean_query(value: str) -> str:
    cleaned = value.strip().replace(" ", "")
    cleaned = re.sub(r"\([^)]*\)$", "", cleaned)
    cleaned = re.sub(r"（[^）]*）$", "", cleaned)
    return cleaned[:-1] if cleaned.endswith("역") else cleaned


def _extract_line(query: str) -> str | None:
    match = LINE_PATTERN.search(query)
    if not match:
        return None
    line = match.group("line_after") or match.group("line_before")
    if line is None:
        return None
    return str(int(line))


class StationNormalizer:
    def __init__(self, aliases_path: Path | None = None) -> None:
        self.aliases_path = aliases_path or DATA_DIR / "station_aliases.yaml"
        self.stations = self._load_stations()
        self._choices: dict[str, Station] = {}
        for station in self.stations:
            for choice in [station.station_name, *station.aliases]:
                self._choices[_clean_query(choice)] = station

    def _load_stations(self) -> list[Station]:
        data: dict[str, Any] = yaml.safe_load(self.aliases_path.read_text(encoding="utf-8"))
        return [Station(**row) for row in data.get("stations", [])]

    def resolve(self, query: str) -> StationResolutionResult:
        line = _extract_line(query)
        cleaned = _clean_query(LINE_PATTERN.sub("", query))

        exact_candidates = [
            station
            for station in self.stations
            if _clean_query(station.station_name) == cleaned
            or cleaned in {_clean_query(alias) for alias in station.aliases}
        ]
        if line:
            exact_candidates = [
                station for station in exact_candidates if station.line in {None, line}
            ] or exact_candidates

        if len(exact_candidates) == 1:
            return StationResolutionResult(
                query=query,
                matched_station=exact_candidates[0].model_copy(update={"confidence": 1.0}),
                candidates=[exact_candidates[0].model_copy(update={"confidence": 1.0})],
            )
        if len(exact_candidates) > 1:
            return StationResolutionResult(
                query=query,
                matched_station=None,
                candidates=[
                    station.model_copy(update={"confidence": 1.0})
                    for station in exact_candidates
                ],
                needs_clarification=True,
                clarification_message="호선 또는 역명을 더 구체적으로 입력하세요.",
            )

        matches = process.extract(cleaned, self._choices.keys(), limit=3, score_cutoff=65)
        candidates: list[Station] = []
        seen: set[tuple[str, str | None]] = set()
        for choice, score, _ in matches:
            station = self._choices[choice]
            if line and station.line not in {None, line}:
                continue
            identity = (station.station_name, station.line)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(station.model_copy(update={"confidence": round(score / 100, 2)}))

        matched = candidates[0] if candidates and candidates[0].confidence >= 0.8 else None
        return StationResolutionResult(
            query=query,
            matched_station=matched,
            candidates=candidates,
            needs_clarification=matched is None,
            clarification_message=None
            if matched
            else "일치하는 역을 확정하지 못했습니다. 역명과 호선을 함께 입력하세요.",
        )


DEFAULT_STATION_NORMALIZER = StationNormalizer()


def resolve_station(query: str) -> StationResolutionResult:
    return DEFAULT_STATION_NORMALIZER.resolve(query)
