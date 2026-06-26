from __future__ import annotations

import json
from pathlib import Path

from app.normalizers.facility_normalizer import normalize_facilities
from app.normalizers.helpers import rows_from_raw
from app.normalizers.route_normalizer import normalize_route_candidates
from app.schemas.facility import FacilityStatus, FacilityType

DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "data" / "mock_responses"


def test_facility_normalizer_converts_fixture() -> None:
    raw = json.loads((DATA_DIR / "facilities.json").read_text(encoding="utf-8"))
    facilities = normalize_facilities(raw, station="홍대입구")

    assert facilities
    assert any(item.facility_type == FacilityType.ELEVATOR for item in facilities)
    assert all(item.status == FacilityStatus.AVAILABLE for item in facilities)


def test_route_normalizer_converts_fixture() -> None:
    raw = json.loads((DATA_DIR / "shortest_route.json").read_text(encoding="utf-8"))
    routes = normalize_route_candidates(raw, origin="홍대입구", destination="삼성")

    assert len(routes) == 2
    direct = next(route for route in routes if route.route_id == "mock-hongdae-samsung-direct")
    assert direct.segments
    assert direct.stations == ["홍대입구", "강남", "삼성"]


def test_normalizers_handle_live_style_nested_fields() -> None:
    raw_facility = {
        "response": {
            "body": {
                "items": {
                    "item": {
                        "STN_NM": "홍대입구",
                        "LINE_NUM": "2",
                        "ELVTR_NM": "엘리베이터",
                        "OPR_STTS": "정상",
                        "DTL_LOC": "대합실",
                    }
                }
            }
        }
    }
    raw_route = {
        "rows": [
            {
                "origin": "홍대입구",
                "destination": "삼성",
                "ROUTE": "홍대입구 → 강남 → 삼성",
                "TRANSFER_CNT": "0",
                "TRVL_TIME": "33",
            }
        ]
    }

    facilities = normalize_facilities(raw_facility, station="홍대입구")
    routes = normalize_route_candidates(raw_route, origin="홍대입구", destination="삼성")

    assert rows_from_raw(raw_facility)[0]["STN_NM"] == "홍대입구"
    assert facilities[0].location_description == "대합실"
    assert routes[0].stations == ["홍대입구", "강남", "삼성"]


def test_dedicated_restroom_source_promotes_restroom_type() -> None:
    raw = {
        "response": {
            "body": {
                "items": {
                    "item": {
                        "stnNm": "동묘앞",
                        "lineNm": "1호선",
                        "fcltNm": "대합실화장실",
                    }
                }
            }
        }
    }

    facilities = normalize_facilities(raw, facility_type=FacilityType.ACCESSIBLE_RESTROOM)

    assert len(facilities) == 1
    assert facilities[0].facility_type == FacilityType.ACCESSIBLE_RESTROOM


def test_live_facility_fields_use_normalized_station_line_and_status() -> None:
    raw = {
        "rows": [
            {
                "fcltNo": "EV-1",
                "fcltNm": "승강기)엘리베이터-홍대입구 내부#1",
                "lineNm": "02호선",
                "stnNm": "홍대입구역",
                "dtlPstn": "대합실",
                "oprtngSitu": "M",
            },
            {
                "STN_NM": "홍대입구",
                "ELVTR_NM": "승강기)에스컬레이터-홍대입구 외부",
                "ELVTR_SE": "ES",
                "USE_YN": "보수중",
            },
        ]
    }

    elevators = normalize_facilities(
        raw,
        station="홍대입구",
        line="2",
        facility_type=FacilityType.ELEVATOR,
    )
    all_facilities = normalize_facilities(raw, station="홍대입구")

    assert len(elevators) == 1
    assert elevators[0].status == FacilityStatus.AVAILABLE
    assert any(item.facility_type == FacilityType.ESCALATOR for item in all_facilities)
    assert any(item.status == FacilityStatus.MAINTENANCE for item in all_facilities)


def test_station_matching_ignores_terminal_parenthetical_line_marker() -> None:
    raw = {
        "rows": [
            {
                "STN_NM": "서울역(1)",
                "ELVTR_NM": "승강기)엘리베이터-서울역 외부#1",
                "ELVTR_SE": "EV",
                "USE_YN": "사용가능",
            }
        ]
    }

    facilities = normalize_facilities(
        raw,
        station="서울역",
        facility_type=FacilityType.ELEVATOR,
    )

    assert len(facilities) == 1
    assert facilities[0].status == FacilityStatus.AVAILABLE
