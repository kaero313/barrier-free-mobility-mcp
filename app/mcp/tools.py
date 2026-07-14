from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

from app.cache.base import CacheProtocol
from app.cache.factory import build_cache
from app.core.config import get_settings
from app.core.metrics import metrics_registry
from app.schemas.accessibility import (
    AccessibilityQuestionResult,
    AccessibilityResult,
    MobilityProfile,
)
from app.schemas.lookup import FacilityLookupResult, RouteLookupResult
from app.schemas.station import StationResolutionResult
from app.services.accessibility_service import AccessibilityService
from app.services.facility_service import FacilityService
from app.services.lookup_result import (
    build_facility_lookup_result,
    build_route_lookup_result,
)
from app.services.route_service import RouteService
from app.services.route_station_codes import resolve_route_station_code
from app.services.station_context import resolve_station_context
from app.services.station_service import StationService

_cache: CacheProtocol | None = None
_station_service = StationService()
_facility_service: FacilityService | None = None
_route_service: RouteService | None = None
_accessibility_service: AccessibilityService | None = None

TOOL_DESCRIPTIONS = {
    "resolve_station": "Resolve a Seoul subway station name, line-aware name, or alias.",
    "get_station_facilities": (
        "Return a versioned FacilityLookupResult. Read normalized facilities from data; "
        "use status, outcome, failed_sources, limitations, and data_sources to distinguish "
        "empty results, failures, unsupported coverage, and stale fallback."
    ),
    "get_elevator_status": (
        "Return a versioned FacilityLookupResult with elevator records in data and "
        "structured metadata for empty, failed, unsupported, partial, or stale results."
    ),
    "get_accessible_restroom": (
        "Return a versioned FacilityLookupResult with accessible-restroom records in data "
        "and structured metadata describing result completeness."
    ),
    "get_route_candidates": (
        "Return a versioned RouteLookupResult with route candidates in data and structured "
        "metadata for empty, failed, partial, or stale results."
    ),
    "check_accessible_trip": (
        "Structured accessibility risk check. The result includes user_message, but "
        "generate_accessibility_brief is preferred for end-user final answers."
    ),
    "generate_accessibility_brief": (
        "LLM-facing final-answer tool. Return the result.user_message field verbatim "
        "to the end user whenever possible, preserving its Markdown headings, lists, "
        "and compact tables without wrapping them in a code block. Use "
        "accessibility_checks, evidence_sources, failed_sources, and limitations only "
        "as supporting evidence."
    ),
    "answer_accessibility_question": (
        "Preferred LLM-facing tool for ordinary Korean natural-language accessibility "
        "questions. Return the top-level user_message field verbatim to the end user "
        "whenever possible, preserving its Markdown headings, lists, and compact tables "
        "without wrapping them in a code block. This deterministic tool handles route "
        "accessibility and station elevator or accessible-restroom questions, including "
        "confirmed station facility and route alternatives. It asks for clarification "
        "when required station, line, facility, route, or mobility information is missing."
    ),
}


def reset_tool_services() -> None:
    global _cache, _facility_service, _route_service, _accessibility_service
    _cache = None
    _facility_service = None
    _route_service = None
    _accessibility_service = None


def configure_tool_cache(cache: CacheProtocol) -> None:
    global _cache
    reset_tool_services()
    _cache = cache


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
) -> FacilityLookupResult:
    """Return facilities and structured lookup completeness metadata."""
    _validate_text_inputs(station=station, line=line)

    async def operation() -> FacilityLookupResult:
        service_result = await _get_facility_service().get_station_facilities(
            station,
            line,
        )
        return build_facility_lookup_result(
            station=station,
            line=line,
            service_result=service_result,
        )

    return await _track_tool_call(
        "get_station_facilities",
        operation,
    )


async def get_elevator_status(
    station: str,
    line: str | None = None,
) -> FacilityLookupResult:
    """Return elevator records and structured lookup completeness metadata."""
    _validate_text_inputs(station=station, line=line)

    async def operation() -> FacilityLookupResult:
        service_result = await _get_facility_service().get_elevator_status(station, line)
        return build_facility_lookup_result(
            station=station,
            line=line,
            service_result=service_result,
        )

    return await _track_tool_call(
        "get_elevator_status",
        operation,
    )


async def get_accessible_restroom(
    station: str,
    line: str | None = None,
) -> FacilityLookupResult:
    """Return restroom records and structured lookup completeness metadata."""
    _validate_text_inputs(station=station, line=line)

    async def operation() -> FacilityLookupResult:
        service_result = await _get_facility_service().get_accessible_restroom(
            station,
            line,
        )
        return build_facility_lookup_result(
            station=station,
            line=line,
            service_result=service_result,
        )

    return await _track_tool_call(
        "get_accessible_restroom",
        operation,
    )


async def get_route_candidates(origin: str, destination: str) -> RouteLookupResult:
    """Return route candidates and structured lookup completeness metadata."""
    _validate_text_inputs(origin=origin, destination=destination)

    async def operation() -> RouteLookupResult:
        origin_context = resolve_station_context(_station_service, origin)
        destination_context = resolve_station_context(_station_service, destination)
        service_result = await _get_route_service().get_route_candidates(
            origin,
            destination,
            origin_station_code=resolve_route_station_code(
                origin_context.station_name,
                origin_context.line,
            ),
            destination_station_code=resolve_route_station_code(
                destination_context.station_name,
                destination_context.line,
            ),
        )
        return build_route_lookup_result(
            origin=origin,
            destination=destination,
            service_result=service_result,
        )

    return await _track_tool_call(
        "get_route_candidates",
        operation,
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
    """Final-answer tool; preserve result.user_message Markdown and display it verbatim."""
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


async def answer_accessibility_question(question: str) -> AccessibilityQuestionResult:
    """Final-answer tool for natural-language questions; preserve user_message Markdown."""
    _validate_text_inputs(question=question)
    return await _track_tool_call(
        "answer_accessibility_question",
        lambda: _get_accessibility_service().answer_accessibility_question(question),
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
        answer_accessibility_question,
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
) -> Any:
    started = perf_counter()
    try:
        result = operation()
        if inspect.isawaitable(result):
            result = await result
        response = result
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
