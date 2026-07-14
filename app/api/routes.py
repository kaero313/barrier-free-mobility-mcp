from __future__ import annotations

from typing import Any

from fastmcp.server.auth import AuthProvider
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.health import health
from app.api.metrics import metrics
from app.cache.base import CacheProtocol
from app.core.config import Settings


def register_http_routes(
    mcp: Any,
    settings: Settings,
    auth_provider: AuthProvider | None,
    cache: CacheProtocol | None = None,
) -> None:
    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health_route(request: Request) -> Response:
        return JSONResponse(await health(settings, cache))

    @mcp.custom_route("/metrics", methods=["GET"], include_in_schema=False)
    async def metrics_route(request: Request) -> Response:
        if not await _authorized_for_metrics(request, settings, auth_provider):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return JSONResponse(metrics())


async def _authorized_for_metrics(
    request: Request,
    settings: Settings,
    auth_provider: AuthProvider | None,
) -> bool:
    if not settings.is_mcp_auth_enabled:
        return True
    if auth_provider is None:
        return False

    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        return False
    return await auth_provider.verify_token(token) is not None
