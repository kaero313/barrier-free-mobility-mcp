from __future__ import annotations

from typing import Any

from app.normalizers.helpers import as_int, as_str, pick, rows_from_raw, split_station_path
from app.schemas.route import RouteCandidate, RouteSegment


def _normalize_segments(value: Any, stations: list[str]) -> list[RouteSegment]:
    if isinstance(value, list):
        segments: list[RouteSegment] = []
        for row in value:
            if not isinstance(row, dict):
                continue
            from_station = as_str(pick(row, ("from_station", "from", "출발역")))
            to_station = as_str(pick(row, ("to_station", "to", "도착역")))
            if not from_station or not to_station:
                continue
            segments.append(
                RouteSegment(
                    from_station=from_station,
                    to_station=to_station,
                    line=as_str(pick(row, ("line", "line_name", "호선", "노선"))),
                    transfer=bool(pick(row, ("transfer", "환승"), False)),
                    estimated_minutes=as_int(
                        pick(row, ("estimated_minutes", "minutes", "소요시간"))
                    ),
                )
            )
        if segments:
            return segments

    generated: list[RouteSegment] = []
    for index in range(len(stations) - 1):
        generated.append(
            RouteSegment(
                from_station=stations[index],
                to_station=stations[index + 1],
                transfer=index > 0,
            )
        )
    return generated


def normalize_route_candidates(
    raw: dict[str, Any] | list[dict[str, Any]],
    *,
    origin: str | None = None,
    destination: str | None = None,
) -> list[RouteCandidate]:
    shortest_route = _normalize_shortest_route_document(raw, origin=origin, destination=destination)
    if shortest_route is not None:
        return [shortest_route]

    candidates: list[RouteCandidate] = []
    for index, row in enumerate(rows_from_raw(raw), start=1):
        row_origin = as_str(pick(row, ("origin", "from", "출발역", "start_station"))) or origin
        row_destination = as_str(
            pick(row, ("destination", "to", "도착역", "end_station"))
        ) or destination
        if not row_origin or not row_destination:
            continue
        if origin and row_origin != origin:
            continue
        if destination and row_destination != destination:
            continue

        raw_stations = pick(
            row,
            (
                "stations",
                "station_list",
                "경유역",
                "path",
                "route",
                "ROUTE",
                "STN_LIST",
                "TRANSFER_PATH",
            ),
        )
        stations = split_station_path(raw_stations)
        if not stations:
            stations = [row_origin, row_destination]

        segments = _normalize_segments(pick(row, ("segments", "구간")), stations)
        candidates.append(
            RouteCandidate(
                route_id=as_str(pick(row, ("route_id", "id", "경로id"))) or f"route-{index}",
                origin=row_origin,
                destination=row_destination,
                segments=segments,
                transfer_count=as_int(
                    pick(
                        row,
                        (
                            "transfer_count",
                            "transfers",
                            "환승횟수",
                            "TRANSIT_COUNT",
                            "TRANSFER_CNT",
                        ),
                    )
                )
                or 0,
                estimated_minutes=as_int(
                    pick(row, ("estimated_minutes", "minutes", "소요시간", "TIME", "TRVL_TIME"))
                ),
                distance_meters=as_int(
                    pick(row, ("distance_meters", "distance", "거리", "DISTANCE", "DIST"))
                ),
                stations=stations,
                raw_summary=as_str(pick(row, ("raw_summary", "summary", "요약"))),
            )
        )
    return candidates


def _normalize_shortest_route_document(
    raw: dict[str, Any] | list[dict[str, Any]],
    *,
    origin: str | None,
    destination: str | None,
) -> RouteCandidate | None:
    if not isinstance(raw, dict):
        return None
    body = raw.get("document", {}).get("body") if isinstance(raw.get("document"), dict) else None
    if not isinstance(body, dict) or "paths" not in body:
        return None

    path_container = body.get("paths")
    path_rows = path_container.get("path") if isinstance(path_container, dict) else path_container
    if isinstance(path_rows, dict):
        path_rows = [path_rows]
    if not isinstance(path_rows, list):
        path_rows = []

    segments: list[RouteSegment] = []
    stations: list[str] = []
    for row in path_rows:
        if not isinstance(row, dict):
            continue
        departure = row.get("dptreStn")
        arrival = row.get("arvlStn")
        from_station = _station_name(departure)
        to_station = _station_name(arrival)
        if not from_station or not to_station:
            continue
        line = _line_name(departure) or _line_name(arrival)
        segments.append(
            RouteSegment(
                from_station=from_station,
                to_station=to_station,
                line=line,
                transfer=str(row.get("trsitYn") or "").strip().upper() == "Y",
                estimated_minutes=_seconds_to_minutes(as_int(row.get("reqHr"))),
            )
        )
        if not stations:
            stations.append(from_station)
        if stations[-1] != to_station:
            stations.append(to_station)

    route_origin = origin or (stations[0] if stations else None)
    route_destination = destination or (stations[-1] if stations else None)
    if not route_origin or not route_destination:
        return None

    return RouteCandidate(
        route_id="shortest-route-live",
        origin=route_origin,
        destination=route_destination,
        segments=segments or [
            RouteSegment(from_station=route_origin, to_station=route_destination)
        ],
        transfer_count=as_int(body.get("trsitNmtm")) or 0,
        estimated_minutes=_seconds_to_minutes(as_int(body.get("totalReqHr"))),
        distance_meters=as_int(body.get("totalDstc")),
        stations=stations or [route_origin, route_destination],
        raw_summary=(
            f"{route_origin}에서 {route_destination}까지 "
            f"{as_int(body.get('trsitNmtm')) or 0}회 환승 경로"
        ),
    )


def _station_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return as_str(pick(value, ("stnNm", "station_name", "STN_NM")))
    return as_str(value)


def _line_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return as_str(pick(value, ("lineNm", "line", "LINE_NM")))
    return None


def _seconds_to_minutes(value: int | None) -> int | None:
    if value is None:
        return None
    return max(1, (value + 59) // 60)
