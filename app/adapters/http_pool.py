from __future__ import annotations

import httpx

from app.core.config import Settings

_shared_client: httpx.AsyncClient | None = None


def get_shared_http_client(settings: Settings) -> httpx.AsyncClient:
    """Return the process-wide public API client and reuse its connection pool."""

    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            limits=httpx.Limits(
                max_connections=settings.http_max_connections,
                max_keepalive_connections=settings.http_max_keepalive_connections,
                keepalive_expiry=settings.http_keepalive_expiry_seconds,
            ),
        )
    return _shared_client


async def close_shared_http_client() -> None:
    global _shared_client
    client = _shared_client
    _shared_client = None
    if client is not None and not client.is_closed:
        await client.aclose()
