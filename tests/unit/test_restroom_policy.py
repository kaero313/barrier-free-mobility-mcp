from __future__ import annotations

from app.engine.restroom_policy import evaluate_restroom_requirement
from app.schemas.accessibility import AccessibleRestroomRequirement, MobilityProfile
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.schemas.route import RouteCandidate, RouteSegment


def test_mobility_profile_restroom_requirement_default_is_backwards_compatible() -> None:
    profile = MobilityProfile.model_validate({"need_accessible_restroom": True})

    assert profile.need_accessible_restroom is True
    assert (
        profile.accessible_restroom_requirement
        == AccessibleRestroomRequirement.ALL_KEY_STATIONS
    )


def test_any_route_station_is_satisfied_by_one_route_restroom() -> None:
    evaluation = evaluate_restroom_requirement(
        route=_direct_route(),
        mobility_profile=MobilityProfile(
            need_accessible_restroom=True,
            accessible_restroom_requirement=AccessibleRestroomRequirement.ANY_ROUTE_STATION,
        ),
        restroom_by_station={"B": [_restroom("B")]},
    )

    assert evaluation.satisfied is True
    assert evaluation.missing_required_stations == ()
    assert all(check.required is False for check in evaluation.station_checks)


def test_destination_requirement_fails_when_destination_is_missing() -> None:
    evaluation = evaluate_restroom_requirement(
        route=_direct_route(),
        mobility_profile=MobilityProfile(
            need_accessible_restroom=True,
            accessible_restroom_requirement=AccessibleRestroomRequirement.DESTINATION,
        ),
        restroom_by_station={"A": [_restroom("A")]},
    )

    assert evaluation.satisfied is False
    assert evaluation.missing_required_stations == ("C",)
    assert _check_for(evaluation, "C").required is True
    assert _check_for(evaluation, "C").available is False


def test_origin_or_destination_requirement_is_satisfied_by_either_endpoint() -> None:
    evaluation = evaluate_restroom_requirement(
        route=_direct_route(),
        mobility_profile=MobilityProfile(
            need_accessible_restroom=True,
            accessible_restroom_requirement=AccessibleRestroomRequirement.ORIGIN_OR_DESTINATION,
        ),
        restroom_by_station={"A": [_restroom("A")]},
    )

    assert evaluation.satisfied is True
    assert evaluation.missing_required_stations == ()
    assert _check_for(evaluation, "A").required is True
    assert _check_for(evaluation, "C").required is False


def test_transfer_requirement_only_applies_when_route_has_transfer_station() -> None:
    direct = evaluate_restroom_requirement(
        route=_direct_route(),
        mobility_profile=MobilityProfile(
            need_accessible_restroom=True,
            accessible_restroom_requirement=AccessibleRestroomRequirement.TRANSFER,
        ),
        restroom_by_station={},
    )
    transfer = evaluate_restroom_requirement(
        route=_transfer_route(),
        mobility_profile=MobilityProfile(
            need_accessible_restroom=True,
            accessible_restroom_requirement=AccessibleRestroomRequirement.TRANSFER,
        ),
        restroom_by_station={},
    )

    assert direct.satisfied is True
    assert direct.missing_required_stations == ()
    assert transfer.satisfied is False
    assert transfer.missing_required_stations == ("B",)


def test_all_key_stations_requires_origin_transfer_and_destination() -> None:
    evaluation = evaluate_restroom_requirement(
        route=_transfer_route(),
        mobility_profile=MobilityProfile(
            need_accessible_restroom=True,
            accessible_restroom_requirement=AccessibleRestroomRequirement.ALL_KEY_STATIONS,
        ),
        restroom_by_station={"A": [_restroom("A")], "B": [_restroom("B")]},
    )

    assert evaluation.satisfied is False
    assert evaluation.missing_required_stations == ("C",)
    assert _check_for(evaluation, "A").required is True
    assert _check_for(evaluation, "B").required is True
    assert _check_for(evaluation, "C").required is True


def _direct_route() -> RouteCandidate:
    return RouteCandidate(
        route_id="direct",
        origin="A",
        destination="C",
        stations=["A", "B", "C"],
        segments=[RouteSegment(from_station="A", to_station="C", line="1")],
        transfer_count=0,
    )


def _transfer_route() -> RouteCandidate:
    return RouteCandidate(
        route_id="transfer",
        origin="A",
        destination="C",
        stations=["A", "B", "C"],
        segments=[
            RouteSegment(from_station="A", to_station="B", line="1"),
            RouteSegment(from_station="B", to_station="C", line="2"),
        ],
        transfer_count=1,
    )


def _restroom(station_name: str) -> AccessibleFacility:
    return AccessibleFacility(
        station_name=station_name,
        facility_type=FacilityType.ACCESSIBLE_RESTROOM,
        status=FacilityStatus.AVAILABLE,
    )


def _check_for(evaluation, station_name: str):
    return next(check for check in evaluation.station_checks if check.station == station_name)
