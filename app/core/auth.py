from __future__ import annotations

import secrets

from fastmcp.server.auth import AccessToken, TokenVerifier


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
