from __future__ import annotations

from app.engine.elevator_status import summarize_elevator_status
from app.schemas.accessibility import (
    EvidenceSource,
    FacilityAnswerState,
    FacilityQuestionItem,
    FacilityQuestionKind,
    FacilityQuestionResult,
)
from app.schemas.common import (
    CacheStatus,
    DataSourceMeta,
    FailedSource,
    ResponseStatus,
    SourceCoverageStatus,
)
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.services.evidence import display_name_for_source
from app.services.facility_message import build_facility_user_message
from app.services.types import ServiceResult


def build_facility_question_result(
    *,
    station_name: str,
    line: str | None,
    question_kind: FacilityQuestionKind,
    service_results: dict[FacilityType, ServiceResult[list[AccessibleFacility]]],
) -> FacilityQuestionResult:
    data_sources = _dedupe_data_sources(
        [source for result in service_results.values() for source in result.data_sources]
    )
    failed_sources = _dedupe_failed_sources(
        [failed for result in service_results.values() for failed in result.failed_sources]
    )
    limitations = _dedupe_strings(
        [limitation for result in service_results.values() for limitation in result.limitations]
    )
    items = [
        FacilityQuestionItem(
            facility_type=facility_type,
            answer_state=_answer_state(facility_type, result),
            facilities=result.value,
        )
        for facility_type, result in service_results.items()
    ]
    status = _response_status(items, data_sources, failed_sources)
    evidence_sources = _evidence_sources(data_sources, failed_sources)
    result = FacilityQuestionResult(
        status=status,
        station_name=station_name,
        line=line,
        question_kind=question_kind,
        items=items,
        last_checked_at=max(
            (source.fetched_at for source in data_sources if source.success),
            default=None,
        ),
        evidence_sources=evidence_sources,
        failed_sources=failed_sources,
        limitations=limitations,
        unverified_parts=_unverified_parts(items, data_sources, failed_sources),
    )
    return result.model_copy(update={"user_message": build_facility_user_message(result)})


def _answer_state(
    facility_type: FacilityType,
    result: ServiceResult[list[AccessibleFacility]],
) -> FacilityAnswerState:
    if result.data_sources and all(
        source.coverage_status == SourceCoverageStatus.UNSUPPORTED
        for source in result.data_sources
    ):
        return FacilityAnswerState.UNSUPPORTED
    source_succeeded = any(source.success for source in result.data_sources)
    if not result.value:
        return FacilityAnswerState.NOT_FOUND if source_succeeded else FacilityAnswerState.UNKNOWN

    if facility_type == FacilityType.ELEVATOR:
        return summarize_elevator_status(result.value).answer_state

    statuses = {facility.status for facility in result.value}
    if statuses == {FacilityStatus.AVAILABLE}:
        return FacilityAnswerState.AVAILABLE
    if statuses == {FacilityStatus.MAINTENANCE}:
        return FacilityAnswerState.MAINTENANCE
    if statuses == {FacilityStatus.UNAVAILABLE}:
        return FacilityAnswerState.UNAVAILABLE
    if statuses == {FacilityStatus.UNKNOWN}:
        return FacilityAnswerState.UNKNOWN
    return FacilityAnswerState.MIXED


def _response_status(
    items: list[FacilityQuestionItem],
    data_sources: list[DataSourceMeta],
    failed_sources: list[FailedSource],
) -> ResponseStatus:
    unsupported = any(
        item.answer_state == FacilityAnswerState.UNSUPPORTED for item in items
    )
    successful_source = any(source.success for source in data_sources)
    source_failed = bool(failed_sources) or any(
        not source.success
        and source.coverage_status != SourceCoverageStatus.UNSUPPORTED
        for source in data_sources
    )
    if unsupported and not source_failed:
        return ResponseStatus.PARTIAL
    if not successful_source and source_failed:
        return ResponseStatus.FAILED
    if not successful_source and not data_sources:
        return ResponseStatus.FAILED
    if source_failed or any(item.answer_state == FacilityAnswerState.UNKNOWN for item in items):
        return ResponseStatus.PARTIAL
    return ResponseStatus.SUCCESS


