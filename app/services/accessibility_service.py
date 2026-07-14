from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.cache.base import CacheProtocol
from app.cache.factory import build_cache
from app.core.concurrency import gather_limited
from app.core.config import Settings, get_settings
from app.engine.decision_engine import AccessibilityDecisionEngine
from app.engine.route_ranking import rank_route_candidate_assessments
from app.normalizers.helpers import normalize_station_name
from app.normalizers.route_normalizer import is_usable_route_candidate
from app.schemas.accessibility import (
    AccessibilityQuestionResult,
    AccessibilityResult,
    MobilityProfile,
)
from app.schemas.common import DataSourceMeta, FailedSource
from app.schemas.facility import AccessibleFacility
from app.schemas.route import RouteCandidate
from app.services.facility_service import FacilityService
from app.services.question_answering import (
    answer_accessibility_question as answer_question,
)
from app.services.route_candidate_assessment import assess_route_candidate
from app.services.route_service import RouteService
from app.services.station_context import (
    build_route_station_contexts,
    context_for_station,
    resolve_station_context,
)
from app.services.station_service import StationService
from app.services.trip_response import (
    build_no_route_result,
    build_station_clarification_result,
    build_trip_result,
)
from app.services.types import ServiceResult


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
            return build_station_clarification_result(
                origin=origin,
                destination=destination,
                mobility_profile=mobility_profile,
                origin_context=origin_context,
                destination_context=destination_context,
            )

        normalized_origin = origin_context.station_name
        normalized_destination = destination_context.station_name

        route_result = await self.route_service.get_route_candidates(
            normalized_origin,
            normalized_destination,
        )
        route_data_sources = list(route_result.data_sources)
        route_failed_sources = list(route_result.failed_sources)
        route_limitations = list(route_result.limitations)

        route_candidates = [
            route for route in route_result.value if is_usable_route_candidate(route)
        ]
        if not route_candidates:
            return build_no_route_result(
                origin=normalized_origin,
                destination=normalized_destination,
                mobility_profile=mobility_profile,
                data_sources=route_data_sources,
                failed_sources=route_failed_sources,
                limitations=route_limitations,
            )

        route_station_contexts = build_route_station_contexts(
            station_service=self.station_service,
            routes=route_candidates,
            origin=origin_context,
            destination=destination_context,
        )
        stations = _stations_from_routes(route_candidates)
        facilities_by_station: dict[str, list[AccessibleFacility]] = {}
        elevator_status_by_station: dict[str, list[AccessibleFacility]] = {}
        restroom_by_station: dict[str, list[AccessibleFacility]] = {}
        data_sources_by_station: dict[str, list[DataSourceMeta]] = {}
        failed_sources_by_station: dict[str, list[FailedSource]] = {}
        limitations_by_station: dict[str, list[str]] = {}

        facility_queries: list[
            tuple[
                str,
                str,
                Callable[
                    [],
                    Awaitable[ServiceResult[list[AccessibleFacility]]],
                ],
            ]
        ] = []
        for station in stations:
            station_context = context_for_station(station, route_station_contexts)
            facility_queries.append(
                (
                    station,
                    "facilities",
                    lambda context=station_context: (
                        self.facility_service.get_station_facilities(
                            context.station_name,
                            line=context.line,
                        )
                    ),
                )
            )
            facility_queries.append(
                (
                    station,
                    "elevators",
                    lambda context=station_context: (
                        self.facility_service.get_elevator_status(
                            context.station_name,
                            line=context.line,
                        )
                    ),
                )
            )
            if mobility_profile.need_accessible_restroom:
                facility_queries.append(
                    (
                        station,
                        "restrooms",
                        lambda context=station_context: (
                            self.facility_service.get_accessible_restroom(
                                context.station_name,
                                line=context.line,
                            )
                        ),
                    )
                )

        query_results = await gather_limited(
            (factory for _station, _kind, factory in facility_queries),
            limit=self.settings.facility_query_concurrency,
        )
        for (station, query_kind, _factory), query_result in zip(
            facility_queries,
            query_results,
            strict=True,
        ):
            _record_station_service_metadata(
                station,
                query_result,
                data_sources_by_station,
                failed_sources_by_station,
                limitations_by_station,
            )
            if query_kind == "facilities":
                facilities_by_station[station] = query_result.value
            elif query_kind == "elevators":
                elevator_status_by_station[station] = query_result.value
            else:
                restroom_by_station[station] = query_result.value

        assessments = [
            assess_route_candidate(
                decision_engine=self.decision_engine,
                route=route,
                mobility_profile=mobility_profile,
                origin_context=origin_context,
                destination_context=destination_context,
                route_data_sources=route_data_sources,
                route_failed_sources=route_failed_sources,
                route_limitations=route_limitations,
                data_sources_by_station=data_sources_by_station,
                failed_sources_by_station=failed_sources_by_station,
                limitations_by_station=limitations_by_station,
                facilities_by_station=facilities_by_station,
                elevator_status_by_station=elevator_status_by_station,
                restroom_by_station=restroom_by_station,
                station_contexts=route_station_contexts,
            )
            for route in route_candidates
        ]
        ranked_assessments = rank_route_candidate_assessments(assessments)
        return build_trip_result(
            origin=normalized_origin,
            destination=normalized_destination,
            mobility_profile=mobility_profile,
            ranked_assessments=ranked_assessments,
        )
    async def answer_accessibility_question(
        self,
        question: str,
    ) -> AccessibilityQuestionResult:
        return await answer_question(
            question,
            station_service=self.station_service,
            facility_service=self.facility_service,
            trip_answerer=self.generate_accessibility_brief,
        )
    async def generate_accessibility_brief(
        self,
        origin: str,
        destination: str,
        mobility_profile: MobilityProfile,
    ) -> AccessibilityResult:
        return await self.check_accessible_trip(origin, destination, mobility_profile)

def _stations_from_routes(routes: list[RouteCandidate]) -> list[str]:
    seen: set[str] = set()
    stations: list[str] = []
    for route in routes:
        for station in _route_station_names(route):
            normalized = normalize_station_name(station)
            if normalized in seen:
                continue
            seen.add(normalized)
            stations.append(station)
    return stations


def _record_station_service_metadata(
    station: str,
    result: ServiceResult[list[AccessibleFacility]],
    data_sources_by_station: dict[str, list[DataSourceMeta]],
    failed_sources_by_station: dict[str, list[FailedSource]],
    limitations_by_station: dict[str, list[str]],
) -> None:
    data_sources_by_station.setdefault(station, []).extend(result.data_sources)
    failed_sources_by_station.setdefault(station, []).extend(result.failed_sources)
    limitations_by_station.setdefault(station, []).extend(result.limitations)


def _route_station_names(route: RouteCandidate) -> list[str]:
    candidates = [
        route.origin,
        *route.stations,
        *(segment.from_station for segment in route.segments),
        *(segment.to_station for segment in route.segments),
        route.destination,
    ]
    seen: set[str] = set()
    stations: list[str] = []
    for station in candidates:
        normalized = normalize_station_name(station)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        stations.append(station)
    return stations
