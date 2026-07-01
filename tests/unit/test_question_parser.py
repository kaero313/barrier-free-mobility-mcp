from __future__ import annotations

from app.schemas.accessibility import AccessibleRestroomRequirement
from app.services.question_parser import parse_accessibility_question


def test_parser_extracts_wheelchair_trip_question() -> None:
    parsed = parse_accessibility_question("휠체어로 홍대입구역에서 삼성역까지 갈 수 있어?")

    assert parsed.intent == "trip_accessibility"
    assert parsed.parsed.origin == "홍대입구"
    assert parsed.parsed.destination == "삼성"
    assert parsed.parsed.mobility_profile.wheelchair is True
    assert parsed.parsed.mobility_profile.can_use_stairs is False
    assert parsed.parsed.mobility_profile.can_use_escalator is False
    assert parsed.parsed.mobility_profile.need_elevator_only is True
    assert parsed.parsed.missing_fields == []


def test_parser_extracts_stroller_and_stair_restriction() -> None:
    parsed = parse_accessibility_question(
        "유모차로 1호선 서울역에서 1호선 시청까지 갈 때 계단 안 써도 돼?"
    )

    assert parsed.intent == "trip_accessibility"
    assert parsed.parsed.origin == "1호선 서울역"
    assert parsed.parsed.destination == "1호선 시청"
    assert parsed.parsed.mobility_profile.stroller is True
    assert parsed.parsed.mobility_profile.can_use_stairs is False
    assert parsed.parsed.mobility_profile.need_elevator_only is True


def test_parser_preserves_line_aware_station_mentions() -> None:
    parsed = parse_accessibility_question(
        "휠체어로 9호선 고속터미널에서 9호선 여의도까지 갈 수 있어?"
    )

    assert parsed.parsed.origin == "9호선 고속터미널"
    assert parsed.parsed.destination == "9호선 여의도"
    assert parsed.parsed.station_mentions == ["9호선 고속터미널", "9호선 여의도"]


def test_parser_extracts_accessible_restroom_requirement_scope() -> None:
    destination = parse_accessibility_question(
        "휠체어로 홍대입구에서 삼성 가는데 도착역 장애인화장실이 필요해."
    )
    origin = parse_accessibility_question(
        "휠체어로 홍대입구에서 출발역 장애인화장실을 확인하고 삼성까지 가고 싶어."
    )
    any_station = parse_accessibility_question(
        "홍대입구에서 삼성 가는 경로 중 장애인화장실이 한 곳이라도 있으면 괜찮아."
    )

    assert (
        destination.parsed.mobility_profile.accessible_restroom_requirement
        == AccessibleRestroomRequirement.DESTINATION
    )
    assert (
        origin.parsed.mobility_profile.accessible_restroom_requirement
        == AccessibleRestroomRequirement.ORIGIN
    )
    assert (
        any_station.parsed.mobility_profile.accessible_restroom_requirement
        == AccessibleRestroomRequirement.ANY_ROUTE_STATION
    )


def test_parser_marks_place_name_without_station_as_missing_route_fields() -> None:
    parsed = parse_accessibility_question("휠체어로 코엑스 갈 수 있어?")

    assert parsed.intent == "trip_accessibility"
    assert parsed.parsed.origin is None
    assert parsed.parsed.destination is None
    assert parsed.parsed.station_mentions == []
    assert len(parsed.parsed.place_mentions) == 1
    assert parsed.parsed.place_mentions[0].place_name == "코엑스"
    assert "origin" in parsed.parsed.missing_fields
    assert "destination" in parsed.parsed.missing_fields


def test_parser_classifies_facility_question_as_unsupported_intent() -> None:
    parsed = parse_accessibility_question("강남역 엘베 고장났어?")

    assert parsed.intent == "facility_status"
    assert parsed.parsed.station_mentions == ["강남"]
    assert "supported_intent" in parsed.parsed.missing_fields


def test_parser_uses_station_mention_before_same_range_place_alias() -> None:
    parsed = parse_accessibility_question("홍대에서 코엑스 가는데 계단 못 써.")

    assert parsed.intent == "trip_accessibility"
    assert parsed.parsed.origin == "홍대입구"
    assert parsed.parsed.destination is None
    assert parsed.parsed.station_mentions == ["홍대입구"]
    assert [mention.place_name for mention in parsed.parsed.place_mentions] == ["코엑스"]


def test_parser_keeps_longer_place_context_for_overlapping_station_alias() -> None:
    parsed = parse_accessibility_question("서울역 KTX에서 잠실까지 유모차로 갈만해?")

    assert parsed.intent == "trip_accessibility"
    assert parsed.parsed.origin == "서울역"
    assert parsed.parsed.destination == "잠실"
    assert parsed.parsed.station_mentions == ["서울역", "잠실"]
    assert [mention.place_name for mention in parsed.parsed.place_mentions] == ["서울역 KTX"]
