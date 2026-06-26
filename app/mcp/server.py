from __future__ import annotations

from fastmcp import FastMCP

from app.api.routes import register_http_routes
from app.core.auth import StaticBearerTokenVerifier
from app.core.config import Settings, get_settings
from app.mcp.prompts import register_prompts, register_resources
from app.mcp.tools import register_tools


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
    active_settings = settings or get_settings()
    auth = None
    if active_settings.mcp_auth_enabled:
        auth = StaticBearerTokenVerifier(
            active_settings.mcp_api_key,
            base_url=active_settings.mcp_public_base_url or None,
        )

    mcp = FastMCP(name=active_settings.mcp_server_name, auth=auth)
    register_http_routes(mcp, active_settings)
    register_tools(mcp)
    register_prompts(mcp)
    register_resources(mcp)
    return mcp
