from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, quote_plus, unquote

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
    re.compile(
        r"((?:serviceKey|ServiceKey|SERVICE_KEY|api_key|API_KEY|KEY)\s*=\s*)[^&\s]+"
    ),
    re.compile(
        r"((?:MCP_API_KEY|PUBLIC_DATA_SERVICE_KEY|SEOUL_OPEN_API_KEY|"
        r"ELEVATOR_STATUS_API_KEY|ELEVATOR_INFO_API_KEY|RESTROOM_API_KEY)\s*=\s*)[^\s]+"
    ),
)


def redact_sensitive_values(
    value: Any,
    *,
    sensitive_values: tuple[str, ...] = (),
) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_sensitive_values(
                    item,
                    sensitive_values=sensitive_values,
                )
        return redacted
    if isinstance(value, list):
        return [
            redact_sensitive_values(item, sensitive_values=sensitive_values)
            for item in value
        ]
    if isinstance(value, str):
        return redact_sensitive_text(value, sensitive_values=sensitive_values)
    return value


def redact_sensitive_text(
    value: str,
    *,
    sensitive_values: tuple[str, ...] = (),
) -> str:
    redacted = value
    for secret in _secret_variants(sensitive_values):
        redacted = redacted.replace(secret, "[REDACTED]")
    for pattern in SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub(lambda match: _redacted_match(match), redacted)
    return redacted


def _secret_variants(sensitive_values: tuple[str, ...]) -> list[str]:
    variants: set[str] = set()
    for value in sensitive_values:
        secret = value.strip()
        if len(secret) < 4:
            continue
        decoded = unquote(secret)
        variants.update(
            candidate
            for candidate in (
                secret,
                decoded,
                quote(decoded, safe=""),
                quote_plus(decoded, safe=""),
            )
            if len(candidate) >= 4
        )
    return sorted(variants, key=len, reverse=True)


def _redacted_match(match: re.Match[str]) -> str:
    if match.lastindex:
        return match.group(1) + "[REDACTED]"
    return "[REDACTED]"
