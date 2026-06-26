from __future__ import annotations

from app.schemas.facility import FacilityStatus

EXACT_STATUS_CODES = {
    "m": FacilityStatus.AVAILABLE,
    "y": FacilityStatus.AVAILABLE,
    "yes": FacilityStatus.AVAILABLE,
    "n": FacilityStatus.UNAVAILABLE,
    "no": FacilityStatus.UNAVAILABLE,
}
AVAILABLE_TOKENS = {
    "available",
    "normal",
    "ok",
    "운영",
    "운행",
    "정상",
    "가동",
    "사용가능",
    "이용가능",
    "가능",
    "운영중",
    "운행중",
}
UNAVAILABLE_TOKENS = {
    "unavailable",
    "down",
    "stop",
    "중지",
    "정지",
    "고장",
    "장애",
    "비정상",
    "이용불가",
    "사용불가",
    "운휴",
    "사용중지",
    "운행중지",
}
MAINTENANCE_TOKENS = {
    "maintenance",
    "repair",
    "점검",
    "점검중",
    "공사",
    "보수",
    "보수중",
    "수리",
    "수리중",
}


def normalize_status(value: object) -> FacilityStatus:
    if value is None:
        return FacilityStatus.UNKNOWN
    text = str(value).strip().lower().replace(" ", "")
    if not text:
        return FacilityStatus.UNKNOWN
    if text in EXACT_STATUS_CODES:
        return EXACT_STATUS_CODES[text]
    if any(token in text for token in MAINTENANCE_TOKENS):
        return FacilityStatus.MAINTENANCE
    if any(token in text for token in UNAVAILABLE_TOKENS):
        return FacilityStatus.UNAVAILABLE
    if any(token in text for token in AVAILABLE_TOKENS):
        return FacilityStatus.AVAILABLE
    return FacilityStatus.UNKNOWN
