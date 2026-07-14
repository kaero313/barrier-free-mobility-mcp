from __future__ import annotations

from app.adapters.elevator_info_client import ElevatorInfoClient
from app.adapters.elevator_status_client import ElevatorStatusClient
from app.adapters.facility_client import FacilityClient
from app.adapters.restroom_client import RestroomClient
from app.adapters.shortest_route_client import ShortestRouteClient
from app.core.config import AppMode, Settings


def test_public_data_clients_use_public_data_service_key() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        public_data_service_key="PUBLIC",
        facility_api_url="https://example.test/facility",
        shortest_route_api_url="https://example.test/route",
    )

    facility = FacilityClient(settings)
    route = ShortestRouteClient(settings)

    assert facility.api_key == "PUBLIC"
    assert facility.api_key_field == "serviceKey"
    assert route.api_key == "PUBLIC"
    assert route.api_key_field == "serviceKey"
    assert route.endpoint_url == "https://example.test/route/getShtrmPath2"
    assert route.param_aliases == {
        "origin": "dptreStn",
        "destination": "arvlStn",
        "station_value_type": "stationValueType",
    }
    assert "searchDt" in route.default_params


def test_seoul_open_data_clients_use_per_api_keys() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        seoul_open_api_key="SHARED",
        elevator_status_api_key="STATUS",
        elevator_info_api_key="ELEVATOR",
        restroom_api_key="RESTROOM",
        elevator_status_api_url="https://example.test/status",
        elevator_info_api_url="https://example.test/elevator",
        restroom_api_url="https://example.test/restroom",
    )

    status = ElevatorStatusClient(settings)
    elevator = ElevatorInfoClient(settings)
    restroom = RestroomClient(settings)

    assert status.api_key == "STATUS"
    assert elevator.api_key == "ELEVATOR"
    assert restroom.api_key == "RESTROOM"
    assert {status.api_key_field, elevator.api_key_field, restroom.api_key_field} == {"KEY"}


def test_seoul_open_data_clients_fall_back_to_shared_key() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        seoul_open_api_key="SHARED",
        elevator_status_api_url="https://example.test/status",
        elevator_info_api_url="https://example.test/elevator",
        restroom_api_url="https://example.test/restroom",
    )

    assert ElevatorStatusClient(settings).api_key == "SHARED"
    assert ElevatorInfoClient(settings).api_key == "SHARED"
    assert RestroomClient(settings).api_key == "SHARED"
