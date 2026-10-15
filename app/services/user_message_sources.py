from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.accessibility import (
    CHARGER_SOURCE_UNSUPPORTED_NOTE,
    DEFAULT_SAFETY_NOTICE,
    AccessibilityEvidenceStatus,
    AccessibilityResult,
    FacilityAnswerState,
)
from app.schemas.common import ResponseStatus, SourceCoverageStatus
from app.services.user_message_accessibility import (
    dedupe_strings,
    station_label,
)
from app.services.user_message_decision import charger_unchecked, judgement, lead_points

# 경로 결과는 대표 시설만 담는다. MCP 클라이언트와 웹 사용자 모두 따라 할 수 있는 말로 안내한다.
REPRESENTATIVE_FACILITY_LIMITATION = (
    "대표 접근성 시설만 포함했습니다. 역별 전체 시설 목록은 역 시설 질문으로 볼 수 있습니다."
)

# 경로를 찾지 못한 답변은 첫 문장이 이미 이 한계를 말하므로 주의사항에서 반복하지 않는다.
NO_ROUTE_LIMITATION = "공공 경로 데이터에서 유효한 경로 후보를 확인하지 못했습니다."

# 데이터 한계와 경로 범위는 한 문장으로 알린다. 확인 시각 목록에 범위 설명을 섞지 않는다.
TRIP_SCOPE_NOTICE = (
    "공공데이터의 지하철 경로 기준이라 현장 상황과 다를 수 있고, "
    "저상버스 등 지상 대체 경로는 포함하지 않았습니다."
)

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


# 출처를 차례로 부르느라 생기는 몇 분 차이는 사용자에게 의미가 없다. 이보다 오래된 출처(이전
# 응답 재사용 등)만 따로 시각을 밝힌다.
_UNSUPPORTED_GROUP_STATUS = "현재 데이터 제공 범위 밖"
_SAME_LOOKUP_WINDOW = timedelta(minutes=5)


def data_basis(result: AccessibilityResult) -> list[str]:
    source_groups = [
        ("최단경로 정보", {"shortest_route"}),
        ("엘리베이터 위치·운행상태", {"elevator_status", "elevator_info"}),
        ("편의시설 정보", {"facility_info"}),
    ]
    if result.mobility_profile.need_accessible_restroom or _has_restroom_evidence(result):
        source_groups.append(("장애인화장실 정보", {"restroom"}))

    folded_times: list[datetime] = []
    others: list[tuple[str, str]] = []
    for label, source_names in source_groups:
        checked_at = _fresh_checked_at(result, source_names)
        if checked_at is not None:
            folded_times.append(checked_at)
            continue
        status = _source_group_status(result, source_names)
        if result.selected_route is None and status == "미확인":
            # 경로를 찾지 못했거나 역을 확정하지 못하면 역별 시설은 조회하지 않는다. 본문이 이미 그
            # 이유를 말하므로 조회하지 않은 출처를 "미확인"으로 늘어놓지 않는다.
            continue
        if result.accessibility_checks and status == _UNSUPPORTED_GROUP_STATUS:
            # 제공 범위 밖은 표와 요약이 역별로 이미 말한다. 조회 시각도 없으니 따로 적지 않는다.
            continue
        others.append((label, status))

    lines: list[str] = []
    if folded_times:
        # 함께 조회한 출처는 가장 이른 시각 하나로 묶는다. 확인한 출처 목록은 판단 근거가 말한다.
        lines.append(f"조회 시각: {_format_checked_at(min(folded_times))}")
    lines.extend(f"{labels}: {status}" for labels, status in _merge_same_status(others))
    return lines


def _fresh_checked_at(result: AccessibilityResult, source_names: set[str]) -> datetime | None:
    """Return the group's check time when every source succeeded close to the overall lookup."""
    # 제공 범위 밖인 출처는 조회 실패가 아니다. 표와 요약이 역별로 밝히므로 시각 묶음에서만 뺀다.
    sources = [
        source
        for source in result.evidence_sources
        if source.source_name in source_names
        and source.coverage_status != SourceCoverageStatus.UNSUPPORTED
    ]
    if result.last_checked_at is None or not sources:
        return None
    if not all(source.success for source in sources):
        return None
    checked_at = _latest_checked_at(sources)
    if checked_at is None or result.last_checked_at - checked_at > _SAME_LOOKUP_WINDOW:
        return None
    return checked_at


