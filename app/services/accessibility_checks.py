from __future__ import annotations

from app.engine.elevator_path_evidence import evaluate_elevator_path_evidence
from app.engine.elevator_status import (
    align_elevator_answer_state_with_sources,
    summarize_elevator_status,
)
from app.engine.restroom_policy import (
    evaluate_restroom_requirement,
    is_restroom_required_for_station,
)
from app.normalizers.facility_identity import facility_record_identity
from app.normalizers.helpers import normalize_line_name, normalize_station_name
from app.schemas.accessibility import (
    AccessibilityCheck,
    AccessibilityEvidenceStatus,
    FacilityAnswerState,
    MobilityProfile,
    RiskReason,
)
from app.schemas.common import DataSourceMeta, SourceCoverageStatus
from app.schemas.facility import (
    AccessibleFacility,
    FacilityIssue,
    FacilityStatus,
    FacilityType,
)
from app.schemas.route import RouteCandidate
from app.services.elevator_evidence import build_elevator_evidence_items
from app.services.station_context import StationLookupContext, context_for_station


def build_accessibility_checks(
    *,
    route: RouteCandidate | None,
    accessible_facilities: list[AccessibleFacility],
    facilities_by_station: dict[str, list[AccessibleFacility]],
    elevator_status_by_station: dict[str, list[AccessibleFacility]],
    restroom_by_station: dict[str, list[AccessibleFacility]],
    blocked_facilities: list[FacilityIssue],
    risk_reasons: list[RiskReason],
    mobility_profile: MobilityProfile,
    station_contexts: dict[str, StationLookupContext],
    source_coverage_by_station: dict[str, list[DataSourceMeta]],
) -> list[AccessibilityCheck]:
    if route is None:
        return []

    restroom_evaluation = evaluate_restroom_requirement(
        route=route,
        mobility_profile=mobility_profile,
        restroom_by_station=restroom_by_station,
    )
    checks: list[AccessibilityCheck] = []
    for station_name, role in accessibility_check_station_roles(route):
        station_context = context_for_station(station_name, station_contexts)
        elevator = _first_matching_facility(
            accessible_facilities,
            station_name,
            FacilityType.ELEVATOR,
        )
        station_elevators = _matching_elevators(
            station_name,
            facilities_by_station,
            elevator_status_by_station,
        )
        blocked = _first_matching_issue(
            blocked_facilities,
            station_name,
            FacilityType.ELEVATOR,
        )
        station_risk_reasons = [
            reason
            for reason in risk_reasons
            if reason.station_name
            and normalize_station_name(reason.station_name)
            == normalize_station_name(station_name)
        ]
        restroom = _first_matching_available_restroom(
            restroom_by_station,
            station_name,
        )
        restroom_required = is_restroom_required_for_station(
            restroom_evaluation,
            station_name,
        )

        status_summary = summarize_elevator_status(station_elevators)
        elevator_answer_state = align_elevator_answer_state_with_sources(
            status_summary.answer_state,
            station_source_metadata(source_coverage_by_station, station_name),
        )
        elevator_details = build_elevator_evidence_items(station_elevators)
        elevator_status = status_summary.representative_status
        elevator_location: str | None = None
        notes: list[str] = []
        if elevator is not None:
            elevator_location = elevator.location_description
        elif status_summary.available:
            elevator_location = status_summary.available[0].location_description
        elif status_summary.operational_facilities:
            elevator_location = (
                status_summary.operational_facilities[0].location_description
            )
        elif status_summary.facilities:
            elevator_location = status_summary.facilities[0].location_description

        if elevator_answer_state == FacilityAnswerState.MIXED:
            notes.append(
                "정상 운행과 점검 또는 이용불가 상태의 엘리베이터가 함께 있습니다."
            )
        elif (
            elevator_answer_state == FacilityAnswerState.UNKNOWN
            and status_summary.answer_state == FacilityAnswerState.NOT_FOUND
        ):
            notes.append(
                "엘리베이터 정보 조회가 완료되지 않아 시설 유무를 확인하지 못했습니다."
            )
        elif blocked is not None:
            notes.append(blocked.reason)

        notes.extend(_risk_reason_notes(station_risk_reasons))
        if station_sources_are_unsupported(
            source_coverage_by_station,
            station_name,
            {"restroom"},
        ):
            notes.append(
                "장애인화장실 정보는 현재 연결된 공공데이터 제공 범위 밖입니다."
            )
        if role == "transfer":
            notes.append("환승역입니다. 엘리베이터 환승 동선을 확인하세요.")

        evidence = _elevator_evidence(
            station_context=station_context,
            role=role,
            station_elevators=station_elevators,
            blocked=blocked,
            elevator_status=elevator_status,
            elevator_answer_state=elevator_answer_state,
            mobility_profile=mobility_profile,
        )
        checks.append(
            AccessibilityCheck(
                station=station_name,
                line=station_context.line,
                station_id=station_context.station_id,
                operator=station_context.operator,
                role=role,
                elevator_status=elevator_status,
                elevator_answer_state=elevator_answer_state,
                elevator_location=elevator_location,
                elevator_details=elevator_details,
                station_has_elevator=evidence["station_has_elevator"],
                line_matched_elevator=evidence["line_matched_elevator"],
                platform_to_concourse_verified=evidence[
                    "platform_to_concourse_verified"
                ],
                transfer_path_elevator_verified=evidence[
                    "transfer_path_elevator_verified"
                ],
                exit_elevator_verified=evidence["exit_elevator_verified"],
                status_verified=evidence["status_verified"],
                restroom_available=(
                    restroom is not None
                    if mobility_profile.need_accessible_restroom
                    else None
                ),
                restroom_required=restroom_required,
                notes=_dedupe_strings(notes),
            )
        )
    return checks


