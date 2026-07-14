from __future__ import annotations

from app.schemas.route import RouteCandidate, RouteSegment
from app.services.route_candidate_enrichment import add_same_line_direct_candidate
from app.services.station_context import StationLookupContext


def test_does_not_invent_same_line_candidate_without_verified_topology() -> None:
    transfer_route = _route("api-transfer", transfer_count=2)
    origin = StationLookupContext("홍대입구", line="2", station_id="0239")
    destination = StationLookupContext("삼성", line="02호선", station_id="0219")

    routes, added = add_same_line_direct_candidate(
        [transfer_route],
        origin,
        destination,
    )

    assert routes == [transfer_route]
    assert added is None


def test_adds_same_line_candidate_with_verified_station_path() -> None:
    transfer_route = _route("api-transfer", transfer_count=2)
    origin = StationLookupContext("홍대입구", line="2", station_id="0239")
    destination = StationLookupContext("삼성", line="02호선", station_id="0219")

    routes, added = add_same_line_direct_candidate(
        [transfer_route],
        origin,
        destination,
        verified_station_path=["홍대입구", "신도림", "강남", "삼성"],
    )

    assert added is routes[0]
    assert added is not None
    assert added.transfer_count == 0
    assert added.segments[0].line == "2호선"
    assert added.stations == ["홍대입구", "신도림", "강남", "삼성"]
    assert [(segment.from_station, segment.to_station) for segment in added.segments] == [
        ("홍대입구", "신도림"),
        ("신도림", "강남"),
        ("강남", "삼성"),
    ]
    assert routes[1] == transfer_route


def test_rejects_verified_path_with_wrong_endpoints() -> None:
    transfer_route = _route("api-transfer", transfer_count=2)

    routes, added = add_same_line_direct_candidate(
        [transfer_route],
        StationLookupContext("홍대입구", line="2"),
        StationLookupContext("삼성", line="2"),
        verified_station_path=["홍대입구", "강남"],
    )

    assert routes == [transfer_route]
    assert added is None


def test_does_not_duplicate_existing_no_transfer_candidate() -> None:
    direct_route = _route("api-direct", transfer_count=0)
    origin = StationLookupContext("홍대입구", line="2")
    destination = StationLookupContext("삼성", line="2")

    routes, added = add_same_line_direct_candidate(
        [direct_route],
        origin,
        destination,
    )

    assert routes == [direct_route]
    assert added is None


def test_does_not_add_candidate_for_different_or_unknown_lines() -> None:
    transfer_route = _route("api-transfer", transfer_count=1)

    different, different_added = add_same_line_direct_candidate(
        [transfer_route],
        StationLookupContext("서울역", line="1"),
        StationLookupContext("삼성", line="2"),
    )
    unknown, unknown_added = add_same_line_direct_candidate(
        [transfer_route],
        StationLookupContext("서울역", line=None),
        StationLookupContext("시청", line="1"),
    )

    assert different == [transfer_route]
    assert different_added is None
    assert unknown == [transfer_route]
    assert unknown_added is None


def _route(route_id: str, *, transfer_count: int) -> RouteCandidate:
    return RouteCandidate(
        route_id=route_id,
        origin="홍대입구",
        destination="삼성",
        segments=[
            RouteSegment(
                from_station="홍대입구",
                to_station="삼성",
                line="2호선",
                transfer=transfer_count > 0,
            )
        ],
        transfer_count=transfer_count,
        stations=["홍대입구", "삼성"],
    )
