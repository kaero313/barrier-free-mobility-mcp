from __future__ import annotations

from app.cache.base import CacheProtocol
from app.cache.factory import build_cache
from app.core.config import Settings, get_settings
from app.engine.decision_engine import AccessibilityDecisionEngine
from app.engine.restroom_policy import (
    evaluate_restroom_requirement,
    is_restroom_required_for_station,
)
from app.engine.risk_alignment import align_risk_with_user_judgement
from app.normalizers.helpers import normalize_station_name
from app.schemas.accessibility import (
    AccessibilityCheck,
    AccessibilityResult,
    AlternativeRoute,
    MobilityProfile,
    RiskReason,
)
from app.schemas.common import DataSourceMeta, FailedSource, ResponseStatus
from app.schemas.facility import AccessibleFacility, FacilityIssue, FacilityStatus, FacilityType
from app.schemas.route import RouteCandidate
from app.services.evidence import build_evidence_context
from app.services.facility_service import FacilityService
from app.services.route_service import RouteService
from app.services.station_context import (
    StationLookupContext,
    build_route_station_contexts,
    resolve_station_context,
    route_line_mismatch_limitations,
)
from app.services.station_service import StationService
from app.services.types import ServiceResult
from app.services.user_message import build_user_message_context

REPRESENTATIVE_FACILITY_LIMITATION = (
    "대표 접근성 시설만 포함했습니다. 전체 시설 목록은 개별 시설 조회 도구로 확인하세요."
)


