from __future__ import annotations

from app.adapters.http_pool import (
    close_shared_http_client,
    get_shared_http_client,
)
from app.core.config import Settings


async def test_http_pool_reuses_client_until_lifespan_close() -> None:
    settings = Settings(_env_file=None)

    first = get_shared_http_client(settings)
    second = get_shared_http_client(settings)

    assert first is second
    assert first.is_closed is False

    await close_shared_http_client()
    replacement = get_shared_http_client(settings)

    assert first.is_closed is True
    assert replacement is not first
