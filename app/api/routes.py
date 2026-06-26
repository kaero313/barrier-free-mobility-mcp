from __future__ import annotations

import secrets
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.health import health
from app.api.metrics import metrics
from app.core.config import Settings


def register_http_routes(mcp: Any, settings: Settings) -> None:
    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health_route(request: Request) -> Response:
        return JSONResponse(health(settings))

    @mcp.custom_route("/metrics", methods=["GET"], include_in_schema=False)
    async def metrics_route(request: Request) -> Response:
        if not _authorized_for_metrics(request, settings):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return JSONResponse(metrics())


def _authorized_for_metrics(request: Request, settings: Settings) -> bool:
    if not settings.mcp_auth_enabled:
        return True

    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        return False
    return secrets.compare_digest(token, settings.mcp_api_key)
