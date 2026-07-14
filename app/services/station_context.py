from __future__ import annotations

import re
from dataclasses import dataclass

from app.normalizers.helpers import normalize_line_name, normalize_station_name
from app.schemas.route import RouteCandidate
from app.services.station_service import StationService

LINE_PATTERN = re.compile(
    r"(?:(?:line)\s*(?P<line_after>\d+)|(?P<line_before>\d+)\s*호선)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StationLookupContext:
    station_name: str
    line: str | None = None
    station_id: str | None = None
    operator: str | None = None
    query: str = ""
    needs_clarification: bool = False
    candidate_lines: tuple[str, ...] = ()
    clarification_message: str | None = None


def context_for_station(
    station: str,
    station_contexts: dict[str, StationLookupContext],
) -> StationLookupContext:
    key = normalize_station_name(station)
    if key and key in station_contexts:
        return station_contexts[key]
    return StationLookupContext(station_name=station)


def resolve_station_context(
    station_service: StationService,
    query: str,
    *,
    explicit_line: str | None = None,
) -> StationLookupContext:
    line = normalize_line_name(explicit_line) or _extract_line(query)
    station_query = _strip_line_marker(query)
    lookup_query = f"{line}호선 {station_query}" if line else query
    resolution = station_service.resolve_station(lookup_query)
    matched = resolution.matched_station
    if matched is not None:
        return StationLookupContext(
            station_name=matched.station_name,
            line=line or matched.line,
            station_id=matched.station_id,
            operator=matched.operator,
            query=query,
            needs_clarification=False,
        )

    fallback_station_name = _fallback_station_name(station_query, resolution)
    return StationLookupContext(
        station_name=fallback_station_name,
        line=line,
        station_id=None,
        query=query,
        needs_clarification=resolution.needs_clarification,
        candidate_lines=tuple(
            sorted({candidate.line for candidate in resolution.candidates if candidate.line})
        ),
        clarification_message=resolution.clarification_message,
    )


def build_route_station_contexts(
    *,
    station_service: StationService,
    routes: list[RouteCandidate],
    origin: StationLookupContext,
    destination: StationLookupContext,
) -> dict[str, StationLookupContext]:
    contexts: dict[str, StationLookupContext] = {}
    route_lines = _route_station_lines(routes)

    def add(context: StationLookupContext) -> None:
        key = normalize_station_name(context.station_name)
        if key:
            contexts[key] = context

    for station in _ordered_route_stations(routes):
        key = normalize_station_name(station)
        if not key:
            continue
        if key == normalize_station_name(origin.station_name):
            add(origin)
            continue
        if key == normalize_station_name(destination.station_name):
            add(destination)
            continue

        lines = route_lines.get(key, set())
        if len(lines) == 1:
            line = next(iter(lines))
            context = resolve_station_context(
                station_service,
                station,
                explicit_line=line,
            )
        else:
            context = resolve_station_context(station_service, station)
        add(context)

    add(origin)
    add(destination)
    return contexts


def route_line_mismatch_limitations(
    routes: list[RouteCandidate],
    *contexts: StationLookupContext,
) -> list[str]:
    route_lines = _route_station_lines(routes)
    limitations: list[str] = []
    for context in contexts:
        if context.line is None:
            continue
        key = normalize_station_name(context.station_name)
        if not key:
            continue
        lines = route_lines.get(key, set())
        if lines and context.line not in lines:
            route_line_text = ", ".join(f"{line}호선" for line in sorted(lines))
            limitations.append(
                f"{context.station_name} 입력 호선({context.line}호선)과 "
                f"경로 API 호선({route_line_text})이 다릅니다."
            )
    return limitations


def _extract_line(query: str) -> str | None:
    match = LINE_PATTERN.search(query)
    if not match:
        return None
    line = match.group("line_after") or match.group("line_before")
    return normalize_line_name(line)


def _strip_line_marker(query: str) -> str:
    stripped = LINE_PATTERN.sub("", query).strip()
    return stripped or query.strip()


def _fallback_station_name(query: str, resolution: object) -> str:
    candidates = getattr(resolution, "candidates", [])
    if candidates:
        return candidates[0].station_name
    return _strip_line_marker(query)


def _ordered_route_stations(routes: list[RouteCandidate]) -> list[str]:
    stations: list[str] = []
    seen: set[str] = set()
    for route in routes:
        route_stations = route.stations or [route.origin, route.destination]
        for station in route_stations:
            key = normalize_station_name(station)
            if not key or key in seen:
                continue
            seen.add(key)
            stations.append(station)
    return stations


def _route_station_lines(routes: list[RouteCandidate]) -> dict[str, set[str]]:
    station_lines: dict[str, set[str]] = {}
    for route in routes:
        for segment in route.segments:
            line = normalize_line_name(segment.line)
            if line is None:
                continue
            for station in (segment.from_station, segment.to_station):
                key = normalize_station_name(station)
                if key:
                    station_lines.setdefault(key, set()).add(line)
    return station_lines
