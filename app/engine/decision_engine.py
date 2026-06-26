from __future__ import annotations

from dataclasses import dataclass, field

from app.engine.mobility_profile import requires_elevator
from app.engine.restroom_policy import evaluate_restroom_requirement
from app.engine.risk_rules import DEFAULT_RISK_RULES, RiskRuleSet
from app.engine.risk_scoring import calculate_risk_level, clamp_score, has_stale_data, total_score
from app.normalizers.helpers import normalize_station_name
from app.schemas.accessibility import AlternativeRoute, MobilityProfile, RiskLevel, RiskReason
from app.schemas.common import DataSourceMeta, FailedSource
from app.schemas.facility import AccessibleFacility, FacilityIssue, FacilityStatus, FacilityType
from app.schemas.route import RouteCandidate


@dataclass
class RouteEvaluation:
    route: RouteCandidate | None
    risk_score: int
    risk_level: RiskLevel
    risk_reasons: list[RiskReason] = field(default_factory=list)
    caution_points: list[str] = field(default_factory=list)
    blocked_facilities: list[FacilityIssue] = field(default_factory=list)
    accessible_facilities: list[AccessibleFacility] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


@dataclass
class DecisionResult:
    selected: RouteEvaluation
    alternatives: list[AlternativeRoute] = field(default_factory=list)


class AccessibilityDecisionEngine:
    def __init__(self, rules: RiskRuleSet | None = None) -> None:
        self.rules = rules or DEFAULT_RISK_RULES

    def evaluate_routes(
        self,
        *,
        routes: list[RouteCandidate],
        mobility_profile: MobilityProfile,
        facilities_by_station: dict[str, list[AccessibleFacility]],
        elevator_status_by_station: dict[str, list[AccessibleFacility]],
        restroom_by_station: dict[str, list[AccessibleFacility]],
        failed_sources: list[FailedSource],
        data_sources: list[DataSourceMeta],
    ) -> DecisionResult:
        if not routes:
            evaluation = self._empty_route_evaluation(failed_sources)
            return DecisionResult(selected=evaluation)

        evaluations = [
            self.evaluate_route(
                route=route,
                mobility_profile=mobility_profile,
                facilities_by_station=facilities_by_station,
                elevator_status_by_station=elevator_status_by_station,
                restroom_by_station=restroom_by_station,
                failed_sources=failed_sources,
                data_sources=data_sources,
            )
            for route in routes
        ]
        selected = sorted(
            evaluations,
            key=lambda item: (item.risk_score, item.route.estimated_minutes or 9999),
        )[0]
        alternatives = [
            AlternativeRoute(
                title=f"대안 경로 {index}",
                description=(
                    evaluation.route.raw_summary
                    or (
                        f"{evaluation.route.origin}에서 "
                        f"{evaluation.route.destination}까지의 대안 경로입니다."
                    )
                ),
                route=evaluation.route,
                expected_risk_level=evaluation.risk_level,
            )
            for index, evaluation in enumerate(evaluations, start=1)
            if evaluation.route != selected.route
        ]
        return DecisionResult(selected=selected, alternatives=alternatives)

    def evaluate_route(
        self,
        *,
        route: RouteCandidate,
        mobility_profile: MobilityProfile,
        facilities_by_station: dict[str, list[AccessibleFacility]],
        elevator_status_by_station: dict[str, list[AccessibleFacility]],
        restroom_by_station: dict[str, list[AccessibleFacility]],
        failed_sources: list[FailedSource],
        data_sources: list[DataSourceMeta],
    ) -> RouteEvaluation:
        reasons: list[RiskReason] = []
        blocked: list[FacilityIssue] = []
        accessible: list[AccessibleFacility] = []
        limitations: list[str] = []

        elevator_check_stations = _elevator_check_stations(route)
        if requires_elevator(mobility_profile):
            for station in elevator_check_stations:
                station_facilities = _facilities_for_station(facilities_by_station, station)
                station_elevator_status = _facilities_for_station(
                    elevator_status_by_station,
                    station,
                )
                elevators = [
                    facility
                    for facility in [
                        *station_facilities,
                        *station_elevator_status,
                    ]
                    if facility.facility_type == FacilityType.ELEVATOR
                ]
                available = [item for item in elevators if item.status == FacilityStatus.AVAILABLE]
                unavailable = [
                    item
                    for item in elevators
                    if item.status in {FacilityStatus.UNAVAILABLE, FacilityStatus.MAINTENANCE}
                ]
                unknown = [item for item in elevators if item.status == FacilityStatus.UNKNOWN]

                if available:
                    accessible.extend(available)
                    continue
                if unavailable:
                    reasons.append(self.rules.reason("elevator_unavailable", station_name=station))
                    blocked.extend(
                        FacilityIssue(
                            station_name=item.station_name,
                            line=item.line,
                            facility_type=item.facility_type,
                            status=item.status,
                            severity="HIGH",
                            reason="필수 엘리베이터가 이용불가 또는 점검 상태입니다.",
                        )
                        for item in unavailable
                    )
                    continue
                if unknown:
                    reasons.append(self.rules.reason("elevator_unknown", station_name=station))
                elif not elevators:
                    reasons.append(self.rules.reason("elevator_not_found", station_name=station))

                escalators = [
                    facility
                    for facility in station_facilities
                    if facility.facility_type == FacilityType.ESCALATOR
                    and facility.status == FacilityStatus.AVAILABLE
                ]
                if mobility_profile.wheelchair and escalators:
                    reasons.append(
                        self.rules.reason("escalator_only_for_wheelchair", station_name=station)
                    )

        if route.transfer_count > 0:
            reasons.append(self.rules.reason("transfer_required"))
        if mobility_profile.max_transfer_count is not None:
            if route.transfer_count > mobility_profile.max_transfer_count:
                reasons.append(self.rules.reason("too_many_transfers"))
        elif mobility_profile.avoid_many_transfers and route.transfer_count > 1:
            reasons.append(self.rules.reason("too_many_transfers"))

        if mobility_profile.need_accessible_restroom:
            restroom_evaluation = evaluate_restroom_requirement(
                route=route,
                mobility_profile=mobility_profile,
                restroom_by_station=restroom_by_station,
            )
            accessible.extend(restroom_evaluation.confirmed_facilities)
            if not restroom_evaluation.satisfied:
                if restroom_evaluation.missing_required_stations:
                    reasons.extend(
                        _station_restroom_reason(
                            self.rules,
                            station_name,
                            index,
                        )
                        for index, station_name in enumerate(
                            restroom_evaluation.missing_required_stations
                        )
                    )
                else:
                    reasons.append(self.rules.reason("no_accessible_restroom_when_required"))

        if failed_sources:
            reasons.append(self.rules.reason("api_failure"))
            limitations.append("일부 공공 API 조회에 실패해 접근성 판단에 한계가 있습니다.")

        if has_stale_data(data_sources):
            reasons.append(self.rules.reason("stale_data"))
            limitations.append("일부 데이터가 캐시된 이전 응답입니다.")

        deduped_reasons = _dedupe_reasons(reasons)
        risk_score = total_score(deduped_reasons)
        risk_level = calculate_risk_level(risk_score, failed_sources=failed_sources)
        return RouteEvaluation(
            route=route,
            risk_score=risk_score,
            risk_level=risk_level,
            risk_reasons=deduped_reasons,
            caution_points=[reason.message for reason in deduped_reasons],
            blocked_facilities=blocked,
            accessible_facilities=_dedupe_facilities(accessible),
            limitations=limitations,
        )

    def _empty_route_evaluation(self, failed_sources: list[FailedSource]) -> RouteEvaluation:
        reasons = [self.rules.reason("api_failure")] if failed_sources else []
        score = clamp_score(sum(reason.score for reason in reasons))
        return RouteEvaluation(
            route=None,
            risk_score=score,
            risk_level=calculate_risk_level(score, failed_sources=failed_sources),
            risk_reasons=reasons,
            caution_points=[reason.message for reason in reasons],
            limitations=["경로 후보를 확인하지 못했습니다."],
        )


