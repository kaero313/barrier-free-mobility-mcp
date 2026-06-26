from __future__ import annotations

from app.normalizers.helpers import normalize_station_name
from app.schemas.route import RouteCandidate, RouteSegment
from app.services.station_context import (
    build_route_station_contexts,
    resolve_station_context,
)
from app.services.station_service import StationService


def test_station_context_resolves_line_aware_inputs() -> None:
    station_service = StationService()

    express = resolve_station_context(station_service, "9호선 고속터미널")
    seoul = resolve_station_context(station_service, "Line 1 서울역")
    samsung = resolve_station_context(station_service, "2호선 삼성")

    assert express.station_name == "고속터미널"
    assert express.line == "9"
    assert express.station_id == "0923"
    assert seoul.station_name == "서울역"
    assert seoul.line == "1"
    assert seoul.station_id == "0150"
    assert samsung.station_name == "삼성"
    assert samsung.line == "2"
    assert samsung.station_id == "0219"


def test_station_context_explicit_line_overrides_embedded_line() -> None:
    context = resolve_station_context(
        StationService(),
        "9호선 고속터미널",
        explicit_line="7",
    )

    assert context.station_name == "고속터미널"
    assert context.line == "7"
    assert context.station_id == "0734"
    assert context.needs_clarification is False


def test_station_context_keeps_ambiguous_transfer_station_as_clarification() -> None:
    context = resolve_station_context(StationService(), "고속터미널")

    assert context.station_name == "고속터미널"
    assert context.line is None
    assert context.station_id is None
    assert context.needs_clarification is True


def test_route_station_contexts_infer_single_route_line() -> None:
    station_service = StationService()
    origin = resolve_station_context(station_service, "2호선 홍대입구")
    destination = resolve_station_context(station_service, "2호선 삼성")
    route = RouteCandidate(
        route_id="route",
        origin="홍대입구",
        destination="삼성",
        transfer_count=0,
        stations=["홍대입구", "강남", "삼성"],
        segments=[
            RouteSegment(from_station="홍대입구", to_station="강남", line="2호선"),
            RouteSegment(from_station="강남", to_station="삼성", line="2호선"),
        ],
    )

    contexts = build_route_station_contexts(
        station_service=station_service,
        routes=[route],
        origin=origin,
        destination=destination,
    )

    assert contexts["홍대입구"].line == "2"
    assert contexts["강남"].line == "2"
    assert contexts["강남"].station_id == "0222"
    assert contexts["삼성"].line == "2"


def test_route_station_contexts_use_broad_lookup_for_multi_line_station() -> None:
    station_service = StationService()
    origin = resolve_station_context(station_service, "1호선 서울역")
    destination = resolve_station_context(station_service, "2호선 을지로입구")
    route = RouteCandidate(
        route_id="route",
        origin="서울역",
        destination="을지로입구",
        transfer_count=1,
        stations=["서울역", "시청", "을지로입구"],
        segments=[
            RouteSegment(from_station="서울역", to_station="시청", line="1호선"),
            RouteSegment(from_station="시청", to_station="을지로입구", line="2호선"),
        ],
    )

    contexts = build_route_station_contexts(
        station_service=station_service,
        routes=[route],
        origin=origin,
        destination=destination,
    )

    assert contexts[normalize_station_name("서울역")].line == "1"
    assert contexts[normalize_station_name("시청")].line is None
    assert contexts[normalize_station_name("시청")].needs_clarification is True
