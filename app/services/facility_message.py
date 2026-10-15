from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.normalizers.facility_identity import facility_display_identity
from app.normalizers.helpers import label_platform_position, tidy_location_text
from app.schemas.accessibility import (
    DEFAULT_SAFETY_NOTICE,
    FacilityAnswerState,
    FacilityQuestionItem,
    FacilityQuestionResult,
)
from app.schemas.common import ResponseStatus, SourceCoverageStatus
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType

# 시설 질문은 역의 시설 목록이 곧 답이라 표에 거의 다 싣는다.
# 이 수는 비정상적으로 긴 목록만 자른다.
MAX_MESSAGE_FACILITIES = 20
FACILITY_DATA_NOTICE = "공공데이터 기준이라 현장 상황과 다를 수 있습니다."
# 경로 답변의 기준 시각과 같은 기준이다.
_SAME_LOOKUP_WINDOW = timedelta(minutes=5)
_GATE_MARKERS = ("개찰", "개집표", "게이트")


def facility_safety_notice(facility_types: list[FacilityType]) -> str:
    # 엘리베이터를 묻지 않은 답변에 엘리베이터 운행 안내를 붙이지 않는다.
    if FacilityType.ELEVATOR in facility_types:
        return DEFAULT_SAFETY_NOTICE
    return FACILITY_DATA_NOTICE


def build_facility_user_message(result: FacilityQuestionResult) -> str:
    return _compose(result, *_title(result))


def build_facility_alternative_user_message(result: FacilityQuestionResult) -> str:
    """"고장났는데 대안 있어?"처럼 대신 쓸 시설을 묻는 답. 표는 시설 답변과 같다."""
    return _compose(result, *_alternative_title(result))


