from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from app.adapters.http_pool import close_shared_http_client
from app.api.routes import register_http_routes
from app.cache.factory import build_cache
from app.core.auth import create_auth_provider
from app.core.config import Settings, get_settings
from app.mcp.prompts import register_prompts, register_resources
from app.mcp.tools import configure_tool_cache, register_tools


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
    active_settings = settings or get_settings()
    auth = create_auth_provider(active_settings)
    cache = build_cache(active_settings)

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        try:
            yield {"cache": cache}
        finally:
            await cache.close()
            await close_shared_http_client()

    mcp = FastMCP(
        name=active_settings.mcp_server_name,
        auth=auth,
        lifespan=lifespan,
    )
    configure_tool_cache(cache)
    register_http_routes(mcp, active_settings, auth, cache)
    register_tools(mcp)
    register_prompts(mcp)
    register_resources(mcp)
    return mcp
