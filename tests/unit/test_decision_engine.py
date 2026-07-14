from __future__ import annotations

from app.engine.decision_engine import AccessibilityDecisionEngine
from app.schemas.accessibility import MobilityProfile
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.schemas.route import RouteCandidate, RouteSegment


def _route(route_id: str, transfer_count: int) -> RouteCandidate:
    return RouteCandidate(
        route_id=route_id,
        origin="홍대입구",
        destination="삼성",
        stations=["홍대입구", "삼성"],
        segments=[
            RouteSegment(from_station="홍대입구", to_station="삼성", line="2"),
        ],
        transfer_count=transfer_count,
    )


def test_decision_engine_selects_lowest_risk_route() -> None:
    engine = AccessibilityDecisionEngine()
    profile = MobilityProfile(stroller=True, max_transfer_count=0)
    route_a = _route("a", 0)
    route_b = _route("b", 2)
    elevator = AccessibleFacility(
        station_name="홍대입구",
        line="2",
        facility_type=FacilityType.ELEVATOR,
        status=FacilityStatus.AVAILABLE,
    )
    samsung_elevator = elevator.model_copy(update={"station_name": "삼성"})

    decision = engine.evaluate_routes(
        routes=[route_b, route_a],
        mobility_profile=profile,
        facilities_by_station={"홍대입구": [elevator], "삼성": [samsung_elevator]},
        elevator_status_by_station={"홍대입구": [elevator], "삼성": [samsung_elevator]},
        restroom_by_station={},
        failed_sources=[],
        data_sources=[],
    )

    assert decision.selected.route == route_a
    assert decision.selected.risk_level == "LOW"


def test_decision_engine_treats_empty_routes_as_unknown() -> None:
    decision = AccessibilityDecisionEngine().evaluate_routes(
        routes=[],
        mobility_profile=MobilityProfile(wheelchair=True),
        facilities_by_station={},
        elevator_status_by_station={},
        restroom_by_station={},
        failed_sources=[],
        data_sources=[],
    )

    assert decision.selected.route is None
    assert decision.selected.risk_level == "UNKNOWN"
    assert decision.selected.limitations == ["경로 후보를 확인하지 못했습니다."]


def test_decision_engine_breaks_risk_ties_by_transfers_then_time() -> None:
    engine = AccessibilityDecisionEngine()
    profile = MobilityProfile(avoid_many_transfers=False)
    two_transfers = _route("two-transfers", 2).model_copy(
        update={"estimated_minutes": 20}
    )
    one_transfer_slow = _route("one-slow", 1).model_copy(
        update={"estimated_minutes": 30}
    )
    one_transfer_fast = _route("one-fast", 1).model_copy(
        update={"estimated_minutes": 25}
    )

    decision = engine.evaluate_routes(
        routes=[two_transfers, one_transfer_slow, one_transfer_fast],
        mobility_profile=profile,
        facilities_by_station={},
        elevator_status_by_station={},
        restroom_by_station={},
        failed_sources=[],
        data_sources=[],
    )

    assert decision.selected.route == one_transfer_fast
    assert [alternative.route for alternative in decision.alternatives] == [
        one_transfer_slow,
        two_transfers,
    ]


def test_decision_engine_adds_restroom_risk_when_required() -> None:
    engine = AccessibilityDecisionEngine()
    profile = MobilityProfile(need_accessible_restroom=True)
    decision = engine.evaluate_routes(
        routes=[_route("a", 0)],
        mobility_profile=profile,
        facilities_by_station={},
        elevator_status_by_station={},
        restroom_by_station={},
        failed_sources=[],
        data_sources=[],
    )

    assert any(
        reason.code == "no_accessible_restroom_when_required"
        for reason in decision.selected.risk_reasons
    )


def test_decision_engine_scores_restroom_missing_once_across_required_stations() -> None:
    engine = AccessibilityDecisionEngine()
    profile = MobilityProfile(need_accessible_restroom=True)

    decision = engine.evaluate_routes(
        routes=[_route("a", 0)],
        mobility_profile=profile,
        facilities_by_station={},
        elevator_status_by_station={},
        restroom_by_station={},
        failed_sources=[],
        data_sources=[],
    )

    restroom_reasons = [
        reason
        for reason in decision.selected.risk_reasons
        if reason.code == "no_accessible_restroom_when_required"
    ]
    assert len(restroom_reasons) == 2
    assert [reason.station_name for reason in restroom_reasons] == ["홍대입구", "삼성"]
    assert restroom_reasons[0].score > 0
    assert restroom_reasons[1].score == 0


