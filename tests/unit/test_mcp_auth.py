from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.auth import StaticBearerTokenVerifier
from app.core.config import Settings
from app.core.security import redact_sensitive_text, redact_sensitive_values
from app.mcp.server import create_mcp_server


async def test_static_bearer_verifier_accepts_valid_token() -> None:
    verifier = StaticBearerTokenVerifier("valid-test-token")

    token = await verifier.verify_token("valid-test-token")

    assert token is not None
    assert token.client_id == "static-mcp-client"
    assert token.scopes == ["mcp:read"]
    assert token.token == "<redacted>"


async def test_static_bearer_verifier_rejects_invalid_token() -> None:
    verifier = StaticBearerTokenVerifier("valid-test-token")

    assert await verifier.verify_token("wrong-token") is None
    assert await verifier.verify_token("") is None


@pytest.mark.parametrize("api_key", ["", "change-me"])
def test_auth_enabled_rejects_empty_or_default_api_key(api_key: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, mcp_auth_enabled=True, mcp_api_key=api_key)

    message = str(exc_info.value)
    assert "MCP_AUTH_ENABLED=true requires MCP_API_KEY" in message
    assert "valid-test-token" not in message


def test_auth_enabled_accepts_non_default_api_key() -> None:
    settings = Settings(
        _env_file=None,
        mcp_auth_enabled=True,
        mcp_api_key="valid-test-token",
    )

    assert settings.mcp_auth_enabled is True
    assert settings.mcp_api_key == "valid-test-token"


def test_static_bearer_verifier_repr_redacts_token() -> None:
    verifier = StaticBearerTokenVerifier("valid-test-token")

    assert "valid-test-token" not in repr(verifier)
    assert "<redacted>" in repr(verifier)


def test_create_mcp_server_supports_auth_enabled() -> None:
    settings = Settings(
        _env_file=None,
        mcp_auth_enabled=True,
        mcp_api_key="valid-test-token",
    )

    server = create_mcp_server(settings)

    assert server.name == settings.mcp_server_name


def test_auth_related_keys_are_redacted() -> None:
    redacted = redact_sensitive_values(
        {
            "mcp_api_key": "valid-test-token",
            "bearer_token": "valid-test-token",
            "nested": {"Authorization": "Bearer valid-test-token"},
        }
    )

    assert redacted["mcp_api_key"] == "[REDACTED]"
    assert redacted["bearer_token"] == "[REDACTED]"
    assert redacted["nested"]["Authorization"] == "[REDACTED]"
    assert "valid-test-token" not in str(redacted)


def test_auth_related_text_patterns_are_redacted() -> None:
    text = (
        "Authorization: Bearer valid-test-token "
        "serviceKey=SECRET-SERVICE-KEY MCP_API_KEY=SECRET-MCP"
    )

    redacted = redact_sensitive_text(text)

    assert "valid-test-token" not in redacted
    assert "SECRET-SERVICE-KEY" not in redacted
    assert "SECRET-MCP" not in redacted
    assert "[REDACTED]" in redacted


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mcp_max_request_body_bytes": 0},
        {"mcp_tool_input_max_chars": 0},
        {"mcp_rate_limit_enabled": True, "mcp_rate_limit_per_minute": 0},
        {"mcp_rate_limit_enabled": True, "mcp_rate_limit_window_seconds": 0},
    ],
)
def test_mcp_security_settings_reject_invalid_limits(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)
