from __future__ import annotations

from app.normalizers.helpers import (
    is_platform_position,
    label_platform_position,
    tidy_location_text,
)
from app.schemas.accessibility import (
    RESTROOM_SOURCE_UNSUPPORTED_NOTE,
    AccessibilityCheck,
    AccessibilityEvidenceStatus,
    AccessibilityResult,
    ElevatorEvidenceItem,
    FacilityAnswerState,
)
from app.schemas.common import ResponseStatus
from app.schemas.facility import AccessibleFacility, FacilityStatus
from app.schemas.route import RouteCandidate

MAX_VISIBLE_ELEVATOR_DETAILS = 3


def build_accessibility_table(result: AccessibilityResult) -> str:
    lines = [
        "### 역별 확인 결과",
        "",
        "| 역 | 확인된 정보 | 추가 확인 |",
        "|---|---|---|",
    ]
    for check in result.accessibility_checks:
        confirmed, attention = _accessibility_table_details(check)
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_table_cell(_accessibility_station_label(check)),
                    _markdown_table_items(confirmed, fallback="확인된 항목 없음"),
                    _markdown_table_items(
                        attention,
                        fallback="추가 확인 항목 없음",
                    ),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _accessibility_table_details(
    check: AccessibilityCheck,
) -> tuple[list[str], list[str]]:
    confirmed: list[str] = []
    attention: list[str] = []

    if check.elevator_details:
        detail_confirmed, detail_attention = _elevator_detail_table_values(check)
        confirmed.extend(detail_confirmed)
        attention.extend(detail_attention)
    elif check.elevator_answer_state == FacilityAnswerState.UNSUPPORTED:
        attention.append("엘리베이터 정보: 현재 데이터 제공 범위 밖")
    elif check.elevator_answer_state == FacilityAnswerState.NOT_FOUND:
        attention.append("공공데이터 조회 결과 엘리베이터 미확인")
    elif (
        check.elevator_answer_state in {None, FacilityAnswerState.UNKNOWN}
        and check.station_has_elevator != AccessibilityEvidenceStatus.CONFIRMED
    ):
        attention.append("엘리베이터 정보 확인 불가")
    elif check.station_has_elevator == AccessibilityEvidenceStatus.CONFIRMED:
        if check.elevator_location:
            confirmed.append(check.elevator_location)
        else:
            confirmed.append("엘리베이터 있음")
    elif check.station_has_elevator == AccessibilityEvidenceStatus.FAILED:
        attention.append("엘리베이터 정보 확인 실패")
    else:
        attention.append("엘리베이터 위치 미확인")

    if (
        not check.elevator_details
        and check.station_has_elevator != AccessibilityEvidenceStatus.CONFIRMED
    ):
        _append_restroom_table_values(check, confirmed, attention)
        attention.extend(_table_notes(check))
        return dedupe_strings(confirmed), dedupe_strings(attention)

    if check.line is not None and check.line_matched_elevator in {
        AccessibilityEvidenceStatus.FAILED,
        AccessibilityEvidenceStatus.UNVERIFIED,
    }:
        attention.append(f"{check.line}호선용 엘리베이터인지 확인 필요")

    if check.elevator_details:
        pass
    elif check.elevator_answer_state == FacilityAnswerState.MIXED:
        attention.append("운행상태: 일부 이용 가능, 일부 점검 또는 이용 불가")
    elif check.status_verified == AccessibilityEvidenceStatus.CONFIRMED:
        if check.elevator_status == FacilityStatus.AVAILABLE:
            confirmed.append("현재 운행 중")
        elif check.elevator_status == FacilityStatus.MAINTENANCE:
            attention.append("엘리베이터 점검 중")
        elif check.elevator_status == FacilityStatus.UNAVAILABLE:
            attention.append("엘리베이터 운행하지 않음")
        else:
            attention.append("엘리베이터 운행 상태 확인 필요")
    elif check.status_verified == AccessibilityEvidenceStatus.FAILED:
        attention.append("엘리베이터 운행 상태 확인 필요")
    else:
        attention.append("엘리베이터 운행 상태 확인 필요")

    has_platform_location = _has_platform_concourse_location(check)
    if has_platform_location:
        if check.platform_to_concourse_verified in {
            AccessibilityEvidenceStatus.FAILED,
            AccessibilityEvidenceStatus.UNVERIFIED,
        }:
            attention.append("표시된 엘리베이터가 실제 이용 승강장과 맞는지 확인 필요")
    else:
        # 승강장 엘리베이터가 표에 보이면 엘리베이터가 없다는 뜻으로 읽히지 않게, 확인하지 못한 것이
        # 그 엘리베이터와 대합실의 연결이라고 쓴다.
        _append_path_evidence(
            confirmed,
            attention,
            "승강장 엘리베이터의 대합실" if has_platform_elevator(check) else "승강장→대합실",
            check.platform_to_concourse_verified,
        )
    _append_path_evidence(
        confirmed,
        attention,
        "환승 구간",
        check.transfer_path_elevator_verified,
    )
    _append_path_evidence(
        confirmed,
        attention,
        "출구까지",
        check.exit_elevator_verified,
    )

    _append_restroom_table_values(check, confirmed, attention)

    attention.extend(_table_notes(check))
    return dedupe_strings(confirmed), dedupe_strings(attention)


