from __future__ import annotations

import base64

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier, RSAKeyPair
from pydantic import ValidationError

from app.core.auth import (
    StaticBearerTokenVerifier,
    create_auth_provider,
    create_oidc_token_verifier,
)
from app.core.config import McpAuthMode, Settings
from app.core.security import redact_sensitive_text, redact_sensitive_values
from app.mcp.server import create_mcp_server

VALID_STATIC_TOKEN = "valid-test-token-with-at-least-32-characters"


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


@pytest.mark.parametrize(
    "api_key",
    [
        "",
        "change-me",
        "<long-random-token>",
        "replace-with-at-least-32-random-characters",
        "too-short",
    ],
)
def test_auth_enabled_rejects_empty_or_default_api_key(
    api_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MCP_AUTH_MODE", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, mcp_auth_enabled=True, mcp_api_key=api_key)

    message = str(exc_info.value)
    assert "MCP_AUTH_MODE=static requires MCP_API_KEY" in message
    assert "valid-test-token" not in message


def test_auth_enabled_accepts_non_default_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_AUTH_MODE", raising=False)
    settings = Settings(
        _env_file=None,
        mcp_auth_enabled=True,
        mcp_api_key=VALID_STATIC_TOKEN,
    )

    assert settings.mcp_auth_enabled is True
    assert settings.mcp_api_key == VALID_STATIC_TOKEN
    assert settings.effective_mcp_auth_mode == McpAuthMode.STATIC


def test_explicit_auth_mode_takes_precedence_over_legacy_flag() -> None:
    settings = Settings(
        _env_file=None,
        mcp_auth_mode=McpAuthMode.NONE,
        mcp_auth_enabled=True,
    )

    assert settings.effective_mcp_auth_mode == McpAuthMode.NONE
    assert settings.is_mcp_auth_enabled is False


def test_oidc_auth_requires_complete_configuration() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, mcp_auth_mode=McpAuthMode.OIDC)

    message = str(exc_info.value)
    assert "MCP_AUTH_MODE=oidc requires configuration" in message
    assert "MCP_OIDC_ISSUER_URL" in message
    assert "MCP_OIDC_JWKS_URL" in message
    assert "MCP_OIDC_AUDIENCE" in message
    assert "MCP_PUBLIC_BASE_URL" in message


def test_oidc_auth_rejects_symmetric_algorithm() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _oidc_settings(mcp_oidc_algorithm="HS256")

    assert "must be an asymmetric" in str(exc_info.value)


def test_oidc_scope_list_accepts_spaces_and_commas() -> None:
    settings = _oidc_settings(mcp_oidc_required_scopes="openid, mcp:read mcp:read")

    assert settings.mcp_oidc_scope_list == ["openid", "mcp:read"]


def test_static_bearer_verifier_repr_redacts_token() -> None:
    verifier = StaticBearerTokenVerifier("valid-test-token")

    assert "valid-test-token" not in repr(verifier)
    assert "<redacted>" in repr(verifier)


def test_create_mcp_server_supports_auth_enabled() -> None:
    settings = Settings(
        _env_file=None,
        mcp_auth_mode=McpAuthMode.STATIC,
        mcp_api_key=VALID_STATIC_TOKEN,
    )

    server = create_mcp_server(settings)

    assert server.name == settings.mcp_server_name


def test_auth_factory_builds_none_static_and_oidc_modes() -> None:
    assert create_auth_provider(Settings(_env_file=None)) is None

    static_provider = create_auth_provider(
        Settings(
            _env_file=None,
            mcp_auth_mode=McpAuthMode.STATIC,
            mcp_api_key=VALID_STATIC_TOKEN,
        )
    )
    assert isinstance(static_provider, StaticBearerTokenVerifier)

    oidc_provider = create_auth_provider(_oidc_settings())
    assert isinstance(oidc_provider, RemoteAuthProvider)
    assert isinstance(oidc_provider.token_verifier, JWTVerifier)
    assert oidc_provider.token_verifier.required_scopes == ["mcp:read"]


async def test_oidc_verifier_accepts_valid_jwt_from_jwks() -> None:
    settings = _oidc_settings()
    key_pair = RSAKeyPair.generate()
    token = key_pair.create_token(
        subject="test-user",
        issuer=settings.mcp_oidc_issuer_url,
        audience=settings.mcp_oidc_audience,
        scopes=["mcp:read"],
        kid="test-key",
    )

    async with _jwks_client(key_pair, "test-key") as client:
        verifier = create_oidc_token_verifier(settings, http_client=client)
        access_token = await verifier.verify_token(token)

    assert access_token is not None
    assert access_token.client_id == "test-user"
    assert access_token.scopes == ["mcp:read"]
    assert access_token.token == "<redacted>"
    assert access_token.subject == "test-user"