def _dedupe_reasons(reasons: list[RiskReason]) -> list[RiskReason]:
    seen: set[tuple[str, str | None]] = set()
    deduped: list[RiskReason] = []
    for reason in reasons:
        identity = (reason.code, reason.station_name)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(reason)
    return deduped


def _station_restroom_reason(
    rules: RiskRuleSet,
    station_name: str,
    index: int,
) -> RiskReason:
    reason = rules.reason("no_accessible_restroom_when_required", station_name=station_name)
    if index == 0:
        return reason
    return reason.model_copy(update={"score": 0})


def _facilities_for_station(
    facilities_by_station: dict[str, list[AccessibleFacility]],
    station: str,
) -> list[AccessibleFacility]:
    exact = facilities_by_station.get(station)
    if exact:
        return exact

    normalized = normalize_station_name(station)
    matched: list[AccessibleFacility] = []
    for candidate_station, facilities in facilities_by_station.items():
        if normalize_station_name(candidate_station) == normalized:
            matched.extend(facilities)
    return matched


def _dedupe_facilities(facilities: list[AccessibleFacility]) -> list[AccessibleFacility]:
    seen: set[tuple[str | None, str, FacilityType]] = set()
    deduped: list[AccessibleFacility] = []
    for facility in facilities:
        identity = (facility.facility_id, facility.station_name, facility.facility_type)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(facility)
    return deduped


def _elevator_check_stations(route: RouteCandidate) -> list[str]:
    stations: list[str] = [route.origin, route.destination]

    previous_line: str | None = None
    for segment in route.segments:
        current_line = segment.line.strip() if segment.line else None
        if segment.transfer:
            stations.extend([segment.from_station, segment.to_station])
        if previous_line and current_line and previous_line != current_line:
            stations.append(segment.from_station)
        if current_line:
            previous_line = current_line

    return _ordered_route_stations(_dedupe_station_names(stations), route)


def _ordered_route_stations(station_names: list[str], route: RouteCandidate) -> list[str]:
    if not route.stations:
        return station_names
    route_order = {
        normalize_station_name(station_name): index
        for index, station_name in enumerate(route.stations)
    }
    return sorted(
        station_names,
        key=lambda station_name: route_order.get(normalize_station_name(station_name), 10_000),
    )


def _dedupe_station_names(station_names: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for station_name in station_names:
        normalized = normalize_station_name(station_name)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(station_name)
    return deduped
