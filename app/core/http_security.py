from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from time import monotonic

from starlette.middleware import Middleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings

JsonBody = bytes


class HttpSecurityMiddleware:
    """Apply lightweight HTTP protections before FastMCP handles requests."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if self._rate_limit_applies(path) and not self._allow_request(scope, path):
            await _send_json(
                send,
                429,
                b'{"detail":"Too Many Requests"}',
            )
            return

        if self.settings.mcp_request_body_limit_enabled:
            body, too_large = await _read_limited_body(
                receive,
                self.settings.mcp_max_request_body_bytes,
            )
            if too_large:
                await _send_json(
                    send,
                    413,
                    b'{"detail":"Request body too large"}',
                )
                return
            await self.app(scope, _replay_body(body, receive), send)
            return

        await self.app(scope, receive, send)

    def _rate_limit_applies(self, path: str) -> bool:
        return self.settings.mcp_rate_limit_enabled and (
            _path_matches(path, self.settings.mcp_path) or path == "/metrics"
        )

    def _allow_request(self, scope: Scope, path: str) -> bool:
        client = scope.get("client")
        client_host = client[0] if client else "unknown"
        key = f"{client_host}:{path}"
        now = monotonic()
        window_start = now - self.settings.mcp_rate_limit_window_seconds
        request_times = self._requests[key]
        while request_times and request_times[0] < window_start:
            request_times.popleft()
        if len(request_times) >= self.settings.mcp_rate_limit_per_minute:
            return False
        request_times.append(now)
        return True


def build_http_security_middleware(settings: Settings) -> list[Middleware]:
    return [Middleware(HttpSecurityMiddleware, settings=settings)]


async def _read_limited_body(receive: Receive, max_bytes: int) -> tuple[JsonBody, bool]:
    body_parts: list[bytes] = []
    total_bytes = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return b"".join(body_parts), False
        chunk = message.get("body", b"")
        if chunk:
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                return b"", True
            body_parts.append(chunk)
        if not message.get("more_body", False):
            return b"".join(body_parts), False


def _replay_body(body: bytes, receive: Receive) -> Callable[[], Awaitable[Message]]:
    sent = False
    receive_original = receive

    async def replay() -> Message:
        nonlocal sent
        if sent:
            return await receive_original()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return replay


async def _send_json(send: Send, status_code: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _path_matches(path: str, base_path: str) -> bool:
    normalized_base = base_path.rstrip("/") or "/"
    return path == normalized_base or path.startswith(normalized_base + "/")
