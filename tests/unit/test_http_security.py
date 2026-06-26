from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core.config import Settings, get_settings
from app.core.http_security import build_http_security_middleware
from app.mcp import tools


async def test_request_body_limit_returns_413_without_echoing_body() -> None:
    app = _app(
        Settings(
            _env_file=None,
            mcp_max_request_body_bytes=8,
            mcp_rate_limit_enabled=False,
        )
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/mcp", content=b"0123456789SECRET")

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}
    assert "SECRET" not in response.text


async def test_rate_limit_returns_429_for_mcp_path() -> None:
    app = _app(
        Settings(
            _env_file=None,
            mcp_rate_limit_enabled=True,
            mcp_rate_limit_per_minute=2,
            mcp_rate_limit_window_seconds=60,
        )
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/mcp")
        second = await client.get("/mcp")
        third = await client.get("/mcp")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json() == {"detail": "Too Many Requests"}


async def test_rate_limit_does_not_apply_to_health_path() -> None:
    app = _app(
        Settings(
            _env_file=None,
            mcp_rate_limit_enabled=True,
            mcp_rate_limit_per_minute=1,
            mcp_rate_limit_window_seconds=60,
        )
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/health")
        second = await client.get("/health")

    assert first.status_code == 200
    assert second.status_code == 200


async def test_tool_input_length_limit_rejects_long_station_without_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_TOOL_INPUT_MAX_CHARS", "3")
    get_settings.cache_clear()

    with pytest.raises(ValueError) as exc_info:
        await tools.resolve_station("abcdSECRET")

    message = str(exc_info.value)
    assert "query" in message
    assert "max length is 3" in message
    assert "abcdSECRET" not in message


def _app(settings: Settings) -> Starlette:
    return Starlette(
        routes=[
            Route("/mcp", _ok, methods=["GET", "POST"]),
            Route("/health", _ok, methods=["GET"]),
        ],
        middleware=build_http_security_middleware(settings),
    )


async def _ok(request: Request) -> JSONResponse:
    body = await request.body()
    return JSONResponse({"ok": True, "body_size": len(body)})