def _append_restroom_table_values(
    check: AccessibilityCheck,
    confirmed: list[str],
    attention: list[str],
) -> None:
    if check.restroom_available is True:
        if check.restroom_required is True:
            confirmed.append("장애인화장실 확인(필수)")
        elif check.restroom_required is False:
            confirmed.append("장애인화장실 확인(참고)")
        else:
            confirmed.append("장애인화장실 확인")
    elif check.restroom_available is False and restroom_source_unsupported(check):
        # "미확인"과 "제공 범위 밖" 메모를 한 칸에 겹쳐 쓰지 않고 엘리베이터 칸과 같은 꼴로 쓴다.
        attention.append(f"장애인화장실 정보: 현재 데이터 제공 범위 밖{_restroom_need(check)}")
    elif check.restroom_available is False and check.restroom_required is True:
        attention.append("장애인화장실 미확인(필수)")
    elif check.restroom_available is False and check.restroom_required is False:
        attention.append("장애인화장실 미확인(참고)")


def restroom_source_unsupported(check: AccessibilityCheck) -> bool:
    return RESTROOM_SOURCE_UNSUPPORTED_NOTE in check.notes


def _restroom_need(check: AccessibilityCheck) -> str:
    if check.restroom_required is True:
        return "(필수)"
    if check.restroom_required is False:
        return "(참고)"
    return ""


def _elevator_detail_table_values(
    check: AccessibilityCheck,
) -> tuple[list[str], list[str]]:
    selected = _select_elevator_details(
        check.elevator_details,
        mixed=check.elevator_answer_state == FacilityAnswerState.MIXED,
    )
    confirmed: list[str] = []
    attention: list[str] = []
    for detail in selected:
        location = _elevator_detail_location(detail)
        if (
            detail.status == FacilityStatus.AVAILABLE
            and detail.status_verified == AccessibilityEvidenceStatus.CONFIRMED
        ):
            confirmed.append(f"운행 중: {location}")
        elif detail.status == FacilityStatus.MAINTENANCE:
            attention.append(f"점검 중: {location}")
        elif detail.status == FacilityStatus.UNAVAILABLE:
            attention.append(f"이용 불가: {location}")
        else:
            attention.append(f"운행 상태 미확인: {location}")

    remaining = len(check.elevator_details) - len(selected)
    if remaining > 0:
        # 무엇을 물으면 나머지를 볼 수 있는지 그대로 쓸 수 있는 질문으로 알려 준다.
        station = station_label(check.station)
        query = f"{check.line}호선 {station}" if check.line else station
        attention.append(f"그 외 엘리베이터 {remaining}건은 '{query} 엘리베이터' 질문으로 확인")
    return confirmed, attention


def _table_notes(check: AccessibilityCheck) -> list[str]:
    # 엘리베이터 유무·운행 상태·연결 구간은 표가 항목으로 직접 보여 준다. 같은 내용을 담은 판단 메모
    # ("엘리베이터 정보를 찾지 못했습니다" 등)는 같은 칸에서 반복하지 않고 나머지 메모만 붙인다.
    return [
        note
        for note in check.notes
        if "엘리베이터" not in note and note != RESTROOM_SOURCE_UNSUPPORTED_NOTE
    ][:2]


