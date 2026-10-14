from __future__ import annotations

import json
from pathlib import Path

from app.normalizers.facility_normalizer import normalize_facilities, normalize_facility_type
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


def test_shortest_route_normalizer_rejects_empty_paths() -> None:
    raw = {
        "document": {
            "body": {
                "paths": {"path": []},
                "trsitNmtm": 0,
                "totalReqHr": 0,
            }
        }
    }

    assert normalize_route_candidates(raw, origin="서울역", destination="삼성") == []


def test_generic_route_normalizer_rejects_endpoint_only_row() -> None:
    raw = {"rows": [{"origin": "서울역", "destination": "삼성"}]}

    assert normalize_route_candidates(raw, origin="서울역", destination="삼성") == []


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
                "OPR_SEC": "승강장-대합실",
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
        source_name="elevator_status",
    )
    all_facilities = normalize_facilities(raw, station="홍대입구")

    assert len(elevators) == 1
    assert elevators[0].status == FacilityStatus.AVAILABLE
    assert elevators[0].facility_name == "승강기)엘리베이터-홍대입구 내부#1"
    assert elevators[0].operation_section == "승강장-대합실"
    assert elevators[0].source_name == "elevator_status"
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


def test_elevator_status_keeps_descriptive_name_and_excludes_wheelchair_lift() -> None:
    raw = {
        "rows": [
            {
                "STN_NM": "삼성",
                "ELVTR_NM": "승강기)엘리베이터-삼성 1번 출구측 외부#1",
                "ELVTR_SE": "EV",
                "INSTL_PSTN": "1번 출입구",
                "USE_YN": "보수중",
            },
            {
                "STN_NM": "삼성",
                "ELVTR_NM": "승강기)휠체어리프트-삼성 연결계단 내부1",
                "ELVTR_SE": "WL",
                "INSTL_PSTN": "연결계단",
                "USE_YN": "보수중",
            },
        ]
    }

    elevators = normalize_facilities(
        raw,
        station="삼성",
        facility_type=FacilityType.ELEVATOR,
        source_name="elevator_status",
    )
    all_facilities = normalize_facilities(raw, station="삼성")

    assert len(elevators) == 1
    assert elevators[0].facility_name == "승강기)엘리베이터-삼성 1번 출구측 외부#1"
    assert elevators[0].location_description == "1번 출입구"
    assert elevators[0].status == FacilityStatus.MAINTENANCE
    assert any(
        item.facility_type == FacilityType.WHEELCHAIR_LIFT
        for item in all_facilities
    )


def test_elevator_status_infers_line_for_transfer_station_filtering() -> None:
    raw = {
        "rows": [
            {
                "STN_CD": "0329",
                "STN_NM": "고속터미널(3)",
                "ELVTR_NM": "승강기)엘리베이터-고속터미널 3호선 내부",
                "ELVTR_SE": "EV",
                "INSTL_PSTN": "3호선 승강장",
                "USE_YN": "사용가능",
            },
            {
                "STN_CD": "2736",
                "STN_NM": "고속터미널(7)",
                "ELVTR_NM": "승강기)엘리베이터-고속터미널 7호선 내부",
                "ELVTR_SE": "EV",
                "INSTL_PSTN": "7호선 승강장",
                "USE_YN": "사용가능",
            },
        ]
    }

    facilities = normalize_facilities(
        raw,
        station="고속터미널",
        line="3",
        facility_type=FacilityType.ELEVATOR,
        source_name="elevator_status",
    )

    assert len(facilities) == 1
    assert facilities[0].line == "3"
    assert facilities[0].location_description == "3호선 승강장"


def test_shortest_route_summary_reads_zero_transfers_naturally() -> None:
    def document(transfers: int) -> dict[str, object]:
        return {
            "document": {
                "body": {
                    "paths": {
                        "path": [
                            {
                                "dptreStn": {"stnNm": "홍대입구", "lineNm": "2호선"},
                                "arvlStn": {"stnNm": "삼성", "lineNm": "2호선"},
                                "trsitYn": "N",
                                "reqHr": 1800,
                            }
                        ]
                    },
                    "trsitNmtm": transfers,
                    "totalReqHr": 1800,
                }
            }
        }

    direct = normalize_route_candidates(document(0), origin="홍대입구", destination="삼성")
    one_transfer = normalize_route_candidates(document(1), origin="홍대입구", destination="삼성")

    assert direct[0].raw_summary == "홍대입구에서 삼성까지 환승 없는 경로"
    assert one_transfer[0].raw_summary == "홍대입구에서 삼성까지 1회 환승 경로"


def test_misspelled_escalator_names_are_not_counted_as_elevators() -> None:
    # 공공데이터 시설명의 "에스컬레터" 오타와 "E/S" 표기도 에스컬레이터다.
    assert (
        normalize_facility_type("승강기)에스컬레터-사당(2) E/S 1200형 13호기")
        == FacilityType.ESCALATOR
    )
    assert normalize_facility_type("승강기)사당(2) E/S 1200형 14호기") == FacilityType.ESCALATOR
    # 엘리베이터라고 적힌 이름은 위치 설명에 E/S가 섞여도 엘리베이터로 남는다.
    assert (
        normalize_facility_type("승강기)엘리베이터-사당 E/S 11호기 옆 내부#1")
        == FacilityType.ELEVATOR
    )
    assert (
        normalize_facility_type("승강기)엘리베이터-삼성 1번 출구측 외부#1") == FacilityType.ELEVATOR
    )
