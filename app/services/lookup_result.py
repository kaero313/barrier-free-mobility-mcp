from __future__ import annotations

from app.schemas.common import CacheStatus, ResponseStatus, SourceCoverageStatus
from app.schemas.facility import AccessibleFacility
from app.schemas.lookup import FacilityLookupResult, LookupOutcome, RouteLookupResult
from app.schemas.route import RouteCandidate
from app.services.types import ServiceResult


def build_facility_lookup_result(
    *,
    station: str,
    line: str | None,
    service_result: ServiceResult[list[AccessibleFacility]],
) -> FacilityLookupResult:
    status, outcome = classify_lookup_result(service_result)
    return FacilityLookupResult(
        status=status,
        outcome=outcome,
        station=station,
        line=line,
        data=service_result.value,
        data_sources=service_result.data_sources,
        failed_sources=service_result.failed_sources,
        limitations=service_result.limitations,
    )


def build_route_lookup_result(
    *,
    origin: str,
    destination: str,
    service_result: ServiceResult[list[RouteCandidate]],
) -> RouteLookupResult:
    status, outcome = classify_lookup_result(service_result)
    return RouteLookupResult(
        status=status,
        outcome=outcome,
        origin=origin,
        destination=destination,
        data=service_result.value,
        data_sources=service_result.data_sources,
        failed_sources=service_result.failed_sources,
        limitations=service_result.limitations,
    )


def classify_lookup_result[T](
    service_result: ServiceResult[list[T]],
) -> tuple[ResponseStatus, LookupOutcome]:
    sources = service_result.data_sources
    unsupported_sources = [
        source
        for source in sources
        if source.coverage_status == SourceCoverageStatus.UNSUPPORTED
    ]
    if sources and len(unsupported_sources) == len(sources):
        return ResponseStatus.PARTIAL, LookupOutcome.UNSUPPORTED

    if any(source.cache_status == CacheStatus.STALE for source in sources):
        return ResponseStatus.PARTIAL, LookupOutcome.STALE

    failed = bool(service_result.failed_sources) or any(
        not source.success
        and source.coverage_status != SourceCoverageStatus.UNSUPPORTED
        for source in sources
    )
    if failed:
        has_usable_data = bool(service_result.value) or any(
            source.success for source in sources
        )
        if has_usable_data:
            return ResponseStatus.PARTIAL, LookupOutcome.PARTIAL
        return ResponseStatus.FAILED, LookupOutcome.FAILED

    if unsupported_sources:
        return ResponseStatus.PARTIAL, LookupOutcome.PARTIAL
    if service_result.value:
        return ResponseStatus.SUCCESS, LookupOutcome.DATA
    return ResponseStatus.SUCCESS, LookupOutcome.EMPTY
