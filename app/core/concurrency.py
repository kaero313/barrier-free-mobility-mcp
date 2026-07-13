from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable


async def gather_limited[T](
    factories: Iterable[Callable[[], Awaitable[T]]],
    *,
    limit: int,
) -> list[T]:
    """Run independent async operations with a deterministic concurrency bound."""

    semaphore = asyncio.Semaphore(max(1, limit))

    async def run(factory: Callable[[], Awaitable[T]]) -> T:
        async with semaphore:
            return await factory()

    return list(await asyncio.gather(*(run(factory) for factory in factories)))
