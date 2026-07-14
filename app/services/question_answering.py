from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.schemas.accessibility import (
    AccessibilityQuestionResult,
    AccessibilityResult,
    AlternativeRequestKind,
    FacilityQuestionKind,
    MobilityProfile,
    ParsedAccessibilityQuestion,
)
from app.schemas.facility import AccessibleFacility, FacilityType
from app.services.alternative_message import (
    build_route_alternative_message,
    build_station_facility_alternative_message,
)
from app.services.facility_question import build_facility_question_result
from app.services.facility_service import FacilityService
from app.services.question_clarification import (
    build_question_clarification_result,
    question_clarification_reason,
)
from app.services.question_parser import parse_accessibility_question
from app.services.station_context import StationLookupContext, resolve_station_context
from app.services.station_service import StationService
from app.services.types import ServiceResult

TripAnswerer = Callable[
    [str, str, MobilityProfile],
    Awaitable[AccessibilityResult],
]


async def answer_accessibility_question(
    question: str,
    *,
    station_service: StationService,
    facility_service: FacilityService,
    trip_answerer: TripAnswerer,
) -> AccessibilityQuestionResult:
    parsed_question = parse_accessibility_question(question)
    parsed = parsed_question.parsed
    clarification_reason = question_clarification_reason(
        intent=parsed_question.intent,
        parsed=parsed,
        station_service=station_service,
    )
    if clarification_reason:
        return build_question_clarification_result(
            question=question,
            intent=parsed_question.intent,
            parsed=parsed,
            reason=clarification_reason,
        )

    if parsed_question.intent == "facility_status":
        return await _answer_facility_question(
            question,
            parsed,
            station_service=station_service,
            facility_service=facility_service,
        )
    if parsed_question.intent == "alternative_request":
        return await _answer_alternative_question(
            question,
            parsed,
            station_service=station_service,
            facility_service=facility_service,
            trip_answerer=trip_answerer,
        )

    assert parsed.origin is not None
    assert parsed.destination is not None
    result = await trip_answerer(
        parsed.origin,
        parsed.destination,
        parsed.mobility_profile,
    )
    return AccessibilityQuestionResult(
        question=question,
        status=result.status,
        intent=parsed_question.intent,
        parsed=parsed,
        result=result,
        user_message=result.user_message,
        clarification_needed=result.clarification_needed,
        questions=result.questions,
        available_partial_info=result.available_partial_info,
    )


async def _answer_facility_question(
    question: str,
    parsed: ParsedAccessibilityQuestion,
    *,
    station_service: StationService,
    facility_service: FacilityService,
) -> AccessibilityQuestionResult:
    context = _resolved_facility_context(parsed, station_service)
    service_results = await _lookup_requested_facilities(
        parsed,
        context,
        facility_service,
    )
    facility_result = build_facility_question_result(
        station_name=context.station_name,
        line=context.line,
        question_kind=parsed.facility_question_kind or FacilityQuestionKind.OVERVIEW,
        service_results=service_results,
    )
    normalized_parsed = _with_resolved_facility_context(parsed, context)
    return AccessibilityQuestionResult(
        question=question,
        status=facility_result.status,
        intent="facility_status",
        parsed=normalized_parsed,
        result=None,
        facility_result=facility_result,
        user_message=facility_result.user_message,
        clarification_needed=False,
        questions=[],
        available_partial_info=[],
    )


async def _answer_alternative_question(
    question: str,
    parsed: ParsedAccessibilityQuestion,
    *,
    station_service: StationService,
    facility_service: FacilityService,
    trip_answerer: TripAnswerer,
) -> AccessibilityQuestionResult:
    if parsed.alternative_request_kind == AlternativeRequestKind.STATION_FACILITY:
        return await _answer_station_facility_alternative(
            question,
            parsed,
            station_service=station_service,
            facility_service=facility_service,
        )
    return await _answer_route_alternative(question, parsed, trip_answerer)


async def _answer_station_facility_alternative(
    question: str,
    parsed: ParsedAccessibilityQuestion,
    *,
    station_service: StationService,
    facility_service: FacilityService,
) -> AccessibilityQuestionResult:
    context = _resolved_facility_context(parsed, station_service)
    service_results = await _lookup_requested_facilities(
        parsed,
        context,
        facility_service,
    )
    facility_result = build_facility_question_result(
        station_name=context.station_name,
        line=context.line,
        question_kind=parsed.facility_question_kind or FacilityQuestionKind.OVERVIEW,
        service_results=service_results,
    )
    normalized_parsed = _with_resolved_facility_context(parsed, context)
    return AccessibilityQuestionResult(
        question=question,
        status=facility_result.status,
        intent="alternative_request",
        parsed=normalized_parsed,
        facility_result=facility_result,
        user_message=build_station_facility_alternative_message(facility_result),
        clarification_needed=False,
    )


async def _answer_route_alternative(
    question: str,
    parsed: ParsedAccessibilityQuestion,
    trip_answerer: TripAnswerer,
) -> AccessibilityQuestionResult:
    assert parsed.origin is not None
    assert parsed.destination is not None
    result = await trip_answerer(
        parsed.origin,
        parsed.destination,
        parsed.mobility_profile,
    )
    return AccessibilityQuestionResult(
        question=question,
        status=result.status,
        intent="alternative_request",
        parsed=parsed,
        result=result,
        user_message=build_route_alternative_message(result),
        clarification_needed=result.clarification_needed,
        questions=result.questions,
        available_partial_info=result.available_partial_info,
    )


def _resolved_facility_context(
    parsed: ParsedAccessibilityQuestion,
    station_service: StationService,
) -> StationLookupContext:
    assert parsed.target_station is not None
    assert parsed.facility_types
    return resolve_station_context(
        station_service,
        parsed.target_station,
        explicit_line=parsed.target_line,
    )


def _with_resolved_facility_context(
    parsed: ParsedAccessibilityQuestion,
    context: StationLookupContext,
) -> ParsedAccessibilityQuestion:
    return parsed.model_copy(
        update={
            "target_station": context.station_name,
            "target_line": context.line,
        }
    )


async def _lookup_requested_facilities(
    parsed: ParsedAccessibilityQuestion,
    context: StationLookupContext,
    facility_service: FacilityService,
) -> dict[FacilityType, ServiceResult[list[AccessibleFacility]]]:
    service_results: dict[
        FacilityType,
        ServiceResult[list[AccessibleFacility]],
    ] = {}
    for facility_type in parsed.facility_types:
        if facility_type == FacilityType.ELEVATOR:
            service_results[facility_type] = (
                await facility_service.get_elevator_status(
                    context.station_name,
                    line=context.line,
                )
            )
        elif facility_type == FacilityType.ACCESSIBLE_RESTROOM:
            service_results[facility_type] = (
                await facility_service.get_accessible_restroom(
                    context.station_name,
                    line=context.line,
                )
            )
    return service_results
