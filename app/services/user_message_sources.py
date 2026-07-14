from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.accessibility import DEFAULT_SAFETY_NOTICE, AccessibilityResult
from app.schemas.common import ResponseStatus, SourceCoverageStatus
from app.services.user_message_accessibility import dedupe_strings

SENSITIVE_NOTICE_MARKERS = (
    "http://",
    "https://",
    "serviceKey",
    "PUBLIC_DATA_SERVICE_KEY",
    "SEOUL_OPEN_API_KEY",
    "MCP_API_KEY",
    "Authorization",
    "Bearer ",
)


def data_basis(result: AccessibilityResult) -> list[str]:
    checked_at = _format_checked_at(result.last_checked_at)
    lines: list[str] = []
    if checked_at:
        lines.append(f"전체 조회 시각: {checked_at}")
    else:
        lines.append("전체 조회 시각: 확인된 기준 시각 없음")

    lines.extend(
        [
            _source_group_line(result, "최단경로 정보", {"shortest_route"}),
            _source_group_line(
                result,
                "엘리베이터 위치·운행상태",
                {"elevator_status", "elevator_info"},
            ),
            _source_group_line(result, "편의시설 정보", {"facility_info"}),
        ]
    )
    if result.mobility_profile.need_accessible_restroom or _has_restroom_evidence(result):
        lines.append(_restroom_group_line(result))
    lines.append(
        "확인 범위: 지하철 경로 기준입니다. 저상버스 등 지상 대체 경로는 포함하지 않았습니다."
    )
    return [line for line in lines if line]


def notices(result: AccessibilityResult) -> list[str]:
    notice_items = [
        DEFAULT_SAFETY_NOTICE,
        "공공 API 기준 정보이므로 현장 상황과 다를 수 있습니다.",
    ]
    if result.status in {ResponseStatus.PARTIAL, ResponseStatus.FAILED} or result.failed_sources:
        notice_items.append("일부 데이터가 확인되지 않아 결과가 제한적입니다.")
    if result.status == ResponseStatus.NEEDS_CLARIFICATION:
        notice_items.append("역명과 이동 조건을 확인한 뒤 다시 조회하는 것을 권장합니다.")
    for limitation in result.limitations:
        if limitation == (
            "대표 접근성 시설만 포함했습니다. 전체 시설 목록은 개별 시설 조회 도구로 확인하세요."
        ):
            notice_items.append("전체 시설 목록은 개별 시설 조회로 추가 확인할 수 있습니다.")
        elif _looks_sensitive(limitation):
            notice_items.append("일부 출처 세부 정보는 보안상 표시하지 않았습니다.")
        elif limitation:
            notice_items.append(limitation)
    return dedupe_strings(notice_items)


def _has_restroom_evidence(result: AccessibilityResult) -> bool:
    return any(source.source_name == "restroom" for source in result.evidence_sources)


def _source_group_line(
    result: AccessibilityResult,
    label: str,
    source_names: set[str],
) -> str:
    sources = [
        source
        for source in result.evidence_sources
        if source.source_name in source_names
    ]
    if not sources:
        return f"{label}: 미확인"

    unsupported_sources = [
        source
        for source in sources
        if source.coverage_status == SourceCoverageStatus.UNSUPPORTED
    ]
    if len(unsupported_sources) == len(sources):
        return f"{label}: 현재 데이터 제공 범위 밖"
    successful_sources = [source for source in sources if source.success]
    failed_sources = [
        source
        for source in sources
        if not source.success
        and source.coverage_status != SourceCoverageStatus.UNSUPPORTED
    ]
    if successful_sources:
        checked_at = _latest_checked_at(successful_sources)
        suffix = f"{_format_time_only(checked_at)} 확인" if checked_at else "확인"
        if failed_sources:
            suffix += ", 일부 확인 실패"
        return f"{label}: {suffix}"
    return f"{label}: 확인 실패"


def _restroom_group_line(result: AccessibilityResult) -> str:
    sources = [
        source for source in result.evidence_sources if source.source_name == "restroom"
    ]
    unsupported = bool(sources) and all(
        source.coverage_status == SourceCoverageStatus.UNSUPPORTED
        for source in sources
    )
    checked_at = _latest_checked_at([source for source in sources if source.success])
    station_parts: list[str] = []
    if result.accessibility_checks:
        for check in result.accessibility_checks:
            if check.restroom_available is True:
                if check.restroom_required is True:
                    station_parts.append(f"{check.station} 확인(필수)")
                elif check.restroom_required is False:
                    station_parts.append(f"{check.station} 확인(참고)")
                else:
                    station_parts.append(f"{check.station} 확인")
            elif check.restroom_available is False:
                if unsupported and check.restroom_required is True:
                    station_parts.append(f"{check.station} 데이터 제공 범위 밖(필수)")
                elif unsupported and check.restroom_required is False:
                    station_parts.append(f"{check.station} 데이터 제공 범위 밖(참고)")
                elif check.restroom_required is True:
                    station_parts.append(f"{check.station} 미확인(필수)")
                elif check.restroom_required is False:
                    station_parts.append(f"{check.station} 미확인(참고)")
                else:
                    station_parts.append(f"{check.station} 미확인")

    if station_parts:
        suffix = ", ".join(dedupe_strings(station_parts))
        if checked_at:
            suffix += f" ({_format_time_only(checked_at)} 조회)"
        elif unsupported:
            suffix += " (현재 데이터 제공 범위 밖)"
        elif sources and all(not source.success for source in sources):
            suffix += " (확인 실패)"
        return f"장애인화장실 정보: {suffix}"

    if not sources:
        return "장애인화장실 정보: 미확인"
    if unsupported:
        return "장애인화장실 정보: 현재 데이터 제공 범위 밖"
    if any(source.success for source in sources):
        return (
            "장애인화장실 정보: "
            + (f"{_format_time_only(checked_at)} 확인" if checked_at else "확인")
        )
    return "장애인화장실 정보: 확인 실패"


def _latest_checked_at(sources) -> datetime | None:
    checked_values = [
        source.checked_at for source in sources if source.checked_at is not None
    ]
    return max(checked_values) if checked_values else None


def _looks_sensitive(value: str) -> bool:
    return any(marker in value for marker in SENSITIVE_NOTICE_MARKERS)


def _format_checked_at(checked_at: datetime | None) -> str | None:
    if checked_at is None:
        return None
    kst = timezone(timedelta(hours=9), "KST")
    local_checked_at = checked_at.astimezone(kst)
    return (
        f"{local_checked_at.year}년 {local_checked_at.month}월 {local_checked_at.day}일 "
        f"{local_checked_at.hour:02d}:{local_checked_at.minute:02d}"
    )


def _format_time_only(checked_at: datetime | None) -> str | None:
    if checked_at is None:
        return None
    kst = timezone(timedelta(hours=9), "KST")
    local_checked_at = checked_at.astimezone(kst)
    return f"{local_checked_at.hour:02d}:{local_checked_at.minute:02d}"