def _select_elevator_details(
    details: list[ElevatorEvidenceItem],
    *,
    mixed: bool,
) -> list[ElevatorEvidenceItem]:
    if len(details) <= MAX_VISIBLE_ELEVATOR_DETAILS:
        return details

    restricted = [
        detail
        for detail in details
        if detail.status in {FacilityStatus.MAINTENANCE, FacilityStatus.UNAVAILABLE}
    ]
    available = [
        detail for detail in details if detail.status == FacilityStatus.AVAILABLE
    ]
    unknown = [
        detail
        for detail in details
        if detail.status == FacilityStatus.UNKNOWN
        or detail.status_verified != AccessibilityEvidenceStatus.CONFIRMED
    ]
    ordered = [*restricted, *unknown, *available]
    selected: list[ElevatorEvidenceItem] = []
    if mixed and restricted and available:
        selected.extend([restricted[0], available[0]])
    # 출입구 엘리베이터만 여러 대 보여 주고 승강장 쪽 엘리베이터를 "그 외"로 숨기지 않도록,
    # 역 안쪽과 출입구 쪽을 한 대씩 먼저 고른 뒤 남은 자리를 채운다.
    for is_exit in (False, True):
        if any(_is_exit_elevator(detail) is is_exit for detail in selected):
            continue
        candidate = next(
            (detail for detail in ordered if _is_exit_elevator(detail) is is_exit),
            None,
        )
        if candidate is not None and len(selected) < MAX_VISIBLE_ELEVATOR_DETAILS:
            selected.append(candidate)
    for detail in ordered:
        if len(selected) >= MAX_VISIBLE_ELEVATOR_DETAILS:
            break
        if detail not in selected:
            selected.append(detail)
    return sorted(selected, key=ordered.index)


def _is_exit_elevator(detail: ElevatorEvidenceItem) -> bool:
    text = " ".join(part for part in (detail.location, detail.facility_name) if part)
    return any(marker in text for marker in ("출구", "출입구", "외부"))


def is_platform_elevator(detail: ElevatorEvidenceItem) -> bool:
    return is_platform_position(detail.location)


def has_platform_elevator(check: AccessibilityCheck) -> bool:
    return any(is_platform_elevator(detail) for detail in check.elevator_details)


def _elevator_detail_location(detail: ElevatorEvidenceItem) -> str:
    location = label_platform_position(tidy_location_text(detail.location or "위치 미확인"))
    if detail.operation_section and detail.operation_section not in location:
        return f"{location} ({detail.operation_section})"
    return location


def _has_platform_concourse_location(check: AccessibilityCheck) -> bool:
    values = [
        check.elevator_location or "",
        *[
            " ".join(
                part
                for part in (detail.location, detail.operation_section)
                if part
            )
            for detail in check.elevator_details
        ],
    ]
    return any("승강장" in value and "대합실" in value for value in values)


def _append_path_evidence(
    confirmed: list[str],
    attention: list[str],
    label: str,
    status: AccessibilityEvidenceStatus,
) -> None:
    if status == AccessibilityEvidenceStatus.CONFIRMED:
        confirmed.append(f"{label} 연결 확인")
    elif status == AccessibilityEvidenceStatus.UNVERIFIED:
        # 시설 설명에 연결 구간이 없을 뿐 조회는 됐다. 운행 중인 엘리베이터와 나란히 보여도 모순처럼
        # 읽히지 않게 "정보 없음"으로 쓴다.
        attention.append(f"{label} 연결 정보 없음")
    elif status == AccessibilityEvidenceStatus.FAILED:
        attention.append(f"{label} 연결 확인 필요")


def elevator_location_label(check: AccessibilityCheck) -> str:
    station = station_label(check.station)
    if check.elevator_location:
        return f"{station} {check.elevator_location}"
    return station


def detail_location_labels(
    check: AccessibilityCheck,
    statuses: set[FacilityStatus],
) -> list[str]:
    station = station_label(check.station)
    labels = [
        f"{station} {detail.location or '위치 미확인'}"
        for detail in check.elevator_details
        if detail.status in statuses
        and detail.status_verified == AccessibilityEvidenceStatus.CONFIRMED
    ]
    return dedupe_strings(labels)


def restricted_elevator_location_labels(
    checks: list[AccessibilityCheck],
) -> list[str]:
    labels: list[str] = []
    for check in checks:
        detail_labels = detail_location_labels(
            check,
            {FacilityStatus.MAINTENANCE, FacilityStatus.UNAVAILABLE},
        )
        if detail_labels:
            labels.extend(detail_labels)
        elif check.elevator_answer_state == FacilityAnswerState.MIXED or (
            check.elevator_status
            in {FacilityStatus.MAINTENANCE, FacilityStatus.UNAVAILABLE}
        ):
            labels.append(station_label(check.station))
    return dedupe_strings(labels)


