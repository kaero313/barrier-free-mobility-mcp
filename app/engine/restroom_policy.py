from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.normalizers.helpers import normalize_station_name
from app.schemas.accessibility import AccessibleRestroomRequirement, MobilityProfile
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.schemas.route import RouteCandidate

StationRole = Literal["origin", "transfer", "destination"]


@dataclass(frozen=True)
class RestroomStationCheck:
    station: str
    role: StationRole
    required: bool
    available: bool
    facilities: tuple[AccessibleFacility, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RestroomRequirementEvaluation:
    applies: bool
    requirement: AccessibleRestroomRequirement
    satisfied: bool
    station_checks: tuple[RestroomStationCheck, ...] = field(default_factory=tuple)
    confirmed_facilities: tuple[AccessibleFacility, ...] = field(default_factory=tuple)
    missing_required_stations: tuple[str, ...] = field(default_factory=tuple)


def evaluate_restroom_requirement(
    *,
    route: RouteCandidate,
    mobility_profile: MobilityProfile,
    restroom_by_station: dict[str, list[AccessibleFacility]],
) -> RestroomRequirementEvaluation:
    requirement = mobility_profile.accessible_restroom_requirement
    if not mobility_profile.need_accessible_restroom:
        return RestroomRequirementEvaluation(
            applies=False,
            requirement=requirement,
            satisfied=True,
        )

    key_stations = _key_station_roles(route)
    route_station_names = route.stations or [route.origin, route.destination]
    available_by_key_station = {
        station: _available_restrooms_for_station(restroom_by_station, station)
        for station, _role in key_stations
    }
    available_route_facilities = _dedupe_facilities(
        [
            facility
            for station in route_station_names
            for facility in _available_restrooms_for_station(restroom_by_station, station)
        ]
    )

    required_stations = _required_station_names(
        requirement=requirement,
        key_stations=key_stations,
        available_by_station=available_by_key_station,
        available_route_facilities=available_route_facilities,
    )
    required_station_keys = {_station_key(station) for station in required_stations}

    station_checks = tuple(
        RestroomStationCheck(
            station=station,
            role=role,
            required=_station_key(station) in required_station_keys,
            available=bool(available_by_key_station.get(station, [])),
            facilities=tuple(available_by_key_station.get(station, [])),
        )
        for station, role in key_stations
    )
    missing_required_stations = tuple(
        check.station
        for check in station_checks
        if check.required and not check.available
    )
    satisfied = _is_requirement_satisfied(
        requirement=requirement,
        station_checks=station_checks,
        available_route_facilities=available_route_facilities,
    )

    return RestroomRequirementEvaluation(
        applies=True,
        requirement=requirement,
        satisfied=satisfied,
        station_checks=station_checks,
        confirmed_facilities=tuple(
            _dedupe_facilities(
                [facility for check in station_checks for facility in check.facilities]
            )
        ),
        missing_required_stations=missing_required_stations,
    )


def is_restroom_required_for_station(
    evaluation: RestroomRequirementEvaluation,
    station_name: str,
) -> bool | None:
    if not evaluation.applies:
        return None
    station_key = _station_key(station_name)
    for check in evaluation.station_checks:
        if _station_key(check.station) == station_key:
            return check.required
    return False


def _required_station_names(
    *,
    requirement: AccessibleRestroomRequirement,
    key_stations: list[tuple[str, StationRole]],
    available_by_station: dict[str, list[AccessibleFacility]],
    available_route_facilities: list[AccessibleFacility],
) -> list[str]:
    origins = [station for station, role in key_stations if role == "origin"]
    transfers = [station for station, role in key_stations if role == "transfer"]
    destinations = [station for station, role in key_stations if role == "destination"]

    if requirement == AccessibleRestroomRequirement.ANY_ROUTE_STATION:
        return []
    if requirement == AccessibleRestroomRequirement.ORIGIN:
        return origins
    if requirement == AccessibleRestroomRequirement.TRANSFER:
        return transfers
    if requirement == AccessibleRestroomRequirement.DESTINATION:
        return destinations
    if requirement == AccessibleRestroomRequirement.ORIGIN_OR_DESTINATION:
        candidates = [*origins, *destinations]
        confirmed = [
            station
            for station in candidates
            if available_by_station.get(station)
        ]
        return confirmed or candidates
    return [station for station, _role in key_stations]


def _is_requirement_satisfied(
    *,
    requirement: AccessibleRestroomRequirement,
    station_checks: tuple[RestroomStationCheck, ...],
    available_route_facilities: list[AccessibleFacility],
) -> bool:
    if requirement == AccessibleRestroomRequirement.ANY_ROUTE_STATION:
        return bool(available_route_facilities)
    if requirement == AccessibleRestroomRequirement.TRANSFER and not any(
        check.role == "transfer" for check in station_checks
    ):
        return True
    return not any(check.required and not check.available for check in station_checks)


def _key_station_roles(route: RouteCandidate) -> list[tuple[str, StationRole]]:
    roles: dict[str, tuple[str, StationRole]] = {}

    def add(station_name: str, role: StationRole) -> None:
        key = _station_key(station_name)
        current = roles.get(key)
        if current is not None and (current[1] == "transfer" or role != "transfer"):
            return
        roles[key] = (station_name, role)

    add(route.origin, "origin")
    add(route.destination, "destination")

    previous_line: str | None = None
    for segment in route.segments:
        current_line = segment.line.strip() if segment.line else None
        if segment.transfer:
            add(segment.from_station, "transfer")
            add(segment.to_station, "transfer")
        if previous_line and current_line and previous_line != current_line:
            add(segment.from_station, "transfer")
        if current_line:
            previous_line = current_line

    values = list(roles.values())
    if not route.stations:
        return values
    route_order = {
        _station_key(station_name): index
        for index, station_name in enumerate(route.stations)
    }
    return sorted(values, key=lambda item: route_order.get(_station_key(item[0]), 10_000))


def _available_restrooms_for_station(
    restroom_by_station: dict[str, list[AccessibleFacility]],
    station_name: str,
) -> list[AccessibleFacility]:
    station_key = _station_key(station_name)
    facilities: list[AccessibleFacility] = []
    for candidate_station, candidate_facilities in restroom_by_station.items():
        if _station_key(candidate_station) != station_key:
            continue
        facilities.extend(
            facility
            for facility in candidate_facilities
            if facility.facility_type == FacilityType.ACCESSIBLE_RESTROOM
            and facility.status == FacilityStatus.AVAILABLE
        )
    return _dedupe_facilities(facilities)


def _dedupe_facilities(facilities: list[AccessibleFacility]) -> list[AccessibleFacility]:
    seen: set[tuple[str | None, str, FacilityType]] = set()
    deduped: list[AccessibleFacility] = []
    for facility in facilities:
        identity = (
            facility.facility_id,
            _station_key(facility.station_name),
            facility.facility_type,
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(facility)
    return deduped


def _station_key(station_name: str) -> str:
    return normalize_station_name(station_name)