def test_decision_engine_uses_confirmed_elevator_without_unknown_reason() -> None:
    engine = AccessibilityDecisionEngine()
    profile = MobilityProfile(wheelchair=True, can_use_stairs=False, need_elevator_only=True)
    elevator = AccessibleFacility(
        station_name="홍대입구역",
        line="02호선",
        facility_type=FacilityType.ELEVATOR,
        status=FacilityStatus.AVAILABLE,
    )
    samsung_elevator = elevator.model_copy(update={"station_name": "삼성역"})

    decision = engine.evaluate_routes(
        routes=[_route("a", 0)],
        mobility_profile=profile,
        facilities_by_station={
            "홍대입구역": [elevator],
            "삼성역": [samsung_elevator],
        },
        elevator_status_by_station={},
        restroom_by_station={},
        failed_sources=[],
        data_sources=[],
    )

    codes = {reason.code for reason in decision.selected.risk_reasons}
    assert "elevator_unknown" not in codes
    assert "elevator_not_found" not in codes
    assert decision.selected.risk_level == "LOW"


def test_decision_engine_preserves_mixed_operational_elevator_status() -> None:
    engine = AccessibilityDecisionEngine()
    profile = MobilityProfile(
        wheelchair=True,
        can_use_stairs=False,
        need_elevator_only=True,
    )
    origin_available = AccessibleFacility(
        facility_id="H-1",
        station_name="홍대입구",
        line="2",
        facility_type=FacilityType.ELEVATOR,
        status=FacilityStatus.AVAILABLE,
        location_description="8번 출구",
        source_name="elevator_status",
    )
    origin_maintenance = origin_available.model_copy(
        update={
            "facility_id": "H-2",
            "status": FacilityStatus.MAINTENANCE,
            "location_description": "1번 출구",
        }
    )
    destination_available = origin_available.model_copy(
        update={"facility_id": "S-1", "station_name": "삼성"}
    )

    decision = engine.evaluate_routes(
        routes=[_route("a", 0)],
        mobility_profile=profile,
        facilities_by_station={},
        elevator_status_by_station={
            "홍대입구": [origin_available, origin_maintenance],
            "삼성": [destination_available],
        },
        restroom_by_station={},
        failed_sources=[],
        data_sources=[],
    )

    codes = {reason.code for reason in decision.selected.risk_reasons}
    blocked_ids = {
        issue.station_name
        for issue in decision.selected.blocked_facilities
        if issue.status == FacilityStatus.MAINTENANCE
    }
    assert "elevator_mixed" in codes
    assert "elevator_unavailable" not in codes
    assert decision.selected.risk_level == "CAUTION"
    assert decision.selected.risk_score >= 35
    assert blocked_ids == {"홍대입구"}


def test_decision_engine_ignores_pass_through_station_elevator_status() -> None:
    engine = AccessibilityDecisionEngine()
    profile = MobilityProfile(wheelchair=True, can_use_stairs=False, need_elevator_only=True)
    route = RouteCandidate(
        route_id="a",
        origin="홍대입구",
        destination="삼성",
        stations=["홍대입구", "강남", "삼성"],
        segments=[
            RouteSegment(from_station="홍대입구", to_station="삼성", line="2"),
        ],
        transfer_count=0,
    )
    origin_elevator = AccessibleFacility(
        station_name="홍대입구",
        facility_type=FacilityType.ELEVATOR,
        status=FacilityStatus.AVAILABLE,
        location_description="8번 출입구",
    )
    destination_elevator = origin_elevator.model_copy(
        update={"station_name": "삼성", "location_description": "6번 출입구"}
    )
    pass_through_elevator = origin_elevator.model_copy(
        update={
            "station_name": "강남",
            "status": FacilityStatus.MAINTENANCE,
            "location_description": "5번 출입구",
        }
    )

    decision = engine.evaluate_routes(
        routes=[route],
        mobility_profile=profile,
        facilities_by_station={
            "홍대입구": [origin_elevator],
            "삼성": [destination_elevator],
            "강남": [pass_through_elevator],
        },
        elevator_status_by_station={},
        restroom_by_station={},
        failed_sources=[],
        data_sources=[],
    )

    codes = {reason.code for reason in decision.selected.risk_reasons}
    accessible_stations = {
        facility.station_name for facility in decision.selected.accessible_facilities
    }
    assert "elevator_unavailable" not in codes
    assert accessible_stations == {"홍대입구", "삼성"}
    assert decision.selected.risk_level == "LOW"
