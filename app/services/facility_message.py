from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from app.engine.elevator_status import summarize_elevator_status
from app.normalizers.facility_identity import facility_display_identity
from app.schemas.accessibility import (
    FacilityAnswerState,
    FacilityQuestionItem,
    FacilityQuestionResult,
)
from app.schemas.common import ResponseStatus, SourceCoverageStatus
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType

MAX_MESSAGE_FACILITIES = 5


def build_facility_user_message(result: FacilityQuestionResult) -> str:
    return "\n\n".join(
        [
            f"**확인 결과: {_overall_result_label(result)}**\n{_headline(result)}",
            "### 역·호선\n"
            f"- {_station_label(result.station_name, result.line)}",
            _facility_table(result),
            "### 기준 시각\n" + "\n".join(_checked_at_lines(result)),
            _facility_notice_section(result),
        ]
    )


def _facility_table(result: FacilityQuestionResult) -> str:
    lines = [
        "### 시설 정보",
        "",
        "| 시설 | 위치 | 상태 |",
        "|---|---|---|",
    ]
    displayed = 0
    display_facilities = {
        id(item): _display_facilities(item)
        for item in result.items
    }
    total = sum(len(facilities) for facilities in display_facilities.values())
    for item in result.items:
        label = _facility_type_label(item.facility_type)
        facilities = display_facilities[id(item)]
        if not facilities:
            location, status = _empty_facility_table_values(item)
            lines.append(
                f"| {_markdown_table_cell(label)} | "
                f"{_markdown_table_cell(location)} | {_markdown_table_cell(status)} |"
            )
            continue
        for facility in facilities:
            if displayed >= MAX_MESSAGE_FACILITIES:
                break
            location = facility.location_description or "위치 세부정보 미확인"
            lines.append(
                f"| {_markdown_table_cell(label)} | "
                f"{_markdown_table_cell(location)} | "
                f"{_markdown_table_cell(_display_status(item, facility))} |"
            )
            displayed += 1
    remaining = total - displayed
    if remaining > 0:
        lines.extend(
            [
                "",
                f"- 그 외 {remaining}건은 구조화된 시설 목록에 포함되어 있습니다.",
            ]
        )
    if result.status == ResponseStatus.PARTIAL:
        lines.extend(
            [
                "",
                "- 일부 데이터 출처가 확인되지 않아 안내가 제한적입니다.",
            ]
        )
    return "\n".join(lines)


def _empty_facility_table_values(item: FacilityQuestionItem) -> tuple[str, str]:
    if item.answer_state == FacilityAnswerState.NOT_FOUND:
        return (
            "현재 공공데이터에서 시설을 확인하지 못했습니다",
            "공공데이터 미확인",
        )
    if item.answer_state == FacilityAnswerState.UNKNOWN:
        return "공공데이터 조회 실패로 위치를 확인하지 못했습니다", "확인 불가"
    if item.answer_state == FacilityAnswerState.UNSUPPORTED:
        return "현재 연결된 공공데이터의 제공 범위 밖입니다", "데이터 소스 미지원"
    return "위치 미확인", _facility_answer_state_label(item.answer_state)


def _facility_notice_section(result: FacilityQuestionResult) -> str:
    notices = [line.removeprefix("- ") for line in _notice_lines(result)]
    if not notices:
        return ""
    lines = ["### 주의사항", "", f"> {notices[0]}"]
    lines.extend(f"- {notice}" for notice in notices[1:])
    return "\n".join(lines)


def _facility_answer_state_label(state: FacilityAnswerState) -> str:
    return {
        FacilityAnswerState.AVAILABLE: "이용 가능",
        FacilityAnswerState.MIXED: "상태 혼합",
        FacilityAnswerState.MAINTENANCE: "점검 중",
        FacilityAnswerState.UNAVAILABLE: "이용 불가",
        FacilityAnswerState.NOT_FOUND: "공공데이터 미확인",
        FacilityAnswerState.UNSUPPORTED: "데이터 소스 미지원",
        FacilityAnswerState.UNKNOWN: "확인 불가",
    }[state]


def _markdown_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _overall_result_label(result: FacilityQuestionResult) -> str:
    states = {item.answer_state for item in result.items}
    if result.status == ResponseStatus.FAILED or not states:
        return "확인 불가"
    if FacilityAnswerState.UNKNOWN in states:
        return "일부 정보 확인 불가" if len(states) > 1 else "확인 불가"
    if states == {FacilityAnswerState.UNSUPPORTED}:
        return "데이터 소스 미지원"
    if FacilityAnswerState.UNSUPPORTED in states:
        return "일부 데이터 소스 미지원"
    if states.intersection(
        {
            FacilityAnswerState.MIXED,
            FacilityAnswerState.MAINTENANCE,
            FacilityAnswerState.UNAVAILABLE,
        }
    ):
        return "주의 필요"
    if states == {FacilityAnswerState.NOT_FOUND}:
        return "공공데이터 미확인"
    if FacilityAnswerState.NOT_FOUND in states:
        return "일부 정보 미확인"
    return "정보 확인"


