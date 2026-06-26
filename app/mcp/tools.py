from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

from app.cache.base import CacheProtocol
from app.cache.factory import build_cache
from app.core.config import get_settings
from app.core.metrics import metrics_registry
from app.schemas.accessibility import AccessibilityResult, MobilityProfile
from app.schemas.facility import AccessibleFacility
from app.schemas.route import RouteCandidate
from app.schemas.station import StationResolutionResult
from app.services.accessibility_service import AccessibilityService
from app.services.facility_service import FacilityService
from app.services.route_service import RouteService
from app.services.station_service import StationService

_cache: CacheProtocol | None = None
_station_service = StationService()
_facility_service: FacilityService | None = None
_route_service: RouteService | None = None
_accessibility_service: AccessibilityService | None = None

TOOL_DESCRIPTIONS = {
    "resolve_station": "Resolve a Seoul subway station name, line-aware name, or alias.",
    "get_station_facilities": "Return normalized station accessibility facilities.",
    "get_elevator_status": "Return normalized elevator operation status.",
    "get_accessible_restroom": "Return normalized accessible restroom information.",
    "get_route_candidates": "Return normalized subway route candidates.",
    "check_accessible_trip": (
        "Structured accessibility risk check. The result includes user_message, but "
        "generate_accessibility_brief is preferred for end-user final answers."
    ),
    "generate_accessibility_brief": (
        "LLM-facing final-answer tool. Return the result.user_message field verbatim "
        "to the end user whenever possible. Use accessibility_checks, evidence_sources, "
        "failed_sources, and limitations only as supporting evidence."
    ),
}


def reset_tool_services() -> None:
    global _cache, _facility_service, _route_service, _accessibility_service
    _cache = None
    _facility_service = None
    _route_service = None
    _accessibility_service = None


def _get_cache() -> CacheProtocol:
    global _cache
    if _cache is None:
        _cache = build_cache(get_settings())
    return _cache


def _get_facility_service() -> FacilityService:
    global _facility_service
    if _facility_service is None:
        _facility_service = FacilityService(get_settings(), _get_cache())
    return _facility_service


def _get_route_service() -> RouteService:
    global _route_service
    if _route_service is None:
        _route_service = RouteService(get_settings(), _get_cache())
    return _route_service


def _get_accessibility_service() -> AccessibilityService:
    global _accessibility_service
    if _accessibility_service is None:
        _accessibility_service = AccessibilityService(
            settings=get_settings(),
            cache=_get_cache(),
            station_service=_station_service,
            route_service=_get_route_service(),
            facility_service=_get_facility_service(),
        )
    return _accessibility_service


async def resolve_station(query: str) -> StationResolutionResult:
    """Resolve a station name, line-aware name, or alias."""
    _validate_text_inputs(query=query)
    return await _track_tool_call(
        "resolve_station",
        lambda: _station_service.resolve_station(query),
    )


async def get_station_facilities(
    station: str,
    line: str | None = None,
) -> list[AccessibleFacility]:
    """Return normalized station accessibility facilities."""
    _validate_text_inputs(station=station, line=line)
    return await _track_tool_call(
        "get_station_facilities",
        lambda: _get_facility_service().get_station_facilities(station, line),
        extract_value=True,
    )


async def get_elevator_status(
    station: str,
    line: str | None = None,
) -> list[AccessibleFacility]:
    """Return normalized elevator operation status."""
    _validate_text_inputs(station=station, line=line)
    return await _track_tool_call(
        "get_elevator_status",
        lambda: _get_facility_service().get_elevator_status(station, line),
        extract_value=True,
    )


async def get_accessible_restroom(
    station: str,
    line: str | None = None,
) -> list[AccessibleFacility]:
    """Return normalized accessible restroom information."""
    _validate_text_inputs(station=station, line=line)
    return await _track_tool_call(
        "get_accessible_restroom",
        lambda: _get_facility_service().get_accessible_restroom(station, line),
        extract_value=True,
    )


async def get_route_candidates(origin: str, destination: str) -> list[RouteCandidate]:
    """Return normalized route candidates."""
    _validate_text_inputs(origin=origin, destination=destination)
    return await _track_tool_call(
        "get_route_candidates",
        lambda: _get_route_service().get_route_candidates(origin, destination),
        extract_value=True,
    )


async def check_accessible_trip(
    origin: str,
    destination: str,
    mobility_profile: MobilityProfile,
) -> AccessibilityResult:
    """Structured accessibility check; prefer generate_accessibility_brief for final answers."""
    _validate_text_inputs(origin=origin, destination=destination)
    profile = MobilityProfile.model_validate(mobility_profile)
    return await _track_tool_call(
        "check_accessible_trip",
        lambda: _get_accessibility_service().check_accessible_trip(origin, destination, profile),
    )


async def generate_accessibility_brief(
    origin: str,
    destination: str,
    mobility_profile: MobilityProfile,
) -> AccessibilityResult:
    """Final-answer tool for LLM clients; display result.user_message verbatim."""
    _validate_text_inputs(origin=origin, destination=destination)
    profile = MobilityProfile.model_validate(mobility_profile)
    return await _track_tool_call(
        "generate_accessibility_brief",
        lambda: _get_accessibility_service().generate_accessibility_brief(
            origin,
            destination,
            profile,
        ),
    )


def register_tools(mcp: Any) -> None:
    for tool in (
        resolve_station,
        get_station_facilities,
        get_elevator_status,
        get_accessible_restroom,
        get_route_candidates,
        check_accessible_trip,
        generate_accessibility_brief,
    ):
        mcp.tool(description=TOOL_DESCRIPTIONS.get(tool.__name__))(tool)


def _validate_text_inputs(**fields: str | None) -> None:
    max_chars = get_settings().mcp_tool_input_max_chars
    for field_name, value in fields.items():
        if value is None:
            continue
        if len(value) > max_chars:
            raise ValueError(
                f"Input field '{field_name}' is too long; max length is {max_chars} characters."
            )


async def _track_tool_call[T](
    tool_name: str,
    operation: Callable[[], T | Awaitable[T]],
    *,
    extract_value: bool = False,
) -> Any:
    started = perf_counter()
    try:
        result = operation()
        if inspect.isawaitable(result):
            result = await result
        response = result.value if extract_value else result
    except Exception:
        metrics_registry.record_tool_call(
            tool_name,
            perf_counter() - started,
            success=False,
        )
        raise

    status = getattr(response, "status", None)
    response_status = getattr(status, "value", str(status)) if status is not None else None
    metrics_registry.record_tool_call(
        tool_name,
        perf_counter() - started,
        success=True,
        response_status=response_status,
    )
    return response
