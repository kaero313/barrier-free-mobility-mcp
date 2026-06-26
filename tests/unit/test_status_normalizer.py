from __future__ import annotations

from app.normalizers.status_normalizer import normalize_status
from app.schemas.facility import FacilityStatus


def test_status_normalizer_known_states() -> None:
    assert normalize_status("정상") == FacilityStatus.AVAILABLE
    assert normalize_status("M") == FacilityStatus.AVAILABLE
    assert normalize_status("사용가능") == FacilityStatus.AVAILABLE
    assert normalize_status("Y") == FacilityStatus.AVAILABLE
    assert normalize_status("N") == FacilityStatus.UNAVAILABLE
    assert normalize_status("이용불가") == FacilityStatus.UNAVAILABLE
    assert normalize_status("사용중지") == FacilityStatus.UNAVAILABLE
    assert normalize_status("점검중") == FacilityStatus.MAINTENANCE
    assert normalize_status("보수중") == FacilityStatus.MAINTENANCE
    assert normalize_status("") == FacilityStatus.UNKNOWN