def _accessibility_station_label(check: AccessibilityCheck) -> str:
    line = f"{check.line}호선 " if check.line else ""
    return f"{_role_label(check.role)}: {line}{station_label(check.station)}"


def _markdown_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _markdown_table_items(items: list[str], *, fallback: str) -> str:
    visible_items = [_markdown_table_cell(item) for item in items if item.strip()]
    if not visible_items:
        return _markdown_table_cell(fallback)
    return "<br>".join(f"• {item}" for item in visible_items)


def accessibility_check_points(result: AccessibilityResult) -> list[str]:
    points: list[str] = []
    for check in result.accessibility_checks:
        parts = [f"{_role_label(check.role)} {check.station}: "]
        details = _elevator_evidence_details(check)
        if check.restroom_available is True:
            restroom_detail = "장애인화장실 있음"
            if check.restroom_required is True:
                restroom_detail += "(필수)"
            elif check.restroom_required is False:
                restroom_detail += "(참고)"
            details.append(restroom_detail)
        elif check.restroom_available is False:
            if check.restroom_required is True:
                details.append("장애인화장실 미확인(필수)")
            elif check.restroom_required is False:
                details.append("장애인화장실 미확인(참고)")
            else:
                details.append("장애인화장실 미확인")
        parts.append(" / ".join(details))
        if check.notes:
            parts.append(" - " + "; ".join(check.notes[:2]))
        points.append("".join(parts))

    if result.failed_sources or result.status == ResponseStatus.PARTIAL:
        points.append("일부 공공 정보가 확인되지 않아 현장 확인이 필요합니다.")

    return dedupe_strings(points)


def _elevator_evidence_details(check: AccessibilityCheck) -> list[str]:
    details: list[str] = []
    if check.elevator_details:
        selected = _select_elevator_details(
            check.elevator_details,
            mixed=check.elevator_answer_state == FacilityAnswerState.MIXED,
        )
        details.extend(
            f"{_elevator_detail_status_label(detail)}({_elevator_detail_location(detail)})"
            for detail in selected
        )
        remaining = len(check.elevator_details) - len(selected)
        if remaining > 0:
            details.append(f"그 외 {remaining}건")
    elif check.station_has_elevator == AccessibilityEvidenceStatus.CONFIRMED:
        detail = "엘리베이터 위치 확인"
        if check.elevator_location:
            detail += f"({check.elevator_location})"
        details.append(detail)
    elif check.station_has_elevator == AccessibilityEvidenceStatus.FAILED:
        details.append("엘리베이터 정보 없음")
    else:
        details.append("엘리베이터 위치 미확인")

    if check.line is not None:
        details.append("호선 일치 " + _evidence_label(check.line_matched_elevator))

    if not check.elevator_details:
        details.append("운행상태 " + _status_evidence_label(check))

    if check.platform_to_concourse_verified != AccessibilityEvidenceStatus.NOT_APPLICABLE:
        details.append(
            "승강장-대합실 동선 "
            + _evidence_label(check.platform_to_concourse_verified)
        )

    if check.transfer_path_elevator_verified != AccessibilityEvidenceStatus.NOT_APPLICABLE:
        details.append(
            "환승 동선 "
            + _evidence_label(check.transfer_path_elevator_verified)
        )

    if check.exit_elevator_verified != AccessibilityEvidenceStatus.NOT_APPLICABLE:
        details.append("출구 동선 " + _evidence_label(check.exit_elevator_verified))
    return details


def _elevator_detail_status_label(detail: ElevatorEvidenceItem) -> str:
    if (
        detail.status == FacilityStatus.AVAILABLE
        and detail.status_verified == AccessibilityEvidenceStatus.CONFIRMED
    ):
        return "이용 가능"
    if detail.status == FacilityStatus.MAINTENANCE:
        return "점검 중"
    if detail.status == FacilityStatus.UNAVAILABLE:
        return "이용 불가"
    return "운행 상태 미확인"


def _evidence_label(status: AccessibilityEvidenceStatus) -> str:
    if status == AccessibilityEvidenceStatus.CONFIRMED:
        return "확인"
    if status == AccessibilityEvidenceStatus.FAILED:
        return "확인 실패"
    if status == AccessibilityEvidenceStatus.NOT_APPLICABLE:
        return "요구 대상 아님"
    return "미확인"


def _status_evidence_label(check: AccessibilityCheck) -> str:
    if check.elevator_answer_state == FacilityAnswerState.MIXED:
        return "일부 이용 가능, 일부 제한"
    if check.status_verified == AccessibilityEvidenceStatus.CONFIRMED:
        return _status_label(check.elevator_status)
    return _evidence_label(check.status_verified)


