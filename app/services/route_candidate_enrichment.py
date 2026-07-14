from __future__ import annotations

from app.normalizers.helpers import normalize_line_name, normalize_station_name
from app.schemas.route import RouteCandidate, RouteSegment
from app.services.station_context import StationLookupContext


def add_same_line_direct_candidate(
    routes: list[RouteCandidate],
    origin: StationLookupContext,
    destination: StationLookupContext,
    *,
    verified_station_path: list[str] | None = None,
) -> tuple[list[RouteCandidate], RouteCandidate | None]:
    """Add a direct candidate only when authoritative topology supplies its path."""

    origin_line = normalize_line_name(origin.line)
    destination_line = normalize_line_name(destination.line)
    if not origin_line or origin_line != destination_line:
        return routes, None
    if any(route.transfer_count == 0 for route in routes):
        return routes, None
    if not verified_station_path:
        return routes, None

    station_path = _dedupe_station_path(verified_station_path)
    if len(station_path) < 2:
        return routes, None
    if normalize_station_name(station_path[0]) != normalize_station_name(
        origin.station_name
    ):
        return routes, None
    if normalize_station_name(station_path[-1]) != normalize_station_name(
        destination.station_name
    ):
        return routes, None

    direct = RouteCandidate(
        route_id=(
            "same-line:"
            f"{origin_line}:"
            f"{origin.station_id or normalize_station_name(origin.station_name)}:"
            f"{destination.station_id or normalize_station_name(destination.station_name)}"
        ),
        origin=origin.station_name,
        destination=destination.station_name,
        segments=[
            RouteSegment(
                from_station=from_station,
                to_station=to_station,
                line=f"{origin_line}호선",
                transfer=False,
            )
            for from_station, to_station in zip(
                station_path,
                station_path[1:],
                strict=False,
            )
        ],
        transfer_count=0,
        stations=station_path,
        raw_summary=f"{origin_line}호선 topology 확인 무환승 이동 후보",
    )
    return [direct, *routes], direct


def _dedupe_station_path(stations: list[str]) -> list[str]:
    deduped: list[str] = []
    for station in stations:
        if deduped and normalize_station_name(deduped[-1]) == normalize_station_name(
            station
        ):
            continue
        deduped.append(station)
    return deduped