def _headline(result: FacilityQuestionResult) -> str:
    station = _station_label(result.station_name, result.line)
    if result.status == ResponseStatus.FAILED:
        return f"{station} 시설 정보를 현재 공공데이터로 확인하지 못했습니다."
    if any(item.answer_state == FacilityAnswerState.UNSUPPORTED for item in result.items):
        return (
            f"{station}은 현재 연결된 시설 공공데이터의 제공 범위 밖입니다. "
            "시설이 없다는 뜻은 아닙니다."
        )
    if any(item.answer_state == FacilityAnswerState.NOT_FOUND for item in result.items):
        return f"{station}에서 요청한 시설 일부가 현재 공공데이터에 확인되지 않았습니다."
    if any(item.answer_state == FacilityAnswerState.UNKNOWN for item in result.items):
        return (
            f"{station}의 시설 위치 정보는 확인됐지만 현재 운행 또는 이용 상태는 "
            "확인하지 못했습니다."
        )
    if any(item.answer_state == FacilityAnswerState.MIXED for item in result.items):
        return (
            f"{station}에는 이용 가능한 시설과 점검 또는 이용 불가 시설이 함께 "
            "확인됩니다. 아래 위치별 상태를 확인하세요."
        )
    if any(
        item.answer_state
        in {FacilityAnswerState.MAINTENANCE, FacilityAnswerState.UNAVAILABLE}
        for item in result.items
    ):
        return f"{station} 시설 중 점검 또는 이용 상태를 주의해서 확인해야 할 항목이 있습니다."
    return f"{station}의 요청한 시설 정보를 확인했습니다."


def _location_lines(items: list[FacilityQuestionItem]) -> list[str]:
    lines: list[str] = []
    displayed = 0
    total = sum(len(item.facilities) for item in items)
    for item in items:
        label = _facility_type_label(item.facility_type)
        if not item.facilities:
            if item.answer_state == FacilityAnswerState.NOT_FOUND:
                lines.append(f"- {label}: 현재 공공데이터에서 위치가 확인되지 않았습니다.")
            elif item.answer_state == FacilityAnswerState.UNSUPPORTED:
                lines.append(f"- {label}: 현재 연결된 데이터 소스의 제공 범위 밖입니다.")
            else:
                lines.append(f"- {label}: 위치 정보를 확인하지 못했습니다.")
            continue
        for facility in item.facilities:
            if displayed >= MAX_MESSAGE_FACILITIES:
                break
            location = facility.location_description or "위치 세부정보 미확인"
            lines.append(f"- {label}: {location}.")
            displayed += 1
    remaining = total - displayed
    if remaining > 0:
        lines.append(f"- 그 외 {remaining}건은 구조화된 시설 목록에 포함되어 있습니다.")
    return lines or ["- 요청한 시설 위치를 확인하지 못했습니다."]


def _status_lines(result: FacilityQuestionResult) -> list[str]:
    lines: list[str] = []
    for item in result.items:
        label = _facility_type_label(item.facility_type)
        if item.answer_state == FacilityAnswerState.NOT_FOUND:
            lines.append(
                f"- {label}: 조회는 완료됐지만 현재 공공데이터에서 시설을 확인하지 못했습니다."
            )
            continue
        if item.answer_state == FacilityAnswerState.UNSUPPORTED:
            lines.append(f"- {label}: 현재 연결된 데이터 소스의 제공 범위 밖입니다.")
            continue
        if item.answer_state == FacilityAnswerState.UNKNOWN and not item.facilities:
            lines.append(f"- {label}: 공공데이터 조회 실패로 상태를 확인하지 못했습니다.")
            continue
        status_facilities = item.facilities
        if item.facility_type == FacilityType.ELEVATOR:
            status_facilities = list(
                summarize_elevator_status(item.facilities).operational_facilities
            )
        counts = Counter(facility.status for facility in status_facilities)
        details = [
            f"{_facility_status_label(status)} {count}건"
            for status, count in (
                (FacilityStatus.AVAILABLE, counts[FacilityStatus.AVAILABLE]),
                (FacilityStatus.MAINTENANCE, counts[FacilityStatus.MAINTENANCE]),
                (FacilityStatus.UNAVAILABLE, counts[FacilityStatus.UNAVAILABLE]),
                (FacilityStatus.UNKNOWN, counts[FacilityStatus.UNKNOWN]),
            )
            if count
        ]
        lines.append(f"- {label}: {' / '.join(details) or '상태 미확인' }.")
    if result.status == ResponseStatus.PARTIAL:
        lines.append("- 일부 데이터 출처가 확인되지 않아 안내가 제한적입니다.")
    return lines or ["- 요청한 시설 상태를 확인하지 못했습니다."]


