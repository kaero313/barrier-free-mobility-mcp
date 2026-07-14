from __future__ import annotations

from app.core.config import AppMode, Settings
from app.normalizers.helpers import normalize_station_name
from app.schemas.route import RouteCandidate, RouteSegment
from app.services.facility_service import FacilityService
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
    assert express.operator == "seoul_metro_line9"
    assert seoul.station_name == "서울역"
    assert seoul.line == "1"
    assert seoul.station_id == "0150"
    assert samsung.station_name == "삼성"
    assert samsung.line == "2"
    assert samsung.station_id == "0219"
    assert samsung.operator == "seoul_metro"


def test_station_context_preserves_supported_line_nine_operator() -> None:
    context = resolve_station_context(StationService(), "9호선 봉은사")

    assert context.station_name == "봉은사"
    assert context.line == "9"
    assert context.station_id == "0929"
    assert context.operator == "seoul_metro"


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


def test_station_context_does_not_pair_wrong_line_with_other_line_station_id() -> None:
    context = resolve_station_context(StationService(), "9호선 삼성")

    assert context.station_name == "삼성"
    assert context.line == "9"
    assert context.station_id is None
    assert context.needs_clarification is True
    assert context.candidate_lines == ("2",)
    assert "2호선" in (context.clarification_message or "")


async def test_facility_service_skips_lookup_for_wrong_station_line() -> None:
    service = FacilityService(
        settings=Settings(_env_file=None, app_mode=AppMode.MOCK),
    )

    result = await service.get_elevator_status("9호선 삼성")

    assert result.value == []
    assert result.data_sources == []
    assert result.failed_sources[0].source_name == "station_resolution"
    assert "2호선" in result.limitations[0]


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
