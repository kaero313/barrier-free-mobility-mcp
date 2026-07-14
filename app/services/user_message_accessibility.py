from __future__ import annotations

from app.schemas.accessibility import (
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
                    _markdown_table_cell("; ".join(confirmed) or "확인된 항목 없음"),
                    _markdown_table_cell("; ".join(attention) or "추가 확인 항목 없음"),
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
        attention.extend(check.notes[:2])
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
        _append_path_evidence(
            confirmed,
            attention,
            "승강장→대합실",
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

    notes = check.notes
    if check.elevator_details:
        notes = [
            note
            for note in notes
            if not note.startswith("정상 운행과 점검 또는 이용불가 상태")
        ]
    attention.extend(notes[:2])
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
    elif check.restroom_available is False and check.restroom_required is True:
        attention.append("장애인화장실 미확인(필수)")
    elif check.restroom_available is False and check.restroom_required is False:
        attention.append("장애인화장실 미확인(참고)")


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
        attention.append(f"그 외 엘리베이터 {remaining}건은 상세 결과에서 확인")
    return confirmed, attention


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
    for detail in ordered:
        if detail in selected:
            continue
        selected.append(detail)
        if len(selected) >= MAX_VISIBLE_ELEVATOR_DETAILS:
            break
    return selected


def _elevator_detail_location(detail: ElevatorEvidenceItem) -> str:
    location = detail.location or "위치 미확인"
    if detail.operation_section and detail.operation_section not in location:
        return f"{location} (운행구간 {detail.operation_section})"
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
    elif status in {
        AccessibilityEvidenceStatus.FAILED,
        AccessibilityEvidenceStatus.UNVERIFIED,
    }:
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
    if not result.mobility_profile.need_accessible_restroom:
        return []
    return [
        check.station
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