def accessibility_check_station_roles(
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


def station_sources_are_unsupported(
    source_coverage_by_station: dict[str, list[DataSourceMeta]],
    station_name: str,
    source_names: set[str],
) -> bool:
    relevant = [
        source
        for source in station_source_metadata(
            source_coverage_by_station,
            station_name,
        )
        if source.source_name in source_names
    ]
    return bool(relevant) and all(
        source.coverage_status == SourceCoverageStatus.UNSUPPORTED
        for source in relevant
    )


def station_source_metadata(
    sources_by_station: dict[str, list[DataSourceMeta]],
    station_name: str,
) -> list[DataSourceMeta]:
    normalized_station = normalize_station_name(station_name)
    return [
        source
        for candidate_station, sources in sources_by_station.items()
        if normalize_station_name(candidate_station) == normalized_station
        for source in sources
    ]


def line_match_evidence(
    station_context: StationLookupContext,
    station_elevators: list[AccessibleFacility],
    station_has: AccessibilityEvidenceStatus,
) -> AccessibilityEvidenceStatus:
    if station_has == AccessibilityEvidenceStatus.FAILED:
        return AccessibilityEvidenceStatus.FAILED
    if not station_elevators or not station_context.line:
        return AccessibilityEvidenceStatus.UNVERIFIED

    elevator_lines = {
        normalized_line
        for facility in station_elevators
        if (normalized_line := normalize_line_name(facility.line)) is not None
    }
    expected_line = normalize_line_name(station_context.line)
    if expected_line in elevator_lines:
        return AccessibilityEvidenceStatus.CONFIRMED
    if elevator_lines:
        return AccessibilityEvidenceStatus.FAILED
    return AccessibilityEvidenceStatus.UNVERIFIED


def _matching_elevators(
    station_name: str,
    facilities_by_station: dict[str, list[AccessibleFacility]],
    elevator_status_by_station: dict[str, list[AccessibleFacility]],
) -> list[AccessibleFacility]:
    normalized = normalize_station_name(station_name)
    elevators: list[AccessibleFacility] = []
    for source in (facilities_by_station, elevator_status_by_station):
        for candidate_station, facilities in source.items():
            if normalize_station_name(candidate_station) != normalized:
                continue
            elevators.extend(
                facility
                for facility in facilities
                if facility.facility_type == FacilityType.ELEVATOR
            )
    return _dedupe_facilities_for_check(elevators)


def _risk_reason_notes(reasons: list[RiskReason]) -> list[str]:
    notes: list[str] = []
    for reason in reasons:
        if reason.code == "elevator_not_found":
            notes.append("엘리베이터 정보를 찾지 못했습니다.")
        elif reason.code == "elevator_source_unsupported":
            notes.append(
                "엘리베이터 정보는 현재 연결된 공공데이터 제공 범위 밖입니다."
            )
        elif reason.code == "elevator_unknown":
            notes.append("엘리베이터 상태를 확인하지 못했습니다.")
    return notes


def _elevator_evidence(
    *,
    station_context: StationLookupContext,
    role: str,
    station_elevators: list[AccessibleFacility],
    blocked: FacilityIssue | None,
    elevator_status: FacilityStatus,
    elevator_answer_state: FacilityAnswerState,
    mobility_profile: MobilityProfile,
) -> dict[str, AccessibilityEvidenceStatus]:
    required = _requires_elevator_for_check(mobility_profile)
    has_elevator = bool(station_elevators) or blocked is not None

    if has_elevator:
        station_has = AccessibilityEvidenceStatus.CONFIRMED
    elif elevator_answer_state == FacilityAnswerState.NOT_FOUND:
        station_has = AccessibilityEvidenceStatus.FAILED
    else:
        station_has = AccessibilityEvidenceStatus.UNVERIFIED

    path_evidence = evaluate_elevator_path_evidence(
        required=required,
        role=role,
        station_has_elevator=station_has,
        facilities=station_elevators,
    )
    return {
        "station_has_elevator": station_has,
        "line_matched_elevator": line_match_evidence(
            station_context,
            station_elevators,
            station_has,
        ),
        "platform_to_concourse_verified": path_evidence.platform_to_concourse,
        "transfer_path_elevator_verified": path_evidence.transfer_path,
        "exit_elevator_verified": path_evidence.exit_path,
        "status_verified": _status_evidence(
            station_has,
            elevator_status,
            elevator_answer_state,
            blocked,
        ),
    }


def _status_evidence(
    station_has: AccessibilityEvidenceStatus,
    elevator_status: FacilityStatus,
    elevator_answer_state: FacilityAnswerState,
    blocked: FacilityIssue | None,
) -> AccessibilityEvidenceStatus:
    if station_has == AccessibilityEvidenceStatus.FAILED:
        return AccessibilityEvidenceStatus.FAILED
    if blocked is not None or elevator_answer_state == FacilityAnswerState.MIXED:
        return AccessibilityEvidenceStatus.CONFIRMED
    if elevator_status in {
        FacilityStatus.AVAILABLE,
        FacilityStatus.MAINTENANCE,
        FacilityStatus.UNAVAILABLE,
    }:
        return AccessibilityEvidenceStatus.CONFIRMED
    return AccessibilityEvidenceStatus.UNVERIFIED


def _requires_elevator_for_check(mobility_profile: MobilityProfile) -> bool:
    return (
        mobility_profile.wheelchair
        or mobility_profile.stroller
        or mobility_profile.cane_or_walker
        or not mobility_profile.can_use_stairs
        or not mobility_profile.can_use_escalator
        or mobility_profile.need_elevator_only
    )


def _dedupe_facilities_for_check(
    facilities: list[AccessibleFacility],
) -> list[AccessibleFacility]:
    seen: set[tuple[str, ...]] = set()
    deduped: list[AccessibleFacility] = []
    for facility in facilities:
        identity = facility_record_identity(facility)
        if identity is not None and identity in seen:
            continue
        if identity is not None:
            seen.add(identity)
        deduped.append(facility)
    return deduped


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


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
