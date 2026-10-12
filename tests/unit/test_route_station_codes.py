from __future__ import annotations

from app.normalizers.station_normalizer import DEFAULT_STATION_NORMALIZER
from app.services.route_station_codes import (
    load_route_station_codes,
    resolve_route_station_code,
)


def test_route_station_codes_use_api_specific_values() -> None:
    assert resolve_route_station_code("홍대입구", "2호선") == "0239"
    assert resolve_route_station_code("시청역", "1") == "0151"
    assert resolve_route_station_code("고속터미널", "09") == "4123"
    assert resolve_route_station_code("여의도", "Line 9") == "4115"
    assert resolve_route_station_code("건대입구", "7") == "2729"


def test_route_station_code_requires_verified_station_and_line_pair() -> None:
    assert resolve_route_station_code("고속터미널", None) is None
    assert resolve_route_station_code("지원하지않는역", "2") is None
    assert resolve_route_station_code("홍대입구", "9") is None


def test_route_station_code_mapping_has_unique_nonempty_values_per_pair() -> None:
    mappings = load_route_station_codes()

    assert len(mappings) >= 320
    assert all(station and line and code for (station, line), code in mappings.items())


def test_every_registered_station_line_pair_has_a_verified_route_code() -> None:
    missing = [
        f"{station.line}:{station.station_name}"
        for station in DEFAULT_STATION_NORMALIZER.stations
        if resolve_route_station_code(station.station_name, station.line) is None
    ]

    assert missing == []