def _evidence_sources(
    data_sources: list[DataSourceMeta],
    failed_sources: list[FailedSource],
) -> list[EvidenceSource]:
    evidence = [
        EvidenceSource(
            source_name=source.source_name,
            display_name=display_name_for_source(source.source_name),
            source_type=source.source_type,
            checked_at=(
                None
                if source.coverage_status == SourceCoverageStatus.UNSUPPORTED
                else source.fetched_at
            ),
            cache_status=source.cache_status,
            staleness_seconds=source.staleness_seconds,
            success=source.success,
            coverage_status=source.coverage_status,
            coverage_note=source.coverage_note,
            note=_source_note(source),
        )
        for source in data_sources
    ]
    represented_failures = {
        source.source_name for source in evidence if not source.success
    }
    for failed in failed_sources:
        if failed.source_name in represented_failures:
            continue
        evidence.append(
            EvidenceSource(
                source_name=failed.source_name,
                display_name=display_name_for_source(failed.source_name),
                source_type="public_api",
                success=False,
                note="확인 실패",
            )
        )
    return evidence


def _source_note(source: DataSourceMeta) -> str:
    if source.coverage_status == SourceCoverageStatus.UNSUPPORTED:
        return source.coverage_note or "데이터 제공 범위 밖"
    if not source.success:
        return "조회 실패"
    if source.cache_status == CacheStatus.STALE:
        return "오래된 캐시 응답 사용"
    if source.cache_status == CacheStatus.HIT:
        return "캐시 응답 사용"
    if source.source_type == "fixture":
        return "mock fixture 데이터 사용"
    return "공공 API 조회 성공" if source.source_type == "public_api" else "내부 데이터 확인"


def _unverified_parts(
    items: list[FacilityQuestionItem],
    data_sources: list[DataSourceMeta],
    failed_sources: list[FailedSource],
) -> list[str]:
    parts = [
        f"{display_name_for_source(failed.source_name)} 확인 실패"
        for failed in failed_sources
    ]
    for source in data_sources:
        if source.coverage_status == SourceCoverageStatus.UNSUPPORTED:
            parts.append(source.coverage_note or "현재 연결된 데이터 제공 범위 밖입니다.")
            continue
        if source.cache_status == CacheStatus.STALE:
            parts.append(f"{display_name_for_source(source.source_name)}는 오래된 캐시 응답입니다.")
    for item in items:
        label = (
            "엘리베이터"
            if item.facility_type == FacilityType.ELEVATOR
            else "장애인화장실"
        )
        if item.answer_state == FacilityAnswerState.NOT_FOUND:
            parts.append(f"{label}은 현재 공공데이터에서 확인되지 않았습니다.")
        elif item.answer_state == FacilityAnswerState.UNSUPPORTED:
            parts.append(f"{label}은 현재 연결된 데이터 소스의 제공 범위 밖입니다.")
        elif item.answer_state == FacilityAnswerState.UNKNOWN:
            parts.append(f"{label} 상태를 확인하지 못했습니다.")
    return _dedupe_strings(parts)


def _dedupe_data_sources(values: list[DataSourceMeta]) -> list[DataSourceMeta]:
    seen: set[tuple] = set()
    result: list[DataSourceMeta] = []
    for value in values:
        key = (
            value.source_name,
            value.source_type,
            value.cache_status,
            value.success,
            value.error_message,
            value.coverage_status,
            value.coverage_note,
        )
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _dedupe_failed_sources(values: list[FailedSource]) -> list[FailedSource]:
    seen: set[tuple[str, str]] = set()
    result: list[FailedSource] = []
    for value in values:
        key = (value.source_name, value.reason)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
