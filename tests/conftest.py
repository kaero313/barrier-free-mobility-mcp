from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.core.metrics import metrics_registry
from app.mcp.tools import reset_tool_services


@pytest.fixture(autouse=True)
def reset_settings_and_services(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_MODE", "mock")
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    get_settings.cache_clear()
    metrics_registry.reset()
    reset_tool_services()
    yield
    get_settings.cache_clear()
    metrics_registry.reset()
    reset_tool_services()
