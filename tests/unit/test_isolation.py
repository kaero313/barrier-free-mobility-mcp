from __future__ import annotations

import socket

import httpx
import pytest

from app.core.config import Settings, get_settings


def test_settings_do_not_load_env_file_or_keys() -> None:
    settings = get_settings()
    key_fields = [name for name in Settings.model_fields if name.endswith("_key")]
    keys = {name: getattr(settings, name) for name in key_fields}

    assert Settings.model_config["env_file"] is None
    assert keys.pop("mcp_api_key") == "change-me"
    assert keys
    assert set(keys.values()) == {""}


def test_external_name_lookup_is_blocked() -> None:
    with pytest.raises(RuntimeError, match="must not reach external hosts"):
        socket.getaddrinfo("apis.data.go.kr", 443)


def test_external_connect_is_blocked() -> None:
    with socket.socket() as sock, pytest.raises(RuntimeError, match="external hosts"):
        sock.connect(("203.0.113.10", 443))


async def test_external_http_request_is_blocked() -> None:
    async with httpx.AsyncClient(timeout=1) as client:
        with pytest.raises(RuntimeError, match="external hosts"):
            await client.get("https://apis.data.go.kr/")


def test_loopback_lookup_is_allowed() -> None:
    assert socket.getaddrinfo("localhost", 80)
