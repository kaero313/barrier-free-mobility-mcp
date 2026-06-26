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
