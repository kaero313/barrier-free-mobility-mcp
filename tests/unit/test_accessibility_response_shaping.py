from __future__ import annotations

from app.core.time import utc_now
from app.schemas.accessibility import MobilityProfile
from app.schemas.common import CacheStatus, DataSourceMeta
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.schemas.route import RouteCandidate
from app.services.result_metadata import dedupe_data_sources
from app.services.trip_response import (
    compact_accessible_facilities,
    compact_route_candidates,
)


def test_dedupe_data_sources_by_source_cache_status_and_success() -> None:
    first = DataSourceMeta(
        source_name="facility_info",
        source_type="public_api",
        fetched_at=utc_now(),
        cache_status=CacheStatus.MISS,
    )
    duplicate = first.model_copy(update={"fetched_at": utc_now()})
    cache_hit = DataSourceMeta(
        source_name="facility_info",
        source_type="cache",
        fetched_at=utc_now(),
        cache_status=CacheStatus.HIT,
    )

    compacted = dedupe_data_sources([first, duplicate, cache_hit])

    assert compacted == [first, cache_hit]


def test_compact_accessible_facilities_keeps_representative_elevator_per_station() -> None:
    route = RouteCandidate(
        route_id="route-a",
        origin="A",
        destination="B",
        segments=[],
        stations=["A", "B"],
    )
    facilities = [
        _facility("A-1", "A", FacilityType.ELEVATOR),
        _facility("A-2", "A", FacilityType.ELEVATOR),
        _facility("A-R", "A", FacilityType.ACCESSIBLE_RESTROOM),
        _facility("B-1", "B", FacilityType.ELEVATOR),
        _facility("B-R", "B", FacilityType.ACCESSIBLE_RESTROOM),
        _facility("C-1", "C", FacilityType.ELEVATOR),
    ]

    compacted, trimmed = compact_accessible_facilities(
        facilities,
        route,
        MobilityProfile(wheelchair=True),
    )

    assert trimmed is True
    assert [(item.station_name, item.facility_type) for item in compacted] == [
        ("A", FacilityType.ELEVATOR),
        ("B", FacilityType.ELEVATOR),
    ]


def test_compact_accessible_facilities_adds_restrooms_when_required() -> None:
    route = RouteCandidate(
        route_id="route-a",
        origin="A",
        destination="B",
        segments=[],
        stations=["A", "B"],
    )
    facilities = [
        _facility("A-1", "A", FacilityType.ELEVATOR),
        _facility("A-R", "A", FacilityType.ACCESSIBLE_RESTROOM),
        _facility("B-1", "B", FacilityType.ELEVATOR),
        _facility("B-R", "B", FacilityType.ACCESSIBLE_RESTROOM),
    ]

    compacted, trimmed = compact_accessible_facilities(
        facilities,
        route,
        MobilityProfile(wheelchair=True, need_accessible_restroom=True),
    )

    assert trimmed is False
    assert [(item.station_name, item.facility_type) for item in compacted] == [
        ("A", FacilityType.ELEVATOR),
        ("A", FacilityType.ACCESSIBLE_RESTROOM),
        ("B", FacilityType.ELEVATOR),
        ("B", FacilityType.ACCESSIBLE_RESTROOM),
    ]


def test_compact_route_candidates_keeps_selected_and_two_alternatives() -> None:
    selected = _route("selected")
    routes = [selected, _route("alt-1"), _route("alt-2"), _route("alt-3")]

    compacted = compact_route_candidates(routes, selected)

    assert [route.route_id for route in compacted] == ["selected", "alt-1", "alt-2"]


def _facility(
    facility_id: str,
    station_name: str,
    facility_type: FacilityType,
) -> AccessibleFacility:
    return AccessibleFacility(
        facility_id=facility_id,
        station_name=station_name,
        facility_type=facility_type,
        status=FacilityStatus.AVAILABLE,
    )


def _route(route_id: str) -> RouteCandidate:
    return RouteCandidate(
        route_id=route_id,
        origin="A",
        destination="B",
        segments=[],
        stations=["A", "B"],
    )
