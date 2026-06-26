from __future__ import annotations

from datetime import datetime
from typing import Any

from app.schemas.accessibility import ConfidenceLevel, EvidenceSource, RiskLevel
from app.schemas.common import CacheStatus, DataSourceMeta, FailedSource, ResponseStatus

SOURCE_DISPLAY_NAMES = {
    "shortest_route": "서울교통공사_최단경로이동정보",
    "facility_info": "서울교통공사_편의시설위치정보",
    "elevator_status": "서울교통공사_교통약자_이용시설_승강기_가동현황",
    "elevator_info": "서울시 교통공사 지하철역 교통약자이용정보 엘리베이터 현황",
    "restroom": "서울시 교통공사 지하철역 교통약자이용정보 장애인화장실 현황",
    "station_resolution": "내부 역명 정규화",
}

CRITICAL_SOURCES = {"shortest_route", "elevator_status"}
CORE_EVIDENCE_SOURCES = {"shortest_route", "facility_info", "elevator_status"}


def build_evidence_context(
    *,
    status: ResponseStatus,
    risk_level: RiskLevel,
    data_sources: list[DataSourceMeta],
    failed_sources: list[FailedSource],
    limitations: list[str],
) -> dict[str, Any]:
    evidence_sources = _build_evidence_sources(data_sources, failed_sources)
    unverified_parts = _build_unverified_parts(data_sources, failed_sources, limitations)
    confidence_level, confidence_reasons = _calculate_confidence(
        status=status,
        risk_level=risk_level,
        data_sources=data_sources,
        failed_sources=failed_sources,
        unverified_parts=unverified_parts,
    )
    return {
        "confidence_level": confidence_level,
        "confidence_reasons": confidence_reasons,
        "last_checked_at": _last_checked_at(evidence_sources),
        "evidence_sources": evidence_sources,
        "unverified_parts": unverified_parts,
    }


def _build_evidence_sources(
    data_sources: list[DataSourceMeta],
    failed_sources: list[FailedSource],
) -> list[EvidenceSource]:
    evidence = [
        EvidenceSource(
            source_name=source.source_name,
            display_name=display_name_for_source(source.source_name),
            source_type=source.source_type,
            checked_at=source.fetched_at,
            cache_status=source.cache_status,
            staleness_seconds=source.staleness_seconds,
            success=source.success,
            note=_note_for_data_source(source),
        )
        for source in data_sources
    ]

    represented = {(source.source_name, source.success) for source in evidence}
    for failed in failed_sources:
        if (failed.source_name, False) in represented:
            continue
        evidence.append(
            EvidenceSource(
                source_name=failed.source_name,
                display_name=display_name_for_source(failed.source_name),
                source_type="internal"
                if failed.source_name == "station_resolution"
                else "public_api",
                checked_at=None,
                cache_status=CacheStatus.BYPASS,
                success=False,
                note=f"확인 실패: {failed.reason}",
            )
        )
    return evidence


def _build_unverified_parts(
    data_sources: list[DataSourceMeta],
    failed_sources: list[FailedSource],
    limitations: list[str],
) -> list[str]:
    parts: list[str] = []
    if not data_sources:
        parts.append("핵심 데이터 출처를 확인하지 못했습니다.")

    for failed in failed_sources:
        parts.append(f"{display_name_for_source(failed.source_name)} 확인 실패: {failed.reason}")

    for source in data_sources:
        display_name = display_name_for_source(source.source_name)
        if not source.success:
            parts.append(f"{display_name} 응답을 신뢰 가능한 성공 응답으로 확인하지 못했습니다.")
        if source.cache_status == CacheStatus.STALE:
            parts.append(f"{display_name}는 오래된 캐시 응답입니다.")
        elif source.cache_status == CacheStatus.HIT:
            parts.append(f"{display_name}는 캐시 응답을 사용했습니다.")
        if source.source_type == "fixture":
            parts.append(f"{display_name}는 mock fixture 데이터입니다.")

    for limitation in limitations:
        if "확인" in limitation or "실패" in limitation or "캐시" in limitation:
            parts.append(limitation)

    return _dedupe_strings(parts)


def _calculate_confidence(
    *,
    status: ResponseStatus,
    risk_level: RiskLevel,
    data_sources: list[DataSourceMeta],
    failed_sources: list[FailedSource],
    unverified_parts: list[str],
) -> tuple[ConfidenceLevel, list[str]]:
    successful_sources = {source.source_name for source in data_sources if source.success}
    failed_names = {source.source_name for source in failed_sources}
    cache_or_fixture_used = any(
        source.source_type in {"cache", "fixture"}
        or source.cache_status in {CacheStatus.HIT, CacheStatus.STALE}
        for source in data_sources
    )
    stale_used = any(source.cache_status == CacheStatus.STALE for source in data_sources)
    missing_core = sorted(CORE_EVIDENCE_SOURCES - successful_sources - failed_names)
    critical_failure = bool(CRITICAL_SOURCES.intersection(failed_names))

    if status == ResponseStatus.NEEDS_CLARIFICATION:
        return "LOW", ["추가 정보가 필요해 접근성 판단을 완료하지 못했습니다."]
    if status == ResponseStatus.FAILED:
        return "LOW", ["경로 접근성 판단이 실패했습니다."]
    if risk_level == "UNKNOWN":
        return "LOW", ["위험 수준이 UNKNOWN이라 현재 데이터만으로 확정하기 어렵습니다."]
    if critical_failure:
        return "LOW", ["최단경로 또는 엘리베이터 상태 같은 핵심 출처 확인에 실패했습니다."]
    if missing_core:
        return "LOW", [
            "핵심 출처가 일부 확인되지 않았습니다: " + ", ".join(
                display_name_for_source(source) for source in missing_core
            )
        ]

    if failed_sources:
        return "MEDIUM", ["일부 비핵심 출처 확인에 실패했습니다."]
    if stale_used:
        return "MEDIUM", ["일부 출처가 오래된 캐시 응답입니다."]
    if cache_or_fixture_used:
        return "MEDIUM", ["일부 출처가 캐시 또는 mock fixture 데이터입니다."]
    if unverified_parts:
        return "MEDIUM", ["확인하지 못한 세부 정보가 일부 있습니다."]

    return "HIGH", ["핵심 출처가 최신 public API 응답으로 확인되었습니다."]


def _note_for_data_source(source: DataSourceMeta) -> str:
    if not source.success:
        return f"조회 실패: {source.error_message or 'unknown'}"
    if source.cache_status == CacheStatus.STALE:
        return "오래된 캐시 응답 사용"
    if source.cache_status == CacheStatus.HIT:
        return "캐시 응답 사용"
    if source.source_type == "fixture":
        return "mock fixture 데이터 사용"
    if source.source_type == "public_api":
        return "공공 API 조회 성공"
    if source.source_type == "internal":
        return "서버 내부 처리"
    return "출처 metadata 확인"


def _last_checked_at(evidence_sources: list[EvidenceSource]) -> datetime | None:
    checked_values = [
        source.checked_at for source in evidence_sources if source.checked_at is not None
    ]
    return max(checked_values) if checked_values else None


def display_name_for_source(source_name: str) -> str:
    return SOURCE_DISPLAY_NAMES.get(source_name, source_name)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
