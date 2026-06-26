from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SENSITIVE_KEYS = {
    "key",
    "api_key",
    "mcp_api_key",
    "bearer_token",
    "service_key",
    "servicekey",
    "public_data_service_key",
    "seoul_open_api_key",
    "authorization",
    "x-api-key",
}

SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"(Authorization\s*:\s*)[^\s,;]+", re.IGNORECASE),
    re.compile(r"((?:serviceKey|ServiceKey|SERVICE_KEY)\s*=\s*)[^&\s]+"),
    re.compile(
        r"((?:MCP_API_KEY|PUBLIC_DATA_SERVICE_KEY|SEOUL_OPEN_API_KEY|"
        r"ELEVATOR_STATUS_API_KEY|ELEVATOR_INFO_API_KEY|RESTROOM_API_KEY)\s*=\s*)[^\s]+"
    ),
)


def redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_sensitive_values(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def redact_sensitive_text(value: str) -> str:
    redacted = value
    for pattern in SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub(lambda match: _redacted_match(match), redacted)
    return redacted


def _redacted_match(match: re.Match[str]) -> str:
    if match.lastindex:
        return match.group(1) + "[REDACTED]"
    return "[REDACTED]"
