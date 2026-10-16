from __future__ import annotations

from app.engine.route_ranking import (
    RouteCandidateAssessment,
    build_alternative_routes,
)
from app.normalizers.facility_identity import facility_record_identity
from app.normalizers.helpers import normalize_station_name, transfer_text
from app.schemas.accessibility import (
    AccessibilityResult,
    AlternativeRoute,
    MobilityProfile,
)
from app.schemas.common import DataSourceMeta, FailedSource, ResponseStatus
from app.schemas.facility import AccessibleFacility, FacilityType
from app.schemas.route import RouteCandidate
from app.services.evidence import build_evidence_context
from app.services.result_metadata import (
    dedupe_data_sources,
    dedupe_failed_sources,
    dedupe_strings,
)
from app.services.station_context import StationLookupContext
from app.services.user_message import build_user_message_context
from app.services.user_message_accessibility import station_label
from app.services.user_message_sources import (
    NO_ROUTE_LIMITATION,
    REPRESENTATIVE_FACILITY_LIMITATION,
)


def build_station_clarification_result(
    *,
    origin: str,
    destination: str,
    mobility_profile: MobilityProfile,
    origin_context: StationLookupContext,
    destination_context: StationLookupContext,
) -> AccessibilityResult:
    failed = [
        FailedSource(source_name="station_resolution", reason="needs_clarification")
    ]
    context_messages = [
        context.clarification_message
        for context in (origin_context, destination_context)
        if context.needs_clarification and context.clarification_message
    ]
    limitations = dedupe_strings(
        [
            "현재 검증된 역·호선 목록에서 역을 확정할 수 없어 "
            "경로 접근성 판단을 수행하지 못했습니다.",
            *context_messages,
        ]
    )
    evidence_context = build_evidence_context(
        status=ResponseStatus.FAILED,
        risk_level="UNKNOWN",
        data_sources=[],
        failed_sources=failed,
        limitations=limitations,
    )
    result = AccessibilityResult(
        status=ResponseStatus.NEEDS_CLARIFICATION,
        origin=origin,
        destination=destination,
        mobility_profile=mobility_profile,
        risk_level="UNKNOWN",
        risk_score=25,
        route_summary=_station_clarification_summary(origin_context, destination_context),
        failed_sources=failed,
        limitations=limitations,
        clarification_needed=True,
        questions=dedupe_strings(
            [
                *context_messages,
                "출발역과 도착역을 지하철역 이름과 호선 기준으로 다시 확인해 주세요.",
            ]
        ),
        # 역을 확정하기 전에는 확인한 정보가 없다. 기능 소개 문장을 부분 확인 정보로 쓰지 않는다.
        available_partial_info=[],
        **evidence_context,
    )
    return _with_user_message(result)


def build_no_route_result(
    *,
    origin: str,
    destination: str,
    mobility_profile: MobilityProfile,
    data_sources: list[DataSourceMeta],
    failed_sources: list[FailedSource],
    limitations: list[str],
    line_mismatches: list[str] | None = None,
) -> AccessibilityResult:
    deduped_sources = dedupe_data_sources(data_sources)
    deduped_failed = dedupe_failed_sources(failed_sources)
    merged_limitations = dedupe_strings(
        [
            *limitations,
            NO_ROUTE_LIMITATION,
        ]
    )
    evidence_context = build_evidence_context(
        status=ResponseStatus.FAILED,
        risk_level="UNKNOWN",
        data_sources=deduped_sources,
        failed_sources=deduped_failed,
        limitations=merged_limitations,
    )
    result = AccessibilityResult(
        status=ResponseStatus.FAILED,
        origin=origin,
        destination=destination,
        mobility_profile=mobility_profile,
        risk_level="UNKNOWN",
        risk_score=0,
        route_summary="유효한 지하철 경로 후보를 확인하지 못했습니다.",
        selected_route=None,
        route_candidates=[],
        data_sources=deduped_sources,
        failed_sources=deduped_failed,
        limitations=merged_limitations,
        clarification_needed=False,
        available_partial_info=dedupe_strings(
            [
                *(line_mismatches or []),
                "경로를 확인하지 못해 역별 엘리베이터 정보는 조회하지 않았습니다.",
                # 호선 불일치 안내가 이미 어느 역이 문제인지 말하면 역 확인 문장은 덧붙이지 않는다.
                *(
                    []
                    if line_mismatches
                    else [
                        f"출발역 {station_label(origin)}과 도착역 "
                        f"{station_label(destination)}은 확인했습니다."
                    ]
                ),
            ]
        ),
        **evidence_context,
    )
    return _with_user_message(result)


