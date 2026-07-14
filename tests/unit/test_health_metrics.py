from __future__ import annotations

from unittest.mock import AsyncMock

import httpx

from app.api.health import health
from app.api.metrics import metrics
from app.core.config import AppMode, CacheBackend, McpAuthMode, Settings
from app.core.metrics import metrics_registry
from app.mcp import tools
from app.mcp.server import create_mcp_server
from app.schemas.accessibility import MobilityProfile
from app.schemas.common import CacheStatus

VALID_STATIC_TOKEN = "valid-test-token-with-at-least-32-characters"


async def test_health_reports_mock_mode_without_secrets() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.MOCK,
        public_data_service_key="SECRET-PUBLIC-DATA-KEY",
        mcp_api_key="SECRET-MCP-KEY",
    )

    payload = await health(settings)

    assert payload["status"] == "ok"
    assert payload["app"]["mode"] == AppMode.MOCK
    assert payload["mcp"]["auth_enabled"] is False
    assert payload["mcp"]["auth_mode"] == McpAuthMode.NONE
    assert payload["mcp"]["request_body_limit_enabled"] is True
    assert payload["mcp"]["max_request_body_bytes"] > 0
    assert payload["mcp"]["tool_input_max_chars"] > 0
    assert payload["mcp"]["rate_limit_enabled"] is False
    assert payload["dependencies"]["cache"]["backend"] == CacheBackend.MEMORY
    assert payload["dependencies"]["public_apis"]["facility_info"]["status"] == "not_required"
    assert "SECRET-PUBLIC-DATA-KEY" not in str(payload)
    assert "SECRET-MCP-KEY" not in str(payload)


async def test_health_reports_degraded_live_mode_when_config_is_missing() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        public_data_service_key="",
        seoul_open_api_key="",
        elevator_status_api_key="",
        elevator_info_api_key="",
        restroom_api_key="",
        facility_api_url="",
        shortest_route_api_url="",
        elevator_status_api_url="",
        elevator_info_api_url="",
        restroom_api_url="",
    )

    payload = await health(settings)

    assert payload["status"] == "degraded"
    assert payload["dependencies"]["public_apis"]["shortest_route"]["status"] == "missing_config"
    assert payload["warnings"]


async def test_health_reports_redis_cache_ok_without_secrets(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.health.redis_cache_available",
        AsyncMock(return_value=True),
    )
    settings = Settings(
        _env_file=None,
        cache_backend=CacheBackend.REDIS,
        redis_url="redis://:SECRET-REDIS-PASSWORD@localhost:6379/0",
    )

    payload = await health(settings)

    assert payload["status"] == "ok"
    assert payload["dependencies"]["cache"]["backend"] == CacheBackend.REDIS
    assert payload["dependencies"]["cache"]["status"] == "ok"
    assert "SECRET-REDIS-PASSWORD" not in str(payload)


async def test_health_reports_degraded_when_redis_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.health.redis_cache_available",
        AsyncMock(return_value=False),
    )
    settings = Settings(_env_file=None, cache_backend=CacheBackend.REDIS)

    payload = await health(settings)

    assert payload["status"] == "degraded"
    assert payload["dependencies"]["cache"]["status"] == "unavailable"
    assert "Redis cache backend is configured but unavailable." in payload["warnings"]


def test_metrics_registry_snapshot_counts_events() -> None:
    metrics_registry.record_tool_call(
        "check_accessible_trip",
        0.125,
        success=True,
        response_status="SUCCESS",
    )
    metrics_registry.record_public_api_call("facility_info", 0.25, success=False)
    metrics_registry.record_cache_event(CacheStatus.HIT)
    metrics_registry.record_fallback_response()

    payload = metrics()

    assert payload["mcp_tool_call_count"] == 1
    assert payload["public_api_call_count"] == 1
    assert payload["public_api_error_count"] == 1
    assert payload["fallback_response_count"] == 1
    assert payload["cache"]["HIT"] == 1
    assert payload["response_status"]["SUCCESS"] == 1


async def test_mcp_tool_calls_are_recorded_in_metrics() -> None:
    await tools.resolve_station("\ud64d\ub300\uc785\uad6c")
    await tools.check_accessible_trip(
        "\ud64d\ub300\uc785\uad6c",
        "\uc0bc\uc131",
        MobilityProfile(
            wheelchair=True,
            can_use_stairs=False,
            can_use_escalator=False,
            need_elevator_only=True,
        ),
    )

    payload = metrics()

    assert payload["mcp_tool_call_count"] == 2
    assert payload["tool_calls"]["resolve_station"]["count"] == 1
    assert payload["tool_calls"]["check_accessible_trip"]["count"] == 1
    assert payload["response_status"]["SUCCESS"] == 1


async def test_health_and_metrics_http_routes() -> None:
    settings = Settings(_env_file=None)
    server = create_mcp_server(settings)
    app = server.http_app(path=settings.mcp_path)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health_response = await client.get("/health")
        metrics_response = await client.get("/metrics")

    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
    assert metrics_response.status_code == 200
    assert "mcp_tool_call_count" in metrics_response.json()


async def test_metrics_http_route_requires_bearer_when_mcp_auth_is_enabled() -> None:
    settings = Settings(
        _env_file=None,
        mcp_auth_mode=McpAuthMode.STATIC,
        mcp_api_key=VALID_STATIC_TOKEN,
    )
    server = create_mcp_server(settings)
    app = server.http_app(path=settings.mcp_path)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get("/metrics")
        wrong_token = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer wrong-token"},
        )
        authorized = await client.get(
            "/metrics",
            headers={"Authorization": f"Bearer {VALID_STATIC_TOKEN}"},
        )

    assert unauthorized.status_code == 401
    assert wrong_token.status_code == 401
    assert authorized.status_code == 200
    assert VALID_STATIC_TOKEN not in authorized.text


async def test_health_reports_effective_oidc_mode_without_auth_configuration_details() -> None:
    settings = Settings(
        _env_file=None,
        mcp_auth_mode=McpAuthMode.OIDC,
        mcp_public_base_url="https://mcp.example.com",
        mcp_oidc_issuer_url="https://issuer.example",
        mcp_oidc_jwks_url="https://issuer.example/.well-known/jwks.json",
        mcp_oidc_audience="barrier-free-mcp",
    )

    payload = await health(settings)

    assert payload["mcp"]["auth_enabled"] is True
    assert payload["mcp"]["auth_mode"] == McpAuthMode.OIDC
    assert "issuer.example" not in str(payload)
    assert "barrier-free-mcp" not in str(payload)
