from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.normalizers.helpers import normalize_line_name
from app.schemas.route import RouteCandidate


@dataclass(frozen=True)
class RouteAccuracyIssue:
    code: str
    message: str


def check_route_accuracy(
    route: RouteCandidate,
    case: dict[str, Any],
) -> list[RouteAccuracyIssue]:
    issues: list[RouteAccuracyIssue] = []

    expected_transfer_count = case.get("expected_transfer_count")
    if (
        expected_transfer_count is not None
        and route.transfer_count != expected_transfer_count
    ):
        issues.append(
            RouteAccuracyIssue(
                code="unexpected_transfer_count",
                message=(
                    f"expected {expected_transfer_count} transfers, "
                    f"got {route.transfer_count}"
                ),
            )
        )

    expected_lines = {
        line
        for line in (normalize_line_name(value) for value in case.get("expected_lines", []))
        if line is not None
    }
    route_lines = {
        line
        for line in (normalize_line_name(segment.line) for segment in route.segments)
        if line is not None
    }
    if expected_lines and not route_lines:
        issues.append(
            RouteAccuracyIssue(
                code="missing_line",
                message="route segments did not include line information",
            )
        )
    elif expected_lines and not route_lines.issubset(expected_lines):
        issues.append(
            RouteAccuracyIssue(
                code="unexpected_line",
                message=(
                    f"expected lines {sorted(expected_lines)}, "
                    f"got {sorted(route_lines)}"
                ),
            )
        )

    stations = route.stations or [route.origin, route.destination]
    expected_first = case.get("expected_first_station")
    if expected_first and (not stations or not _same_station(stations[0], expected_first)):
        actual_first = stations[0] if stations else None
        issues.append(
            RouteAccuracyIssue(
                code="unexpected_first_station",
                message=f"expected first station {expected_first}, got {actual_first}",
            )
        )

    expected_last = case.get("expected_last_station")
    if expected_last and (not stations or not _same_station(stations[-1], expected_last)):
        actual_last = stations[-1] if stations else None
        issues.append(
            RouteAccuracyIssue(
                code="unexpected_last_station",
                message=f"expected last station {expected_last}, got {actual_last}",
            )
        )

    for required_station in case.get("required_stations", []):
        if not any(_same_station(station, required_station) for station in stations):
            issues.append(
                RouteAccuracyIssue(
                    code="missing_required_station",
                    message=f"required station {required_station} was not present",
                )
            )

    transfer_stations = _route_transfer_stations(route)
    for forbidden_station in case.get("forbidden_transfer_stations", []):
        if any(_same_station(station, forbidden_station) for station in transfer_stations):
            issues.append(
                RouteAccuracyIssue(
                    code="forbidden_station_present",
                    message=f"unexpected transfer station {forbidden_station} was present",
                )
            )

    return issues


def route_station_summary(route: RouteCandidate, *, max_stations: int = 8) -> str:
    stations = route.stations or [route.origin, route.destination]
    if len(stations) <= max_stations:
        return " → ".join(stations)
    head_count = max(1, max_stations // 2)
    tail_count = max(1, max_stations - head_count - 1)
    return " → ".join([*stations[:head_count], "…", *stations[-tail_count:]])


def route_line_summary(route: RouteCandidate) -> str:
    lines = []
    seen: set[str] = set()
    for segment in route.segments:
        normalized = normalize_line_name(segment.line)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        lines.append(f"{normalized}호선")
    return ", ".join(lines) if lines else "미확인"


def _same_station(left: str, right: str) -> bool:
    return _clean_station(left) == _clean_station(right)


def _route_transfer_stations(route: RouteCandidate) -> list[str]:
    transfer_stations: list[str] = []
    for segment in route.segments:
        if segment.transfer:
            transfer_stations.extend([segment.from_station, segment.to_station])
    if transfer_stations:
        return transfer_stations
    if route.transfer_count > 0 and len(route.stations) > 2:
        return route.stations[1:-1]
    return []


def _clean_station(value: str) -> str:
    cleaned = str(value).strip().replace(" ", "")
    cleaned = re.sub(r"\([^)]*\)$", "", cleaned)
    cleaned = re.sub(r"（[^）]*）$", "", cleaned)
    return cleaned[:-1] if cleaned.endswith("역") else cleaned
