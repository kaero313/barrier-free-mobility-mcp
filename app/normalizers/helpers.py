from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

LINE_NUMBER_PATTERN = re.compile(r"\d+")


def rows_from_raw(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if not isinstance(raw, dict):
        return []

    for key in ("rows", "row", "item", "data", "items", "results", "result", "list"):
        value = raw.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = rows_from_raw(value)
            if nested:
                return nested
            if _looks_like_row(value):
                return [value]

    for value in raw.values():
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return list(value)
        if isinstance(value, dict):
            nested = rows_from_raw(value)
            if nested:
                return nested
    return []


def pick(row: Mapping[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    normalized = {str(key).strip().lower(): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(key.strip().lower())
        if value is not None and value != "":
            return value
    return default


def as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "y", "yes", "운영", "있음", "내부", "inside"}:
        return True
    if text in {"false", "0", "n", "no", "없음", "외부", "outside"}:
        return False
    return None


def normalize_station_name(value: Any) -> str | None:
    text = as_str(value)
    if text is None:
        return None
    normalized = text.replace(" ", "")
    normalized = re.sub(r"\([^)]*\)$", "", normalized)
    normalized = re.sub(r"（[^）]*）$", "", normalized)
    return normalized[:-1] if normalized.endswith("역") else normalized


def station_matches(value: Any, expected: str | None) -> bool:
    if expected is None:
        return True
    return normalize_station_name(value) == normalize_station_name(expected)


def normalize_line_name(value: Any) -> str | None:
    text = as_str(value)
    if text is None:
        return None
    normalized = text.strip().lower().replace(" ", "")
    number_match = LINE_NUMBER_PATTERN.search(normalized)
    if number_match:
        return str(int(number_match.group(0)))
    return normalized.replace("호선", "").replace("line", "") or None


def line_matches(value: Any, expected: str | None) -> bool:
    if expected is None:
        return True
    normalized_value = normalize_line_name(value)
    if normalized_value is None:
        return True
    return normalized_value == normalize_line_name(expected)


def split_station_path(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    for separator in ("→", ">", "-", ",", " "):
        if separator in text:
            return [part.strip() for part in text.split(separator) if part.strip()]
    return [text]


def _looks_like_row(value: Mapping[str, Any]) -> bool:
    return bool(value) and any(not isinstance(item, dict | list) for item in value.values())


def transfer_text(count: int) -> str:
    """Describe a transfer count the way a rider reads it ("0회 환승" reads as an error)."""
    return "환승 없는" if count <= 0 else f"{count}회 환승"


# "방면5-1,남영 방면6-4"처럼 쉼표 뒤가 붙은 원자료만 띄운다.
# "1,12번"처럼 숫자 사이 쉼표는 그대로 둔다.
_TIGHT_COMMA = re.compile(r"(?<=\D),(?=\S)|,(?=[^\s\d])")


def tidy_location_text(value: str) -> str:
    return _TIGHT_COMMA.sub(", ", value)


# "합정 방면7-2"처럼 열차 방면과 칸·문 번호로 적힌 위치는 승강장 안의 시설이다.
_PLATFORM_POSITION = re.compile(r"방면\s*\d+-\d+")


def is_platform_position(location: str | None) -> bool:
    return _PLATFORM_POSITION.search(location or "") is not None


def label_platform_position(location: str) -> str:
    # 방면·칸 번호만으로는 승강장 시설인지 알아보기 어렵다.
    if is_platform_position(location) and "승강장" not in location:
        return f"승강장 {location}"
    return location
