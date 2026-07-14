from __future__ import annotations

from dataclasses import dataclass

from app.normalizers.facility_identity import facility_record_identity
from app.schemas.accessibility import FacilityAnswerState
from app.schemas.common import DataSourceMeta, SourceCoverageStatus
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType

ELEVATOR_SOURCE_NAMES = {"facility_info", "elevator_status", "elevator_info"}


@dataclass(frozen=True)
class ElevatorStatusSummary:
    answer_state: FacilityAnswerState
    representative_status: FacilityStatus
    facilities: tuple[AccessibleFacility, ...]
    operational_facilities: tuple[AccessibleFacility, ...]
    available: tuple[AccessibleFacility, ...]
    maintenance: tuple[AccessibleFacility, ...]
    unavailable: tuple[AccessibleFacility, ...]
    unknown: tuple[AccessibleFacility, ...]

    @property
    def restricted(self) -> tuple[AccessibleFacility, ...]:
        return (*self.maintenance, *self.unavailable)


def summarize_elevator_status(
    facilities: list[AccessibleFacility],
) -> ElevatorStatusSummary:
    elevators = tuple(
        _dedupe_records(
            [
                facility
                for facility in facilities
                if facility.facility_type == FacilityType.ELEVATOR
            ]
        )
    )
    operational = tuple(
        facility
        for facility in elevators
        if facility.source_name in {None, "elevator_status"}
    )
    available = tuple(
        facility for facility in operational if facility.status == FacilityStatus.AVAILABLE
    )
    maintenance = tuple(
        facility for facility in operational if facility.status == FacilityStatus.MAINTENANCE
    )
    unavailable = tuple(
        facility for facility in operational if facility.status == FacilityStatus.UNAVAILABLE
    )
    unknown = tuple(
        facility for facility in operational if facility.status == FacilityStatus.UNKNOWN
    )

    answer_state = _answer_state(
        has_facilities=bool(elevators),
        available=bool(available),
        maintenance=bool(maintenance),
        unavailable=bool(unavailable),
        unknown=bool(unknown),
    )
    representative_status = {
        FacilityAnswerState.AVAILABLE: FacilityStatus.AVAILABLE,
        FacilityAnswerState.MAINTENANCE: FacilityStatus.MAINTENANCE,
        FacilityAnswerState.UNAVAILABLE: FacilityStatus.UNAVAILABLE,
    }.get(answer_state, FacilityStatus.UNKNOWN)
    return ElevatorStatusSummary(
        answer_state=answer_state,
        representative_status=representative_status,
        facilities=elevators,
        operational_facilities=operational,
        available=available,
        maintenance=maintenance,
        unavailable=unavailable,
        unknown=unknown,
    )


def align_elevator_answer_state_with_sources(
    answer_state: FacilityAnswerState,
    data_sources: list[DataSourceMeta],
) -> FacilityAnswerState:
    if answer_state != FacilityAnswerState.NOT_FOUND:
        return answer_state

    relevant = [
        source
        for source in data_sources
        if source.source_name in ELEVATOR_SOURCE_NAMES
    ]
    if not relevant:
        return FacilityAnswerState.UNKNOWN
    if all(
        source.coverage_status == SourceCoverageStatus.UNSUPPORTED
        for source in relevant
    ):
        return FacilityAnswerState.UNSUPPORTED
    supported_or_unknown = [
        source
        for source in relevant
        if source.coverage_status != SourceCoverageStatus.UNSUPPORTED
    ]
    if any(not source.success for source in supported_or_unknown):
        return FacilityAnswerState.UNKNOWN
    if any(source.success for source in supported_or_unknown):
        return FacilityAnswerState.NOT_FOUND
    return FacilityAnswerState.UNKNOWN


def _answer_state(
    *,
    has_facilities: bool,
    available: bool,
    maintenance: bool,
    unavailable: bool,
    unknown: bool,
) -> FacilityAnswerState:
    observed_states = sum((available, maintenance, unavailable, unknown))
    if observed_states > 1:
        return FacilityAnswerState.MIXED
    if available:
        return FacilityAnswerState.AVAILABLE
    if maintenance:
        return FacilityAnswerState.MAINTENANCE
    if unavailable:
        return FacilityAnswerState.UNAVAILABLE
    if unknown or has_facilities:
        return FacilityAnswerState.UNKNOWN
    return FacilityAnswerState.NOT_FOUND


def _dedupe_records(
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
