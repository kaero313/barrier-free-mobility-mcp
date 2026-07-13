from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

NON_ERROR_CODES = {
    "0",
    "00",
    "03",  # Public Data Portal: no data
    "INFO-000",
    "INFO-200",  # Seoul Open Data: no matching data
}
CODE_KEYS = ("resultCode", "RESULT_CODE", "returnReasonCode")


def find_api_error_code(value: Any) -> str | None:
    """Return a sanitized upstream error code without retaining its message."""

    if isinstance(value, Mapping):
        direct_code = _code_from_mapping(value, CODE_KEYS)
        if direct_code is not None and not _is_non_error(direct_code):
            return _sanitize_code(direct_code)

        for key, nested in value.items():
            normalized_key = str(key).strip().upper()
            if normalized_key == "RESULT" and isinstance(nested, Mapping):
                result_code = _code_from_mapping(nested, ("CODE",))
                if result_code is not None and not _is_non_error(result_code):
                    return _sanitize_code(result_code)

        for nested in value.values():
            found = find_api_error_code(nested)
            if found is not None:
                return found

    if isinstance(value, list):
        for nested in value:
            found = find_api_error_code(nested)
            if found is not None:
                return found

    return None


def _code_from_mapping(value: Mapping[Any, Any], keys: tuple[str, ...]) -> str | None:
    normalized = {str(key).strip().lower(): item for key, item in value.items()}
    for key in keys:
        candidate = normalized.get(key.lower())
        if candidate is None:
            continue
        code = str(candidate).strip().upper()
        if code:
            return code
    return None


def _is_non_error(code: str) -> bool:
    return code.strip().upper() in NON_ERROR_CODES


def _sanitize_code(code: str) -> str:
    sanitized = re.sub(r"[^A-Z0-9_.-]+", "_", code.strip().upper()).strip("_")
    return (sanitized or "UNKNOWN")[:64]
