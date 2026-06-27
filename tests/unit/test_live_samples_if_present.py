from __future__ import annotations

import json
from pathlib import Path

from app.normalizers.facility_normalizer import normalize_facilities
from app.normalizers.route_normalizer import normalize_route_candidates
from app.schemas.facility import FacilityStatus, FacilityType

LIVE_SAMPLE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "live_samples"


def test_saved_live_facility_samples_normalize_when_present() -> None:
    sample_types = {
        "elevator_info_sample.json": FacilityType.ELEVATOR,
        "restroom_sample.json": FacilityType.ACCESSIBLE_RESTROOM,
    }
    for filename, facility_type in sample_types.items():
        path = LIVE_SAMPLE_DIR / filename
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))

        assert normalize_facilities(raw, facility_type=facility_type)


def test_saved_live_status_sample_distinguishes_elevators_and_escalators_when_present() -> None:
    path = LIVE_SAMPLE_DIR / "elevator_status_sample.json"
    if not path.exists():
        return
    raw = json.loads(path.read_text(encoding="utf-8"))

    facilities = normalize_facilities(raw)

    assert facilities
    facility_types = {item.facility_type for item in facilities}
    assert FacilityType.ELEVATOR in facility_types
    assert FacilityType.ESCALATOR in facility_types
    assert any(item.status == FacilityStatus.AVAILABLE for item in facilities)


def test_saved_live_facility_sample_maps_operation_code_when_present() -> None:
    path = LIVE_SAMPLE_DIR / "facilities_sample.json"
    if not path.exists():
        return
    raw = json.loads(path.read_text(encoding="utf-8"))

    elevators = normalize_facilities(
        raw,
        station="낙성대역",
        line="02",
        facility_type=FacilityType.ELEVATOR,
    )

    assert elevators
    assert all(item.status == FacilityStatus.AVAILABLE for item in elevators)


def test_saved_live_shortest_route_sample_normalizes_when_present() -> None:
    path = LIVE_SAMPLE_DIR / "shortest_route_sample.json"
    if not path.exists():
        return
    raw = json.loads(path.read_text(encoding="utf-8"))

    routes = normalize_route_candidates(raw, origin="홍대입구", destination="삼성")

    assert len(routes) == 1
    assert routes[0].stations[0] == "홍대입구"
    assert routes[0].stations[-1] == "삼성"
    assert routes[0].transfer_count >= 0
    assert routes[0].estimated_minutes is not None
    assert routes[0].estimated_minutes > 0
