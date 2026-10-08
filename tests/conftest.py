"""Shared test isolation.

Tests never read `.env`, never see `*_key` settings from the environment, and
cannot reach non-loopback hosts, including through a local proxy. Name lookups
are blocked as well because the Windows Proactor event loop connects without
calling `socket.connect`.
"""

from __future__ import annotations

import ipaddress
import os
import socket

import pytest

from app.adapters.http_pool import close_shared_http_client
from app.core.config import Settings, get_settings
from app.core.metrics import metrics_registry
from app.mcp.tools import reset_tool_services

Settings.model_config["env_file"] = None
for _field in Settings.model_fields:
    if _field.endswith("_key"):
        os.environ.pop(_field.upper(), None)
        os.environ.pop(_field, None)
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "*"

_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_GETADDRINFO = socket.getaddrinfo


def _is_loopback(host: str) -> bool:
    if host in {"", "localhost"}:
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _reject(host: str, port: object) -> None:
    raise RuntimeError(
        f"Tests must not reach external hosts ({host}:{port}). "
        "Use fixtures, respx, or monkeypatch instead."
    )


def _check_address(address: object) -> None:
    if isinstance(address, tuple) and len(address) >= 2 and not _is_loopback(str(address[0])):
        _reject(str(address[0]), address[1])


def _guarded_connect(self: socket.socket, address: object) -> None:
    _check_address(address)
    return _ORIGINAL_CONNECT(self, address)


def _guarded_connect_ex(self: socket.socket, address: object) -> int:
    _check_address(address)
    return _ORIGINAL_CONNECT_EX(self, address)


def _guarded_getaddrinfo(host: object, port: object, *args: object, **kwargs: object):
    name = host.decode() if isinstance(host, bytes) else ("" if host is None else str(host))
    if not _is_loopback(name):
        _reject(name, port)
    return _ORIGINAL_GETADDRINFO(host, port, *args, **kwargs)


def pytest_configure(config: pytest.Config) -> None:
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.getaddrinfo = _guarded_getaddrinfo


def pytest_unconfigure(config: pytest.Config) -> None:
    socket.socket.connect = _ORIGINAL_CONNECT
    socket.socket.connect_ex = _ORIGINAL_CONNECT_EX
    socket.getaddrinfo = _ORIGINAL_GETADDRINFO


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
