from __future__ import annotations

import pytest

from app.adapters.http_pool import close_shared_http_client
from app.core.config import get_settings
from app.core.metrics import metrics_registry
from app.mcp.tools import reset_tool_services


@pytest.fixture(autouse=True)
def reset_settings_and_services(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_MODE", "mock")
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    monkeypatch.setenv("MCP_AUTH_MODE", "none")
    monkeypatch.setenv("MCP_AUTH_ENABLED", "false")
    get_settings.cache_clear()
    metrics_registry.reset()
    reset_tool_services()
    yield
    get_settings.cache_clear()
    metrics_registry.reset()
    reset_tool_services()


@pytest.fixture(autouse=True)
async def close_http_pool_after_test():
    yield
    await close_shared_http_client()
