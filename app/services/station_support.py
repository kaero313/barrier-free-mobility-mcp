from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.config import AppMode
from app.schemas.common import SourceCoverageStatus
from app.services.route_station_codes import resolve_route_station_code
from app.services.source_coverage import (
    evaluate_source_coverage,
    station_support_required_sources,
)
from app.services.station_context import StationLookupContext


class StationSupportStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class StationSupportDecision:
    station_name: str
    line: str | None
    status: StationSupportStatus
    route_code_verified: bool
    unsupported_sources: tuple[str, ...] = ()
    unknown_sources: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def evaluate_station_support(
    context: StationLookupContext,
    *,
    app_mode: AppMode,
) -> StationSupportDecision:
    if app_mode == AppMode.MOCK:
        return StationSupportDecision(
            station_name=context.station_name,
            line=context.line,
            status=StationSupportStatus.SUPPORTED,
            route_code_verified=True,
        )

    if (
        context.needs_clarification
        or context.station_id is None
        or context.line is None
        or context.operator is None
    ):
        return StationSupportDecision(
            station_name=context.station_name,
            line=context.line,
            status=StationSupportStatus.UNVERIFIED,
            route_code_verified=False,
            notes=(
                f"{_station_label(context)}은 현재 검증된 역·호선 목록에서 확인되지 않았습니다.",
            ),
        )

    route_code_verified = resolve_route_station_code(context.station_name, context.line) is not None
    source_decisions = [
        evaluate_source_coverage(source_name, context, app_mode=app_mode)
        for source_name in station_support_required_sources()
    ]
    unsupported_sources = tuple(
        decision.source_name
        for decision in source_decisions
        if decision.status == SourceCoverageStatus.UNSUPPORTED
    )
    unknown_sources = tuple(
        decision.source_name
        for decision in source_decisions
        if decision.status == SourceCoverageStatus.UNKNOWN
    )

    if route_code_verified and not unsupported_sources and not unknown_sources:
        return StationSupportDecision(
            station_name=context.station_name,
            line=context.line,
            status=StationSupportStatus.SUPPORTED,
            route_code_verified=True,
        )

    notes: list[str] = []
    station_label = _station_label(context)
    if not route_code_verified:
        notes.append(
            f"{station_label}은 최단경로 API 역 코드가 아직 검증되지 않아 "
            "역명 조회 결과를 사용합니다."
        )
    if unsupported_sources:
        notes.append(
            f"{station_label}은 현재 연결된 접근성 시설 데이터의 제공 범위가 일부 제한됩니다."
        )
    if unknown_sources:
        notes.append(f"{station_label}은 일부 접근성 데이터의 지원 범위를 확인하지 못했습니다.")
    return StationSupportDecision(
        station_name=context.station_name,
        line=context.line,
        status=StationSupportStatus.PARTIAL,
        route_code_verified=route_code_verified,
        unsupported_sources=unsupported_sources,
        unknown_sources=unknown_sources,
        notes=tuple(notes),
    )


def station_support_limitations(
    *contexts: StationLookupContext,
    app_mode: AppMode,
) -> list[str]:
    limitations: list[str] = []
    for context in contexts:
        decision = evaluate_station_support(context, app_mode=app_mode)
        if decision.status == StationSupportStatus.SUPPORTED:
            continue
        for note in decision.notes:
            if note not in limitations:
                limitations.append(note)
    return limitations


def _station_label(context: StationLookupContext) -> str:
    station_name = context.station_name
    station = station_name if station_name.endswith("역") else f"{station_name}역"
    return f"{context.line}호선 {station}" if context.line else station
