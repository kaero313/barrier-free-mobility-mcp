from __future__ import annotations

from app.adapters.elevator_info_client import ElevatorInfoClient
from app.adapters.elevator_status_client import ElevatorStatusClient
from app.adapters.facility_client import FacilityClient
from app.adapters.mock_client import FixtureClient
from app.adapters.restroom_client import RestroomClient
from app.adapters.shortest_route_client import ShortestRouteClient
from app.core.config import AppMode, Settings


def facility_client(settings: Settings):
    if settings.app_mode == AppMode.MOCK:
        return FixtureClient(
            "facility_info",
            "facilities.json",
            failure_sources=settings.mock_failure_sources,
        )
    return FacilityClient(settings)


def route_client(settings: Settings):
    if settings.app_mode == AppMode.MOCK:
        return FixtureClient(
            "shortest_route",
            "shortest_route.json",
            failure_sources=settings.mock_failure_sources,
        )
    return ShortestRouteClient(settings)


def elevator_status_client(settings: Settings):
    if settings.app_mode == AppMode.MOCK:
        return FixtureClient(
            "elevator_status",
            "elevator_status.json",
            failure_sources=settings.mock_failure_sources,
        )
    return ElevatorStatusClient(settings)


def elevator_info_client(settings: Settings):
    if settings.app_mode == AppMode.MOCK:
        return FixtureClient(
            "elevator_info",
            "elevator_info.json",
            failure_sources=settings.mock_failure_sources,
        )
    return ElevatorInfoClient(settings)


def restroom_client(settings: Settings):
    if settings.app_mode == AppMode.MOCK:
        return FixtureClient(
            "restroom",
            "restroom.json",
            failure_sources=settings.mock_failure_sources,
        )
    return RestroomClient(settings)