def _compose(result: FacilityQuestionResult, title: str, detail: str | None) -> str:
    lead = f"**{title}**" + (f"\n{detail}" if detail else "")
    return "\n\n".join(
        part
        for part in [
            lead,
            _facility_table(result),
            "### 기준 시각\n\n" + "\n".join(_checked_at_lines(result)),
            _facility_notice_section(result),
        ]
        if part
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
            lines.append(
                f"| {_markdown_table_cell(label)} | "
                f"{_markdown_table_cell(_display_location(facility))} | "
                f"{_markdown_table_cell(_display_status(item, facility))} |"
            )
            displayed += 1
    remaining = total - displayed
    if remaining > 0:
        lines.extend(["", f"- 그 외 {remaining}건은 표에서 생략했습니다."])
    return "\n".join(lines)


def _display_location(facility: AccessibleFacility) -> str:
    location = label_platform_position(
        tidy_location_text(facility.location_description or "위치 세부정보 미확인")
    )
    if facility.inside_gate is not None and not any(marker in location for marker in _GATE_MARKERS):
        location += " (개찰구 안)" if facility.inside_gate else " (개찰구 밖)"
    if facility.open_time:
        location += f" · 운영 {facility.open_time}"
    return location


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


def _title(result: FacilityQuestionResult) -> tuple[str, str | None]:
    # 제목은 묻는 말에 대한 답이다. 상태가 다른 시설을 함께 물었으면 먼저 알아야 할 상태로
    # 쓰고, 나머지 시설은 표가 보여 준다.
    station = _station_label(result.station_name, result.line)
    items = result.items
    if result.status == ResponseStatus.FAILED or not items:
        return f"{station} 시설 정보를 지금 확인하지 못했습니다.", None

    def having(*states: FacilityAnswerState) -> list[FacilityQuestionItem]:
        return [item for item in items if item.answer_state in states]

    if mixed := having(FacilityAnswerState.MIXED):
        return (
            f"{station} {_labels(mixed)} 중 점검 중이거나 이용할 수 없는 곳이 있습니다.",
            None,
        )
    if maintenance := having(FacilityAnswerState.MAINTENANCE):
        return f"{station} {_with_topic(_labels(maintenance))} 점검 중입니다.", None
    if unavailable := having(FacilityAnswerState.UNAVAILABLE):
        return f"{station} {_with_topic(_labels(unavailable))} 지금 이용할 수 없습니다.", None
    if unknown := [item for item in having(FacilityAnswerState.UNKNOWN) if not item.facilities]:
        return f"{station} {_labels(unknown)} 정보를 지금 확인하지 못했습니다.", None
    if unsupported := having(FacilityAnswerState.UNSUPPORTED):
        return (
            f"{station} {_labels(unsupported)} 정보는 현재 공공데이터 제공 범위 밖입니다.",
            "시설이 없다는 뜻은 아닙니다.",
        )
    if not_found := having(FacilityAnswerState.NOT_FOUND):
        return (
            f"{station} {_with_topic(_labels(not_found))} 현재 공공데이터에서 확인되지 않습니다.",
            None,
        )
    if unknown := having(FacilityAnswerState.UNKNOWN):
        state = "운행" if unknown[0].facility_type == FacilityType.ELEVATOR else "이용"
        return (
            f"{station} {_labels(unknown)} 위치는 확인했지만 지금 {state} 상태는 "
            "확인하지 못했습니다.",
            None,
        )
    if [item.facility_type for item in items] == [FacilityType.ELEVATOR]:
        # 운행 상태 출처에 없는 엘리베이터는 표에 "운행 상태 미확인"으로 남으니
        # "모두 운행 중"이라고만 하지 않는다.
        if any(
            _display_status(items[0], facility) == "운행 상태 미확인"
            for facility in _display_facilities(items[0])
        ):
            return f"{station}에서 운행 상태가 확인된 엘리베이터는 모두 운행 중입니다.", None
        return f"{station} 엘리베이터는 모두 운행 중입니다.", None
    return f"{station} {_with_object(_labels(items))} 이용할 수 있습니다.", None


def _alternative_title(result: FacilityQuestionResult) -> tuple[str, str | None]:
    station = _station_label(result.station_name, result.line)
    if result.status == ResponseStatus.FAILED or not result.items:
        return f"{station} 시설 정보를 지금 확인하지 못했습니다.", None
    rows = [
        (item, facility) for item in result.items for facility in _display_facilities(item)
    ]
    label = _labels(result.items)
    blocked = {
        facility.status
        for _, facility in rows
        if facility.status in {FacilityStatus.MAINTENANCE, FacilityStatus.UNAVAILABLE}
    }
    # 운행 상태 출처에 없거나 위치를 모르는 시설은 대신 쓸 수 있다고 하지 않는다.
    available = any(
        _display_status(item, facility) == "이용 가능" and facility.location_description
        for item, facility in rows
    )
    if blocked and available:
        state = "점검 중인" if blocked == {FacilityStatus.MAINTENANCE} else "이용할 수 없는"
        return (
            f"{station} {label} 중 {state} 곳이 있지만, 운행 중인 다른 "
            f"{_with_subject(label)} 있습니다.",
            None,
        )
    if available:
        return f"{station}에서 고장이나 점검으로 확인된 {_with_topic(label)} 없습니다.", None
    if blocked:
        state = "점검 중이고" if blocked == {FacilityStatus.MAINTENANCE} else "이용할 수 없고"
        return (
            f"{station} {_with_topic(label)} {state}, 운행이 확인된 다른 "
            f"{_with_topic(label)} 없습니다.",
            "이동 전 역무실에 이동 지원을 문의하세요.",
        )
    return (
        f"{station}에서 운행과 위치가 모두 확인된 {_with_object(label)} 찾지 못했습니다.",
        "이동 전 역무실에 이동 지원을 문의하세요.",
    )


def _labels(items: list[FacilityQuestionItem]) -> str:
    labels = list(dict.fromkeys(_facility_type_label(item.facility_type) for item in items))
    if len(labels) == 2:
        first, second = labels
        return f"{first}{'과' if _has_final_consonant(first) else '와'} {second}"
    return ", ".join(labels)


def _has_final_consonant(text: str) -> bool:
    last = text[-1]
    return "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0


def _with_topic(text: str) -> str:
    return text + ("은" if _has_final_consonant(text) else "는")


def _with_subject(text: str) -> str:
    return text + ("이" if _has_final_consonant(text) else "가")


def _with_object(text: str) -> str:
    return text + ("을" if _has_final_consonant(text) else "를")


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
    # 출처를 차례로 부르거나 캐시를 써서 생기는 몇 분 차이는 사용자에게 의미가 없다. 실패·제공
    # 범위 밖 출처가 없고 시각이 몇 분 안에 모이면 조회 시각 한 줄만 쓴다(답변 계약 4).
    grouped: dict[str, list] = {}
    for source in result.evidence_sources:
        grouped.setdefault(_source_label(source.source_name), []).append(source)
    source_lines: list[str] = []
    times: list[datetime] = []
    plain = True
    for label, sources in grouped.items():
        if all(
            source.coverage_status == SourceCoverageStatus.UNSUPPORTED
            for source in sources
        ):
            source_lines.append(f"- {label}: 데이터 제공 범위 밖.")
            plain = False
            continue
        successful = [source for source in sources if source.success]
        checked_at = max(
            (source.checked_at for source in successful if source.checked_at is not None),
            default=None,
        )
        if checked_at is not None:
            # 엘리베이터 위치는 자주 바뀌지 않아 캐시 시각이 운행상태보다 이르더라도 따로 밝히지
            # 않는다. 경로 답변도 위치와 운행상태를 한 시각으로 묶는다.
            if any(source.source_name != "elevator_info" for source in successful):
                times.append(checked_at)
            source_lines.append(f"- {label}: {_format_time_only(checked_at)} 확인.")
        elif any(not source.success for source in sources):
            source_lines.append(f"- {label}: 확인 실패.")
            plain = False
        else:
            source_lines.append(f"- {label}: 기준 시각 미확인.")
            plain = False
    checked_at_text = _format_checked_at(result.last_checked_at) or "확인된 기준 시각 없음"
    if plain and (not times or max(times) - min(times) <= _SAME_LOOKUP_WINDOW):
        return [f"- 조회 시각: {checked_at_text}."]
    return [f"- 전체 조회 시각: {checked_at_text}.", *source_lines]


def _notice_lines(result: FacilityQuestionResult) -> list[str]:
    notices = [result.safety_notice, FACILITY_DATA_NOTICE]
    # 제공 범위 밖은 제목이 이미 밝힌다. 조회에 실패한 출처가 있을 때만 현장 확인을 덧붙인다.
    if result.failed_sources or result.status == ResponseStatus.FAILED:
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