class AccessibilityService:
    def __init__(
        self,
        settings: Settings | None = None,
        cache: CacheProtocol | None = None,
        station_service: StationService | None = None,
        route_service: RouteService | None = None,
        facility_service: FacilityService | None = None,
        decision_engine: AccessibilityDecisionEngine | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache or build_cache(self.settings)
        self.station_service = station_service or StationService()
        self.route_service = route_service or RouteService(self.settings, self.cache)
        self.facility_service = facility_service or FacilityService(
            self.settings,
            self.cache,
            self.station_service,
        )
        self.decision_engine = decision_engine or AccessibilityDecisionEngine()

    async def check_accessible_trip(
        self,
        origin: str,
        destination: str,
        mobility_profile: MobilityProfile,
    ) -> AccessibilityResult:
        origin_context = resolve_station_context(self.station_service, origin)
        destination_context = resolve_station_context(self.station_service, destination)
        if origin_context.needs_clarification or destination_context.needs_clarification:
            failed = [
                FailedSource(source_name="station_resolution", reason="needs_clarification")
            ]
            limitations = ["역명을 확정할 수 없어 경로 접근성 판단을 수행하지 못했습니다."]
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
                route_summary="출발역 또는 도착역을 확정하지 못했습니다.",
                failed_sources=failed,
                limitations=limitations,
                clarification_needed=True,
                questions=[
                    "출발역과 도착역을 지하철역 이름 기준으로 다시 확인해 주세요.",
                    "휠체어, 유모차, 보행약자 중 어떤 이동 조건인지 알려 주세요.",
                ],
                available_partial_info=[
                    "역명이 확정되면 엘리베이터 위치와 운행 상태를 확인할 수 있습니다.",
                    "출발역, 환승역, 도착역 기준 접근성 체크를 제공할 수 있습니다.",
                ],
                **evidence_context,
            )
            return result.model_copy(update=build_user_message_context(result))

        normalized_origin = origin_context.station_name
        normalized_destination = destination_context.station_name

        route_result = await self.route_service.get_route_candidates(
            normalized_origin,
            normalized_destination,
        )
        data_sources = list(route_result.data_sources)
        failed_sources = list(route_result.failed_sources)
        limitations = list(route_result.limitations)

        route_candidates = route_result.value
        route_station_contexts = build_route_station_contexts(
            station_service=self.station_service,
            routes=route_candidates,
            origin=origin_context,
            destination=destination_context,
        )
        limitations.extend(
            route_line_mismatch_limitations(
                route_candidates,
                origin_context,
                destination_context,
            )
        )
        stations = _stations_from_routes(route_candidates)
        facilities_by_station: dict[str, list[AccessibleFacility]] = {}
        elevator_status_by_station: dict[str, list[AccessibleFacility]] = {}
        restroom_by_station: dict[str, list[AccessibleFacility]] = {}

        for station in stations:
            station_context = _context_for_station(station, route_station_contexts)
            facility_result = await self.facility_service.get_station_facilities(
                station_context.station_name,
                line=station_context.line,
            )
            _merge_service_metadata(facility_result, data_sources, failed_sources, limitations)
            facilities_by_station[station] = facility_result.value

            elevator_result = await self.facility_service.get_elevator_status(
                station_context.station_name,
                line=station_context.line,
            )
            _merge_service_metadata(elevator_result, data_sources, failed_sources, limitations)
            elevator_status_by_station[station] = elevator_result.value

            if mobility_profile.need_accessible_restroom:
                restroom_result = await self.facility_service.get_accessible_restroom(
                    station_context.station_name,
                    line=station_context.line,
                )
                _merge_service_metadata(restroom_result, data_sources, failed_sources, limitations)
                restroom_by_station[station] = restroom_result.value

        decision = self.decision_engine.evaluate_routes(
            routes=route_candidates,
            mobility_profile=mobility_profile,
            facilities_by_station=facilities_by_station,
            elevator_status_by_station=elevator_status_by_station,
            restroom_by_station=restroom_by_station,
            failed_sources=_dedupe_failed_sources(failed_sources),
            data_sources=data_sources,
        )
        selected = decision.selected
        merged_limitations = _dedupe_strings([*limitations, *selected.limitations])
        deduped_failed = _dedupe_failed_sources(failed_sources)
        status = ResponseStatus.PARTIAL if deduped_failed else ResponseStatus.SUCCESS

        selected_route = selected.route
        compacted_facilities, facilities_trimmed = _compact_accessible_facilities(
            selected.accessible_facilities,
            selected_route,
            mobility_profile,
        )
        if facilities_trimmed:
            merged_limitations = _dedupe_strings(
                [*merged_limitations, REPRESENTATIVE_FACILITY_LIMITATION]
            )
        deduped_data_sources = _dedupe_data_sources(data_sources)
        accessibility_checks = _build_accessibility_checks(
            route=selected_route,
            accessible_facilities=compacted_facilities,
            restroom_by_station=restroom_by_station,
            blocked_facilities=selected.blocked_facilities,
            risk_reasons=selected.risk_reasons,
            mobility_profile=mobility_profile,
            station_contexts=route_station_contexts,
        )
        aligned_risk = align_risk_with_user_judgement(
            risk_score=selected.risk_score,
            risk_level=selected.risk_level,
            risk_reasons=selected.risk_reasons,
            failed_sources=deduped_failed,
            accessibility_checks=accessibility_checks,
            mobility_profile=mobility_profile,
            status=status,
        )
        evidence_context = build_evidence_context(
            status=status,
            risk_level=aligned_risk.risk_level,
            data_sources=deduped_data_sources,
            failed_sources=deduped_failed,
            limitations=merged_limitations,
        )

        result = AccessibilityResult(
            status=status,
            origin=normalized_origin,
            destination=normalized_destination,
            mobility_profile=mobility_profile,
            risk_level=aligned_risk.risk_level,
            risk_score=aligned_risk.risk_score,
            route_summary=_route_summary(selected_route, normalized_origin, normalized_destination),
            selected_route=selected_route,
            route_candidates=_compact_route_candidates(route_candidates, selected_route),
            risk_reasons=selected.risk_reasons,
            caution_points=selected.caution_points,
            blocked_facilities=selected.blocked_facilities,
            accessible_facilities=compacted_facilities,
            alternatives=_compact_alternatives(decision.alternatives),
            data_sources=deduped_data_sources,
            failed_sources=deduped_failed,
            limitations=merged_limitations,
            accessibility_checks=accessibility_checks,
            **evidence_context,
        )
        return result.model_copy(update=build_user_message_context(result))

    async def generate_accessibility_brief(
        self,
        origin: str,
        destination: str,
        mobility_profile: MobilityProfile,
    ) -> AccessibilityResult:
        return await self.check_accessible_trip(origin, destination, mobility_profile)


