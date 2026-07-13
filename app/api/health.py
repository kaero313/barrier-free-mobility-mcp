from __future__ import annotations

from typing import Any

from app.cache.factory import redis_cache_available
from app.core.config import AppMode, CacheBackend, Settings, get_settings
from app.core.time import utc_now


async def health(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    public_apis = _public_api_status(settings)
    cache_status = await _cache_status(settings)
    warnings = _warnings(settings, public_apis, cache_status)
    return {
        "status": "degraded" if warnings else "ok",
        "generated_at": utc_now().isoformat(),
        "app": {
            "env": settings.app_env,
            "mode": settings.app_mode,
        },
        "mcp": {
            "server_name": settings.mcp_server_name,
            "transport": settings.mcp_transport,
            "path": settings.mcp_path,
            "auth_enabled": settings.mcp_auth_enabled,
            "public_base_url_configured": bool(settings.mcp_public_base_url.strip()),
            "request_body_limit_enabled": settings.mcp_request_body_limit_enabled,
            "max_request_body_bytes": settings.mcp_max_request_body_bytes,
            "tool_input_max_chars": settings.mcp_tool_input_max_chars,
            "rate_limit_enabled": settings.mcp_rate_limit_enabled,
            "rate_limit_per_minute": settings.mcp_rate_limit_per_minute,
        },
        "dependencies": {
            "cache": {
                "backend": settings.cache_backend,
                "status": cache_status,
            },
            "public_apis": public_apis,
        },
        "warnings": warnings,
    }


def _public_api_status(settings: Settings) -> dict[str, dict[str, bool | str]]:
    required = settings.app_mode == AppMode.LIVE
    sources = {
        "facility_info": {
            "endpoint_configured": bool(settings.facility_api_url.strip()),
            "key_configured": bool(settings.public_data_service_key.strip()),
        },
        "shortest_route": {
            "endpoint_configured": bool(settings.shortest_route_api_url.strip()),
            "key_configured": bool(settings.public_data_service_key.strip()),
        },
        "elevator_status": {
            "endpoint_configured": bool(settings.elevator_status_api_url.strip()),
            "key_configured": bool(
                settings.elevator_status_api_key.strip() or settings.seoul_open_api_key.strip()
            ),
        },
        "elevator_info": {
            "endpoint_configured": bool(settings.elevator_info_api_url.strip()),
            "key_configured": bool(
                settings.elevator_info_api_key.strip() or settings.seoul_open_api_key.strip()
            ),
        },
        "restroom": {
            "endpoint_configured": bool(settings.restroom_api_url.strip()),
            "key_configured": bool(
                settings.restroom_api_key.strip() or settings.seoul_open_api_key.strip()
            ),
        },
    }
    return {
        name: {
            **status,
            "required": required,
            "status": _source_status(status, required=required),
        }
        for name, status in sources.items()
    }


def _source_status(status: dict[str, bool], *, required: bool) -> str:
    if not required:
        return "not_required"
    if status["endpoint_configured"] and status["key_configured"]:
        return "ok"
    return "missing_config"


async def _cache_status(settings: Settings) -> str:
    if settings.cache_backend == CacheBackend.MEMORY:
        return "ok"
    if settings.cache_backend == CacheBackend.REDIS:
        return "ok" if await redis_cache_available(settings) else "unavailable"
    return "unknown"


def _warnings(
    settings: Settings,
    public_apis: dict[str, dict[str, bool | str]],
    cache_status: str,
) -> list[str]:
    warnings: list[str] = []
    if settings.cache_backend == CacheBackend.REDIS and cache_status != "ok":
        warnings.append("Redis cache backend is configured but unavailable.")
    missing_sources = [
        source_name
        for source_name, status in public_apis.items()
        if status["required"] and status["status"] != "ok"
    ]
    if missing_sources:
        warnings.append(
            "Live mode public API configuration is incomplete for: "
            + ", ".join(sorted(missing_sources))
        )
    return warnings