def build_trip_result(
    *,
    origin: str,
    destination: str,
    mobility_profile: MobilityProfile,
    ranked_assessments: list[RouteCandidateAssessment],
) -> AccessibilityResult:
    selected = ranked_assessments[0]
    merged_limitations = list(selected.limitations)
    selected_route = selected.route
    compacted_facilities, facilities_trimmed = compact_accessible_facilities(
        selected.accessible_facilities,
        selected_route,
        mobility_profile,
    )
    if facilities_trimmed:
        merged_limitations = dedupe_strings(
            [*merged_limitations, REPRESENTATIVE_FACILITY_LIMITATION]
        )

    evidence_context = build_evidence_context(
        status=selected.status,
        risk_level=selected.risk_level,
        data_sources=selected.data_sources,
        failed_sources=selected.failed_sources,
        limitations=merged_limitations,
    )
    result = AccessibilityResult(
        status=selected.status,
        origin=origin,
        destination=destination,
        mobility_profile=mobility_profile,
        risk_level=selected.risk_level,
        risk_score=selected.risk_score,
        route_summary=_route_summary(selected_route, origin, destination),
        selected_route=selected_route,
        route_candidates=compact_route_candidates(
            [assessment.route for assessment in ranked_assessments],
            selected_route,
        ),
        risk_reasons=selected.risk_reasons,
        caution_points=selected.caution_points,
        blocked_facilities=selected.blocked_facilities,
        accessible_facilities=compacted_facilities,
        alternatives=_compact_alternatives(
            build_alternative_routes(ranked_assessments[1:])
        ),
        data_sources=list(selected.data_sources),
        failed_sources=list(selected.failed_sources),
        limitations=merged_limitations,
        accessibility_checks=selected.accessibility_checks,
        **evidence_context,
    )
    return _with_user_message(result)


def compact_accessible_facilities(
    facilities: list[AccessibleFacility],
    route: RouteCandidate | None,
    mobility_profile: MobilityProfile,
) -> tuple[list[AccessibleFacility], bool]:
    if not facilities:
        return [], False
    if route is None:
        return facilities[:3], len(facilities) > 3

    stations = route.stations or [route.origin, route.destination]
    compacted: list[AccessibleFacility] = []
    for station in stations:
        elevator = _first_facility_for_station(
            facilities,
            station,
            FacilityType.ELEVATOR,
            compacted,
        )
        if elevator is not None:
            compacted.append(elevator)

        if mobility_profile.need_accessible_restroom:
            restroom = _first_facility_for_station(
                facilities,
                station,
                FacilityType.ACCESSIBLE_RESTROOM,
                compacted,
            )
            if restroom is not None:
                compacted.append(restroom)

    if not compacted:
        return facilities[:3], len(facilities) > 3
    return compacted, len(compacted) < len(facilities)


def compact_route_candidates(
    routes: list[RouteCandidate],
    selected_route: RouteCandidate | None,
) -> list[RouteCandidate]:
    if selected_route is None:
        return routes[:3]

    compacted = [selected_route]
    for route in routes:
        if route.route_id == selected_route.route_id:
            continue
        compacted.append(route)
        if len(compacted) >= 3:
            break
    return compacted


def _first_facility_for_station(
    facilities: list[AccessibleFacility],
    station: str,
    facility_type: FacilityType,
    already_selected: list[AccessibleFacility],
) -> AccessibleFacility | None:
    selected_identities = {
        identity
        for facility in already_selected
        if (identity := facility_record_identity(facility)) is not None
    }
    station_name = normalize_station_name(station)
    for facility in facilities:
        if facility.facility_type != facility_type:
            continue
        if normalize_station_name(facility.station_name) != station_name:
            continue
        identity = facility_record_identity(facility)
        if identity is not None and identity in selected_identities:
            continue
        return facility
    return None


def _compact_alternatives(alternatives: list[AlternativeRoute]) -> list[AlternativeRoute]:
    return alternatives[:2]


def _station_clarification_summary(
    origin_context: StationLookupContext,
    destination_context: StationLookupContext,
) -> str:
    roles = [
        role
        for role, context in (("출발역", origin_context), ("도착역", destination_context))
        if context.needs_clarification
    ]
    subject = "과 ".join(roles) if roles else "출발역 또는 도착역"
    return f"{subject}을 확정하지 못해 아직 경로를 조회하지 않았습니다."


def _route_summary(route: RouteCandidate | None, origin: str, destination: str) -> str:
    if route is None:
        return f"{origin}에서 {destination}까지의 경로 후보를 확인하지 못했습니다."
    return (
        route.raw_summary
        or f"{origin}에서 {destination}까지 {transfer_text(route.transfer_count)} 경로입니다."
    )


def _with_user_message(result: AccessibilityResult) -> AccessibilityResult:
    return result.model_copy(update=build_user_message_context(result))
