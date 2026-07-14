from __future__ import annotations

from app.engine.decision_engine import AccessibilityDecisionEngine
from app.engine.risk_alignment import align_risk_with_user_judgement
from app.engine.route_ranking import RouteCandidateAssessment
from app.normalizers.helpers import normalize_station_name
from app.schemas.accessibility import MobilityProfile, RiskReason
from app.schemas.common import (
    DataSourceMeta,
    FailedSource,
    ResponseStatus,
    SourceCoverageStatus,
)
from app.schemas.facility import AccessibleFacility
from app.schemas.route import RouteCandidate
from app.services.accessibility_checks import (
    accessibility_check_station_roles,
    build_accessibility_checks,
    station_sources_are_unsupported,
)
from app.services.result_metadata import (
    dedupe_data_sources,
    dedupe_failed_sources,
    dedupe_strings,
)
from app.services.station_context import (
    StationLookupContext,
    route_line_mismatch_limitations,
)


def assess_route_candidate(
    *,
    decision_engine: AccessibilityDecisionEngine,
    route: RouteCandidate,
    mobility_profile: MobilityProfile,
    origin_context: StationLookupContext,
    destination_context: StationLookupContext,
    route_data_sources: list[DataSourceMeta],
    route_failed_sources: list[FailedSource],
    route_limitations: list[str],
    data_sources_by_station: dict[str, list[DataSourceMeta]],
    failed_sources_by_station: dict[str, list[FailedSource]],
    limitations_by_station: dict[str, list[str]],
    facilities_by_station: dict[str, list[AccessibleFacility]],
    elevator_status_by_station: dict[str, list[AccessibleFacility]],
    restroom_by_station: dict[str, list[AccessibleFacility]],
    station_contexts: dict[str, StationLookupContext],
) -> RouteCandidateAssessment:
    candidate_data_sources = dedupe_data_sources(
        [
            *route_data_sources,
            *_metadata_for_route(route, data_sources_by_station),
        ]
    )
    candidate_failed_sources = dedupe_failed_sources(
        [
            *route_failed_sources,
            *_metadata_for_route(route, failed_sources_by_station),
        ]
    )
    candidate_limitations = dedupe_strings(
        [
            *route_limitations,
            *_metadata_for_route(route, limitations_by_station),
            *route_line_mismatch_limitations(
                [route],
                origin_context,
                destination_context,
            ),
        ]
    )
    evaluation = decision_engine.evaluate_route(
        route=route,
        mobility_profile=mobility_profile,
        facilities_by_station=facilities_by_station,
        elevator_status_by_station=elevator_status_by_station,
        restroom_by_station=restroom_by_station,
        failed_sources=candidate_failed_sources,
        data_sources=candidate_data_sources,
    )
    risk_reasons = _align_source_coverage_reasons(
        evaluation.risk_reasons,
        data_sources_by_station,
    )
    accessibility_checks = build_accessibility_checks(
        route=route,
        accessible_facilities=evaluation.accessible_facilities,
        facilities_by_station=facilities_by_station,
        elevator_status_by_station=elevator_status_by_station,
        restroom_by_station=restroom_by_station,
        blocked_facilities=evaluation.blocked_facilities,
        risk_reasons=risk_reasons,
        mobility_profile=mobility_profile,
        station_contexts=station_contexts,
        source_coverage_by_station=data_sources_by_station,
    )
    status = _candidate_response_status(
        candidate_data_sources,
        candidate_failed_sources,
    )
    aligned_risk = align_risk_with_user_judgement(
        risk_score=evaluation.risk_score,
        risk_level=evaluation.risk_level,
        risk_reasons=risk_reasons,
        failed_sources=candidate_failed_sources,
        accessibility_checks=accessibility_checks,
        mobility_profile=mobility_profile,
        status=status,
    )
    return RouteCandidateAssessment(
        route=route,
        status=status,
        risk_score=aligned_risk.risk_score,
        risk_level=aligned_risk.risk_level,
        risk_reasons=risk_reasons,
        caution_points=[reason.message for reason in risk_reasons],
        blocked_facilities=evaluation.blocked_facilities,
        accessible_facilities=evaluation.accessible_facilities,
        accessibility_checks=accessibility_checks,
        data_sources=candidate_data_sources,
        failed_sources=candidate_failed_sources,
        limitations=dedupe_strings(
            [*candidate_limitations, *evaluation.limitations]
        ),
    )


def _metadata_for_route[T](
    route: RouteCandidate,
    metadata_by_station: dict[str, list[T]],
) -> list[T]:
    route_stations = {
        normalize_station_name(station)
        for station, _role in accessibility_check_station_roles(route)
    }
    return [
        item
        for station, items in metadata_by_station.items()
        if normalize_station_name(station) in route_stations
        for item in items
    ]


def _candidate_response_status(
    data_sources: list[DataSourceMeta],
    failed_sources: list[FailedSource],
) -> ResponseStatus:
    has_unsupported_source = any(
        source.coverage_status == SourceCoverageStatus.UNSUPPORTED
        for source in data_sources
    )
    if failed_sources or has_unsupported_source:
        return ResponseStatus.PARTIAL
    return ResponseStatus.SUCCESS


def _align_source_coverage_reasons(
    reasons: list[RiskReason],
    source_coverage_by_station: dict[str, list[DataSourceMeta]],
) -> list[RiskReason]:
    aligned: list[RiskReason] = []
    for reason in reasons:
        station_name = reason.station_name
        if (
            reason.code == "elevator_not_found"
            and station_name
            and station_sources_are_unsupported(
                source_coverage_by_station,
                station_name,
                {"elevator_status", "elevator_info"},
            )
        ):
            aligned.append(
                reason.model_copy(
                    update={
                        "code": "elevator_source_unsupported",
                        "message": (
                            f"{station_name}역 엘리베이터 정보는 현재 연결된 "
                            "공공데이터 제공 범위 밖입니다."
                        ),
                    }
                )
            )
            continue
        if (
            reason.code == "no_accessible_restroom_when_required"
            and station_name
            and station_sources_are_unsupported(
                source_coverage_by_station,
                station_name,
                {"restroom"},
            )
        ):
            aligned.append(
                reason.model_copy(
                    update={
                        "code": "restroom_source_unsupported",
                        "message": (
                            f"{station_name}역 장애인화장실 정보는 현재 연결된 "
                            "공공데이터 제공 범위 밖입니다."
                        ),
                    }
                )
            )
            continue
        aligned.append(reason)
    return aligned
