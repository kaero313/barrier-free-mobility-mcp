from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def current_risk_rules() -> str:
    return (DATA_DIR / "risk_rules.yaml").read_text(encoding="utf-8")


def data_sources_public_apis() -> dict[str, str]:
    return {
        "facility_info": "서울교통공사_편의시설위치정보",
        "shortest_route": "서울교통공사_최단경로이동정보",
        "elevator_status": "서울교통공사_교통약자_이용시설_승강기_가동현황",
        "elevator_info": "서울시 교통공사 지하철역 교통약자이용정보 엘리베이터 현황",
        "restroom": "서울시 교통공사 지하철역 교통약자이용정보 장애인화장실 현황",
    }