async def test_oidc_server_publishes_protected_resource_metadata() -> None:
    settings = _oidc_settings()
    server = create_mcp_server(settings)
    app = server.http_app(path=settings.mcp_path)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    assert response.json() == {
        "resource": "https://mcp.example.com/mcp",
        "authorization_servers": ["https://issuer.example/"],
        "scopes_supported": ["mcp:read"],
        "bearer_methods_supported": ["header"],
        "resource_name": settings.mcp_server_name,
    }


async def test_oidc_metrics_route_uses_same_jwt_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _oidc_settings()
    key_pair = RSAKeyPair.generate()
    verifier = JWTVerifier(
        public_key=key_pair.public_key,
        issuer=settings.mcp_oidc_issuer_url,
        audience=settings.mcp_oidc_audience,
        algorithm="RS256",
        required_scopes=["mcp:read"],
    )
    monkeypatch.setattr(
        "app.core.auth.create_oidc_token_verifier",
        lambda active_settings: verifier,
    )
    token = key_pair.create_token(
        subject="test-user",
        issuer=settings.mcp_oidc_issuer_url,
        audience=settings.mcp_oidc_audience,
        scopes=["mcp:read"],
    )
    app = create_mcp_server(settings).http_app(path=settings.mcp_path)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get("/metrics")
        authorized = await client.get(
            "/metrics",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert token not in authorized.text


async def test_oidc_verifier_rejects_token_signed_by_unknown_key() -> None:
    settings = _oidc_settings()
    trusted_key_pair = RSAKeyPair.generate()
    untrusted_key_pair = RSAKeyPair.generate()
    token = untrusted_key_pair.create_token(
        subject="test-user",
        issuer=settings.mcp_oidc_issuer_url,
        audience=settings.mcp_oidc_audience,
        scopes=["mcp:read"],
        kid="test-key",
    )

    async with _jwks_client(trusted_key_pair, "test-key") as client:
        verifier = create_oidc_token_verifier(settings, http_client=client)
        access_token = await verifier.verify_token(token)

    assert access_token is None


@pytest.mark.parametrize(
    "additional_claims",
    [
        {"exp": None},
        {"sub": ""},
        {"nbf": 4_102_444_800},
    ],
)
async def test_oidc_verifier_requires_expiring_user_bound_token(
    additional_claims: dict[str, object],
) -> None:
    settings = _oidc_settings()
    key_pair = RSAKeyPair.generate()
    token = key_pair.create_token(
        subject="test-user",
        issuer=settings.mcp_oidc_issuer_url,
        audience=settings.mcp_oidc_audience,
        scopes=["mcp:read"],
        additional_claims=additional_claims,
        kid="test-key",
    )

    async with _jwks_client(key_pair, "test-key") as client:
        verifier = create_oidc_token_verifier(settings, http_client=client)
        access_token = await verifier.verify_token(token)

    assert access_token is None


@pytest.mark.parametrize(
    ("issuer", "audience", "scopes", "expires_in_seconds"),
    [
        ("https://wrong-issuer.example", "barrier-free-mcp", ["mcp:read"], 3600),
        ("https://issuer.example", "wrong-audience", ["mcp:read"], 3600),
        ("https://issuer.example", "barrier-free-mcp", ["openid"], 3600),
        ("https://issuer.example", "barrier-free-mcp", ["mcp:read"], -1),
    ],
)
async def test_oidc_verifier_rejects_invalid_claims_without_logging_token(
    issuer: str,
    audience: str,
    scopes: list[str],
    expires_in_seconds: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _oidc_settings()
    key_pair = RSAKeyPair.generate()
    token = key_pair.create_token(
        subject="test-user",
        issuer=issuer,
        audience=audience,
        scopes=scopes,
        expires_in_seconds=expires_in_seconds,
        kid="test-key",
    )

    async with _jwks_client(key_pair, "test-key") as client:
        verifier = create_oidc_token_verifier(settings, http_client=client)
        access_token = await verifier.verify_token(token)

    assert access_token is None
    assert token not in caplog.text


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


def _oidc_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "mcp_auth_mode": McpAuthMode.OIDC,
        "mcp_public_base_url": "https://mcp.example.com",
        "mcp_oidc_issuer_url": "https://issuer.example",
        "mcp_oidc_jwks_url": "https://issuer.example/.well-known/jwks.json",
        "mcp_oidc_audience": "barrier-free-mcp",
        "mcp_oidc_required_scopes": "mcp:read",
        "mcp_oidc_jwks_ssrf_safe": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _jwks_client(key_pair: RSAKeyPair, kid: str) -> httpx.AsyncClient:
    public_key = load_pem_public_key(key_pair.public_key.encode("utf-8"))
    assert isinstance(public_key, RSAPublicKey)
    numbers = public_key.public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n": _base64url_uint(numbers.n),
                "e": _base64url_uint(numbers.e),
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=jwks, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _base64url_uint(value: int) -> str:
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
