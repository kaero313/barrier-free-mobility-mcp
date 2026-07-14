from __future__ import annotations

import secrets
import time

import httpx
from fastmcp.server.auth import (
    AccessToken,
    AuthProvider,
    JWTVerifier,
    RemoteAuthProvider,
    TokenVerifier,
)
from pydantic import AnyHttpUrl

from app.core.config import McpAuthMode, Settings


class StaticBearerTokenVerifier(TokenVerifier):
    """Validate one configured MCP bearer token without exposing it."""

    def __init__(self, api_key: str, *, base_url: str | None = None) -> None:
        super().__init__(
            base_url=base_url or None,
            required_scopes=["mcp:read"],
            resource_base_url=base_url or None,
        )
        self._api_key = api_key

    def __repr__(self) -> str:
        return "StaticBearerTokenVerifier(api_key=<redacted>)"

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or not secrets.compare_digest(token, self._api_key):
            return None

        return AccessToken(
            token="<redacted>",
            client_id="static-mcp-client",
            scopes=["mcp:read"],
            subject="static-bearer",
        )


class OidcJwtTokenVerifier(JWTVerifier):
    """Require user-bound expiring OIDC tokens and redact them after validation."""

    async def verify_token(self, token: str) -> AccessToken | None:
        access_token = await super().verify_token(token)
        if access_token is None:
            return None

        claims = access_token.claims
        expires_at = claims.get("exp")
        subject = claims.get("sub")
        not_before = claims.get("nbf")
        if not isinstance(expires_at, (int, float)):
            return None
        if not isinstance(subject, str) or not subject.strip():
            return None
        if not_before is not None and (
            not isinstance(not_before, (int, float)) or not_before > time.time()
        ):
            return None

        return access_token.model_copy(
            update={
                "token": "<redacted>",
                "subject": subject,
            }
        )


def create_oidc_token_verifier(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> OidcJwtTokenVerifier:
    """Build the OIDC JWT verifier without contacting the issuer at startup."""

    return OidcJwtTokenVerifier(
        jwks_uri=settings.mcp_oidc_jwks_url,
        issuer=settings.mcp_oidc_issuer_url,
        audience=settings.mcp_oidc_audience,
        algorithm=settings.mcp_oidc_algorithm,
        required_scopes=settings.mcp_oidc_scope_list,
        ssrf_safe=settings.mcp_oidc_jwks_ssrf_safe,
        http_client=http_client,
    )


def create_auth_provider(settings: Settings) -> AuthProvider | None:
    """Create the configured MCP auth provider while preserving legacy static auth."""

    auth_mode = settings.effective_mcp_auth_mode
    if auth_mode == McpAuthMode.NONE:
        return None
    if auth_mode == McpAuthMode.STATIC:
        return StaticBearerTokenVerifier(
            settings.mcp_api_key,
            base_url=settings.mcp_public_base_url or None,
        )

    token_verifier = create_oidc_token_verifier(settings)
    public_base_url = AnyHttpUrl(settings.mcp_public_base_url)
    return RemoteAuthProvider(
        token_verifier=token_verifier,
        authorization_servers=[AnyHttpUrl(settings.mcp_oidc_issuer_url)],
        base_url=public_base_url,
        resource_base_url=public_base_url,
        scopes_supported=settings.mcp_oidc_scope_list,
        resource_name=settings.mcp_server_name,
    )