def _role_label(role: str) -> str:
    if role == "origin":
        return "출발역"
    if role == "transfer":
        return "환승역"
    if role == "destination":
        return "도착역"
    return "확인역"


def _status_label(status: FacilityStatus) -> str:
    if status == FacilityStatus.AVAILABLE:
        return "확인"
    if status == FacilityStatus.MAINTENANCE:
        return "점검 중"
    if status == FacilityStatus.UNAVAILABLE:
        return "이용 불가"
    return "미확인"


def line_summary(route: RouteCandidate) -> str | None:
    lines = dedupe_strings(
        [
            segment.line
            for segment in route.segments
            if segment.line is not None and segment.line.strip()
        ]
    )
    if not lines:
        return None
    if len(lines) == 1:
        return lines[0]
    return ", ".join(lines[:3])


def restroom_missing_station_names(result: AccessibilityResult) -> list[str]:
    return [check.station for check in restroom_missing_checks(result)]


def restroom_missing_checks(result: AccessibilityResult) -> list[AccessibilityCheck]:
    if not result.mobility_profile.need_accessible_restroom:
        return []
    return [
        check
        for check in result.accessibility_checks
        if check.restroom_required is True and check.restroom_available is False
    ]


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def station_names_for_reason(
    result: AccessibilityResult,
    codes: set[str],
) -> list[str]:
    return dedupe_strings(
        [
            reason.station_name
            for reason in result.risk_reasons
            if reason.code in codes and reason.station_name
        ]
    )


def ordered_station_names(
    station_names: list[str],
    route: RouteCandidate | None,
) -> list[str]:
    deduped = dedupe_strings(station_names)
    if route is None or not route.stations:
        return deduped
    route_order = {station_name: index for index, station_name in enumerate(route.stations)}
    return sorted(deduped, key=lambda station_name: route_order.get(station_name, 10_000))


def key_accessibility_stations(
    station_names: list[str],
    route: RouteCandidate | None,
) -> list[str]:
    if route is None:
        return station_names

    critical_station_names = critical_route_stations(route)
    key_station_names = [
        station_name
        for station_name in critical_station_names
        if station_name in set(station_names)
    ]
    return key_station_names or station_names[:3]


def critical_route_stations(route: RouteCandidate) -> list[str]:
    stations: list[str] = [route.origin, route.destination]

    previous_line: str | None = None
    for segment in route.segments:
        current_line = segment.line.strip() if segment.line else None
        if segment.transfer:
            stations.extend([segment.from_station, segment.to_station])
        if previous_line and current_line and previous_line != current_line:
            stations.append(segment.from_station)
        if current_line:
            previous_line = current_line

    return ordered_station_names(stations, route)


def facilities_for_station_names(
    facilities: list[AccessibleFacility],
    station_names: list[str],
) -> list[AccessibleFacility]:
    selected: list[AccessibleFacility] = []
    selected_normalized: set[str] = set()
    for station_name in station_names:
        normalized_station_name = _normalize_for_message(station_name)
        for facility in facilities:
            if _normalize_for_message(facility.station_name) != normalized_station_name:
                continue
            if normalized_station_name in selected_normalized:
                continue
            selected.append(facility)
            selected_normalized.add(normalized_station_name)
            break
    return selected


def format_facility_station_list(
    facilities: list[AccessibleFacility],
    *,
    fallback_station_names: list[str],
) -> str:
    if not facilities:
        return format_station_list(fallback_station_names)

    formatted: list[str] = []
    for facility in facilities:
        location = (facility.location_description or "").strip()
        if location:
            formatted.append(f"{facility.station_name}({location})")
        else:
            formatted.append(facility.station_name)
    return ", ".join(formatted)


def format_station_list(station_names: list[str]) -> str:
    return ", ".join(station_names)


def format_station_subject(station_names: list[str]) -> str:
    names = dedupe_strings(station_names)
    if len(names) <= 1:
        return "".join(names)
    if len(names) == 2:
        return f"{names[0]}과 {names[1]}"
    return f"{', '.join(names[:-1])}, {names[-1]}"


def station_label(station_name: str) -> str:
    stripped = station_name.strip()
    if stripped.endswith("역"):
        return stripped
    return stripped + "역"


def _normalize_for_message(station_name: str) -> str:
    return station_name.replace("역", "").split("(")[0].strip()