def _display_facilities(item: FacilityQuestionItem) -> list[AccessibleFacility]:
    facilities = list(item.facilities)
    if item.facility_type != FacilityType.ELEVATOR:
        return _dedupe_display_rows(facilities)

    operational = [
        facility
        for facility in facilities
        if facility.source_name in {None, "elevator_status"}
    ]
    reference = [facility for facility in facilities if facility not in operational]
    displayed = _dedupe_display_rows(operational)
    operational_keys = {
        identity
        for facility in operational
        if (identity := facility_display_identity(facility)) is not None
    }
    for facility in _dedupe_display_rows(reference):
        identity = facility_display_identity(facility)
        if identity is not None and identity in operational_keys:
            continue
        displayed.append(facility)
    return displayed


def _display_status(
    item: FacilityQuestionItem,
    facility: AccessibleFacility,
) -> str:
    if (
        item.facility_type == FacilityType.ELEVATOR
        and facility.source_name not in {None, "elevator_status"}
    ):
        return "운행 상태 미확인"
    return _facility_status_label(facility.status)


def _dedupe_display_rows(
    facilities: list[AccessibleFacility],
) -> list[AccessibleFacility]:
    seen: set[tuple[object, ...]] = set()
    deduped: list[AccessibleFacility] = []
    for facility in facilities:
        identity = facility_display_identity(facility)
        if identity is None:
            deduped.append(facility)
            continue
        key = (*identity, facility.status)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(facility)
    return deduped


def _checked_at_lines(result: FacilityQuestionResult) -> list[str]:
    lines = [
        "- 전체 조회 시각: "
        + (_format_checked_at(result.last_checked_at) or "확인된 기준 시각 없음")
        + "."
    ]
    grouped: dict[str, list] = {}
    for source in result.evidence_sources:
        grouped.setdefault(_source_label(source.source_name), []).append(source)
    for label, sources in grouped.items():
        if all(
            source.coverage_status == SourceCoverageStatus.UNSUPPORTED
            for source in sources
        ):
            lines.append(f"- {label}: 데이터 제공 범위 밖.")
            continue
        successful = [source for source in sources if source.success]
        checked_at = max(
            (source.checked_at for source in successful if source.checked_at is not None),
            default=None,
        )
        if checked_at is not None:
            lines.append(f"- {label}: {_format_time_only(checked_at)} 확인.")
        elif any(not source.success for source in sources):
            lines.append(f"- {label}: 확인 실패.")
        else:
            lines.append(f"- {label}: 기준 시각 미확인.")
    return lines


def _notice_lines(result: FacilityQuestionResult) -> list[str]:
    notices = [
        result.safety_notice,
        "공공 API 기준 정보이므로 현장 상황과 다를 수 있습니다.",
    ]
    if result.status in {ResponseStatus.PARTIAL, ResponseStatus.FAILED}:
        notices.append("일부 데이터가 확인되지 않아 역무실 또는 현장 안내를 함께 확인하세요.")
    notices.extend(result.limitations)
    return [f"- {notice}" for notice in _dedupe(notices) if notice]


def _station_label(station_name: str, line: str | None) -> str:
    station = station_name if station_name.endswith("역") else f"{station_name}역"
    return f"{line}호선 {station}" if line else station


def _facility_type_label(facility_type: FacilityType) -> str:
    if facility_type == FacilityType.ELEVATOR:
        return "엘리베이터"
    if facility_type == FacilityType.ACCESSIBLE_RESTROOM:
        return "장애인화장실"
    return "접근성 시설"


def _facility_status_label(status: FacilityStatus) -> str:
    if status == FacilityStatus.AVAILABLE:
        return "이용 가능"
    if status == FacilityStatus.MAINTENANCE:
        return "점검 중"
    if status == FacilityStatus.UNAVAILABLE:
        return "이용 불가"
    return "상태 미확인"


def _source_label(source_name: str) -> str:
    return {
        "elevator_status": "엘리베이터 운행상태",
        "elevator_info": "엘리베이터 위치 정보",
        "facility_info": "편의시설 정보",
        "restroom": "장애인화장실 정보",
    }.get(source_name, "시설 정보")


def _format_checked_at(value: datetime | None) -> str | None:
    if value is None:
        return None
    local = value.astimezone(timezone(timedelta(hours=9), "KST"))
    return (
        f"{local.year}년 {local.month}월 {local.day}일 "
        f"{local.hour:02d}:{local.minute:02d}"
    )


def _format_time_only(value: datetime) -> str:
    local = value.astimezone(timezone(timedelta(hours=9), "KST"))
    return f"{local.hour:02d}:{local.minute:02d}"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