def _merge_same_status(groups: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Join sources checked at the same time; failed or missing sources keep their own line."""
    labels_by_status: dict[str, list[str]] = {}
    for label, status in groups:
        labels_by_status.setdefault(status, []).append(label)
    return [(", ".join(labels), status) for status, labels in labels_by_status.items()]


def notices(result: AccessibilityResult) -> list[str]:
    if result.status == ResponseStatus.NEEDS_CLARIFICATION:
        # 되묻는 답변은 아직 아무것도 조회하지 않아 데이터 한계나 운행 상태 안내가 해당하지 않는다.
        return []
    # 표가 이미 엘리베이터 정보가 제공 범위 밖이라고 밝힌 역은 제공 범위 안내를 반복하지 않는다.
    unsupported_stations = [
        station_label(check.station)
        for check in result.accessibility_checks
        if check.elevator_answer_state == FacilityAnswerState.UNSUPPORTED
    ]
    covered_by_table = {
        limitation
        for limitation in result.limitations
        if (
            _is_coverage_limitation(limitation)
            and any(station in limitation for station in unsupported_stations)
        )
        # 경로를 찾지 못하면 역별 시설을 조회하지 않으므로 시설 데이터 범위 안내도 해당하지 않는다.
        or (result.selected_route is None and _is_facility_coverage_limitation(limitation))
    }
    priority_limitations = [
        limitation
        for limitation in result.limitations
        if _is_coverage_limitation(limitation)
        and not _looks_sensitive(limitation)
        and limitation not in covered_by_table
    ]
    notice_items = [
        # 운행 상태를 하나도 보여 주지 않은 답변(경로 없음, 모든 역이 제공 범위 밖)에는 운행 상태가
        # 바뀔 수 있다는 안내가 해당하지 않는다.
        *([DEFAULT_SAFETY_NOTICE] if _shows_elevator_status(result) else []),
        # 경로를 찾지 못하면 "현장과 다를 수 있는" 경로 결과 자체가 없다.
        *([TRIP_SCOPE_NOTICE] if result.selected_route is not None else []),
        *priority_limitations,
        # 요약 줄이 없는 답변(이용 가능 판단)에서도 요청한 충전기를 확인하지 못했다는 사실은 남긴다.
        *(
            [CHARGER_SOURCE_UNSUPPORTED_NOTE]
            if charger_unchecked(result) and not lead_points(judgement(result), result)
            else []
        ),
    ]
    # 실제 조회 실패가 있을 때만 알린다. 제공 범위 밖이나 정보 없음은 표와 요약이 역별로 말하고,
    # 판단 자체가 실패한 답변은 첫 문장이 이미 데이터를 확인하지 못했다고 말한다.
    if result.status != ResponseStatus.FAILED and result.failed_sources:
        notice_items.append("일부 데이터가 확인되지 않아 결과가 제한적입니다.")
    for limitation in result.limitations:
        if (
            limitation in priority_limitations
            or limitation in covered_by_table
            or limitation == NO_ROUTE_LIMITATION
        ):
            continue
        if limitation == REPRESENTATIVE_FACILITY_LIMITATION:
            # 표가 숨긴 엘리베이터는 그 칸에서 물을 질문까지 알려 준다. 숨긴 것이 없으면 전체 목록
            # 안내는 판단에 보탤 것이 없으니 붙이지 않는다.
            continue
        if _looks_sensitive(limitation):
            notice_items.append("일부 출처 세부 정보는 보안상 표시하지 않았습니다.")
        elif limitation:
            notice_items.append(limitation)
    return dedupe_strings(notice_items)


def _shows_elevator_status(result: AccessibilityResult) -> bool:
    if result.selected_route is None:
        return False
    if not result.accessibility_checks:
        return True
    return any(
        check.elevator_details
        or check.station_has_elevator == AccessibilityEvidenceStatus.CONFIRMED
        for check in result.accessibility_checks
    )


def _is_coverage_limitation(value: str) -> bool:
    return any(
        marker in value for marker in ("검증된 역·호선", "역 코드", "지원 범위", "제공 범위")
    )


def _is_facility_coverage_limitation(value: str) -> bool:
    return any(marker in value for marker in ("접근성 시설 데이터", "접근성 데이터의 지원 범위"))


def _has_restroom_evidence(result: AccessibilityResult) -> bool:
    return any(source.source_name == "restroom" for source in result.evidence_sources)


def _source_group_status(
    result: AccessibilityResult,
    source_names: set[str],
) -> str:
    sources = [
        source
        for source in result.evidence_sources
        if source.source_name in source_names
    ]
    if not sources:
        return "미확인"

    unsupported_sources = [
        source
        for source in sources
        if source.coverage_status == SourceCoverageStatus.UNSUPPORTED
    ]
    if len(unsupported_sources) == len(sources):
        return _UNSUPPORTED_GROUP_STATUS
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
        return suffix
    return "확인 실패"


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
