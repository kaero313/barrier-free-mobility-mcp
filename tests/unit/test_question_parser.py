from __future__ import annotations

from app.schemas.accessibility import (
    AccessibleRestroomRequirement,
    AlternativeRequestKind,
    FacilityQuestionKind,
)
from app.schemas.facility import FacilityType
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


def test_parser_preserves_wrong_explicit_line_for_service_validation() -> None:
    parsed = parse_accessibility_question(
        "휠체어로 9호선 삼성역에서 2호선 강남역까지 갈 수 있어?"
    )

    assert parsed.intent == "trip_accessibility"
    assert parsed.parsed.origin == "9호선 삼성"
    assert parsed.parsed.destination == "2호선 강남"


def test_parser_extracts_accessible_restroom_requirement_scope() -> None:
    destination = parse_accessibility_question(
        "휠체어로 홍대입구에서 삼성 가는데 도착역 장애인 화장실이 필요해."
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


def test_parser_extracts_elevator_status_question() -> None:
    parsed = parse_accessibility_question("강남역 엘베 고장났어?")

    assert parsed.intent == "facility_status"
    assert parsed.parsed.station_mentions == ["강남"]
    assert parsed.parsed.target_station == "강남"
    assert parsed.parsed.target_line is None
    assert parsed.parsed.facility_types == [FacilityType.ELEVATOR]
    assert parsed.parsed.facility_question_kind == FacilityQuestionKind.STATUS
    assert parsed.parsed.missing_fields == []


def test_parser_extracts_line_aware_elevator_location_question() -> None:
    parsed = parse_accessibility_question("2호선 삼성역 엘리베이터 어디 있어?")

    assert parsed.intent == "facility_status"
    assert parsed.parsed.target_station == "삼성"
    assert parsed.parsed.target_line == "2"
    assert parsed.parsed.facility_types == [FacilityType.ELEVATOR]
    assert parsed.parsed.facility_question_kind == FacilityQuestionKind.LOCATION


def test_parser_extracts_accessible_restroom_existence_question() -> None:
    parsed = parse_accessibility_question("2호선 잠실역 장애인 화장실 있어?")

    assert parsed.intent == "facility_status"
    assert parsed.parsed.target_station == "잠실"
    assert parsed.parsed.target_line == "2"
    assert parsed.parsed.facility_types == [FacilityType.ACCESSIBLE_RESTROOM]
    assert parsed.parsed.facility_question_kind == FacilityQuestionKind.EXISTENCE


def test_parser_requires_confirmation_for_generic_restroom_question() -> None:
    parsed = parse_accessibility_question("2호선 잠실역 화장실 어디 있어?")

    assert parsed.intent == "facility_status"
    assert parsed.parsed.facility_types == []
    assert "accessible_restroom_confirmation" in parsed.parsed.missing_fields


def test_parser_supports_elevator_and_accessible_restroom_together() -> None:
    parsed = parse_accessibility_question(
        "2호선 삼성역 엘리베이터와 장애인화장실 위치 알려줘."
    )

    assert parsed.parsed.facility_types == [
        FacilityType.ELEVATOR,
        FacilityType.ACCESSIBLE_RESTROOM,
    ]
    assert parsed.parsed.facility_question_kind == FacilityQuestionKind.LOCATION


def test_parser_classifies_station_facility_alternative() -> None:
    parsed = parse_accessibility_question("강남역 엘베 고장났는데 대안 있어?")

    assert parsed.intent == "alternative_request"
    assert (
        parsed.parsed.alternative_request_kind
        == AlternativeRequestKind.STATION_FACILITY
    )
    assert parsed.parsed.target_station == "강남"
    assert parsed.parsed.facility_types == [FacilityType.ELEVATOR]
    assert parsed.parsed.facility_question_kind == FacilityQuestionKind.STATUS
    assert parsed.parsed.missing_fields == []


def test_parser_prioritizes_route_alternative_over_trip_intent() -> None:
    parsed = parse_accessibility_question(
        "휠체어로 홍대입구에서 삼성까지 환승 적은 대안 경로 알려줘."
    )

    assert parsed.intent == "alternative_request"
    assert parsed.parsed.alternative_request_kind == AlternativeRequestKind.ROUTE
    assert parsed.parsed.origin == "홍대입구"
    assert parsed.parsed.destination == "삼성"
    assert parsed.parsed.mobility_profile.wheelchair is True
    assert parsed.parsed.mobility_profile.max_transfer_count == 1
    assert parsed.parsed.missing_fields == []


def test_parser_infers_elevator_requirement_for_avoidance_route() -> None:
    parsed = parse_accessibility_question(
        "홍대입구에서 삼성까지 엘리베이터 고장난 역 피해서 갈 수 있어?"
    )

    assert parsed.parsed.alternative_request_kind == AlternativeRequestKind.ROUTE
    assert parsed.parsed.mobility_profile.need_elevator_only is True
    assert parsed.parsed.mobility_profile.can_use_stairs is False
    assert parsed.parsed.mobility_profile.can_use_escalator is False
    assert "mobility_profile" not in parsed.parsed.missing_fields


def test_parser_marks_current_route_alternative_as_context_dependent() -> None:
    parsed = parse_accessibility_question("현재 경로에서 승강기 문제 있는 역 있어?")

    assert parsed.intent == "alternative_request"
    assert parsed.parsed.alternative_request_kind == AlternativeRequestKind.CURRENT_ROUTE
    assert "current_route_context" in parsed.parsed.missing_fields


def test_parser_requires_route_details_for_unbound_alternative() -> None:
    parsed = parse_accessibility_question("엘리베이터 고장난 역 피해서 갈 수 있어?")

    assert parsed.parsed.alternative_request_kind == AlternativeRequestKind.ROUTE
    assert "origin" in parsed.parsed.missing_fields
    assert "destination" in parsed.parsed.missing_fields


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