def _stations_from_routes(routes: list[RouteCandidate]) -> list[str]:
    stations: list[str] = []
    for route in routes:
        route_stations = route.stations or [route.origin, route.destination]
        for station in route_stations:
            if station not in stations:
                stations.append(station)
    return stations


def _context_for_station(
    station: str,
    station_contexts: dict[str, StationLookupContext],
) -> StationLookupContext:
    key = normalize_station_name(station)
    if key and key in station_contexts:
        return station_contexts[key]
    return StationLookupContext(station_name=station)


def _merge_service_metadata(
    result: ServiceResult[list[AccessibleFacility]],
    data_sources: list[DataSourceMeta],
    failed_sources: list[FailedSource],
    limitations: list[str],
) -> None:
    data_sources.extend(result.data_sources)
    failed_sources.extend(result.failed_sources)
    limitations.extend(result.limitations)


def _dedupe_failed_sources(failed_sources: list[FailedSource]) -> list[FailedSource]:
    seen: set[tuple[str, str]] = set()
    deduped: list[FailedSource] = []
    for source in failed_sources:
        identity = (source.source_name, source.reason)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(source)
    return deduped


def _dedupe_data_sources(data_sources: list[DataSourceMeta]) -> list[DataSourceMeta]:
    seen: set[tuple[str, str, str, bool, str | None]] = set()
    deduped: list[DataSourceMeta] = []
    for source in data_sources:
        identity = (
            source.source_name,
            str(source.source_type),
            str(source.cache_status),
            source.success,
            source.error_message,
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(source)
    return deduped


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _compact_accessible_facilities(
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


def _first_facility_for_station(
    facilities: list[AccessibleFacility],
    station: str,
    facility_type: FacilityType,
    already_selected: list[AccessibleFacility],
) -> AccessibleFacility | None:
    selected_identities = {_facility_identity(facility) for facility in already_selected}
    station_name = normalize_station_name(station)
    for facility in facilities:
        if facility.facility_type != facility_type:
            continue
        if normalize_station_name(facility.station_name) != station_name:
            continue
        if _facility_identity(facility) in selected_identities:
            continue
        return facility
    return None


def _facility_identity(facility: AccessibleFacility) -> tuple[str | None, str | None, FacilityType]:
    return (
        facility.facility_id,
        normalize_station_name(facility.station_name),
        facility.facility_type,
    )


def _compact_route_candidates(
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


def _compact_alternatives(alternatives: list[AlternativeRoute]) -> list[AlternativeRoute]:
    return alternatives[:2]


def _route_summary(route: RouteCandidate | None, origin: str, destination: str) -> str:
    if route is None:
        return f"{origin}에서 {destination}까지의 경로 후보를 확인하지 못했습니다."
    return (
        route.raw_summary
        or f"{origin}에서 {destination}까지 {route.transfer_count}회 환승 경로입니다."
    )


def _build_accessibility_checks(
    *,
    route: RouteCandidate | None,
    accessible_facilities: list[AccessibleFacility],
    restroom_by_station: dict[str, list[AccessibleFacility]],
    blocked_facilities: list[FacilityIssue],
    risk_reasons: list[RiskReason],
    mobility_profile: MobilityProfile,
    station_contexts: dict[str, StationLookupContext],
) -> list[AccessibilityCheck]:
    if route is None:
        return []

    restroom_evaluation = evaluate_restroom_requirement(
        route=route,
        mobility_profile=mobility_profile,
        restroom_by_station=restroom_by_station,
    )
    checks: list[AccessibilityCheck] = []
    for station_name, role in _accessibility_check_station_roles(route):
        station_context = _context_for_station(station_name, station_contexts)
        elevator = _first_matching_facility(
            accessible_facilities,
            station_name,
            FacilityType.ELEVATOR,
        )
        blocked = _first_matching_issue(blocked_facilities, station_name, FacilityType.ELEVATOR)
        station_risk_reasons = [
            reason
            for reason in risk_reasons
            if reason.station_name
            and normalize_station_name(reason.station_name) == normalize_station_name(station_name)
        ]
        restroom = _first_matching_available_restroom(restroom_by_station, station_name)
        restroom_required = is_restroom_required_for_station(restroom_evaluation, station_name)

        elevator_status = FacilityStatus.UNKNOWN
        elevator_location: str | None = None
        notes: list[str] = []
        if elevator is not None:
            elevator_status = elevator.status
            elevator_location = elevator.location_description
        if blocked is not None:
            elevator_status = blocked.status
            notes.append(blocked.reason)
        for reason in station_risk_reasons:
            if reason.code == "elevator_not_found":
                notes.append("엘리베이터 정보를 찾지 못했습니다.")
            elif reason.code == "elevator_unknown":
                notes.append("엘리베이터 상태를 확인하지 못했습니다.")

        if role == "transfer":
            notes.append("환승역입니다. 엘리베이터 환승 동선을 확인하세요.")

        checks.append(
            AccessibilityCheck(
                station=station_name,
                line=station_context.line,
                station_id=station_context.station_id,
                role=role,
                elevator_status=elevator_status,
                elevator_location=elevator_location,
                restroom_available=(
                    restroom is not None if mobility_profile.need_accessible_restroom else None
                ),
                restroom_required=restroom_required,
                notes=_dedupe_strings(notes),
            )
        )
    return checks


def _accessibility_check_station_roles(
    route: RouteCandidate,
) -> list[tuple[str, str]]:
    roles: dict[str, tuple[str, str]] = {}

    def add(station_name: str, role: str) -> None:
        key = normalize_station_name(station_name)
        if key in roles:
            if roles[key][1] == "transfer" or role != "transfer":
                return
            roles[key] = (station_name, role)
            return
        roles[key] = (station_name, role)

    add(route.origin, "origin")
    add(route.destination, "destination")

    previous_line: str | None = None
    for segment in route.segments:
        current_line = segment.line.strip() if segment.line else None
        if segment.transfer:
            add(segment.from_station, "transfer")
            add(segment.to_station, "transfer")
        if previous_line and current_line and previous_line != current_line:
            add(segment.from_station, "transfer")
        if current_line:
            previous_line = current_line

    if not route.stations:
        return list(roles.values())

    route_order = {
        normalize_station_name(station_name): index
        for index, station_name in enumerate(route.stations)
    }
    return sorted(
        roles.values(),
        key=lambda item: route_order.get(normalize_station_name(item[0]), 10_000),
    )


def _first_matching_facility(
    facilities: list[AccessibleFacility],
    station_name: str,
    facility_type: FacilityType,
) -> AccessibleFacility | None:
    normalized = normalize_station_name(station_name)
    for facility in facilities:
        if facility.facility_type != facility_type:
            continue
        if normalize_station_name(facility.station_name) == normalized:
            return facility
    return None


def _first_matching_issue(
    issues: list[FacilityIssue],
    station_name: str,
    facility_type: FacilityType,
) -> FacilityIssue | None:
    normalized = normalize_station_name(station_name)
    for issue in issues:
        if issue.facility_type != facility_type:
            continue
        if normalize_station_name(issue.station_name) == normalized:
            return issue
    return None


def _first_matching_available_restroom(
    restroom_by_station: dict[str, list[AccessibleFacility]],
    station_name: str,
) -> AccessibleFacility | None:
    normalized = normalize_station_name(station_name)
    for candidate_station, facilities in restroom_by_station.items():
        if normalize_station_name(candidate_station) != normalized:
            continue
        for facility in facilities:
            if (
                facility.facility_type == FacilityType.ACCESSIBLE_RESTROOM
                and facility.status == FacilityStatus.AVAILABLE
            ):
                return facility
    return None
