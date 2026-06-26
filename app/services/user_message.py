from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.accessibility import (
    DEFAULT_SAFETY_NOTICE,
    AccessibilityResult,
    AccessibleRestroomRequirement,
    MobilityProfile,
    UserMessageSummary,
)
from app.schemas.common import ResponseStatus
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.schemas.route import RouteCandidate

TECHNICAL_TERMS = {
    "risk_level",
    "confidence_level",
    "cache",
    "payload",
    "data_sources",
    "failed_sources",
}

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


def build_user_message_context(result: AccessibilityResult) -> dict[str, object]:
    summary = build_user_message_summary(result)
    return {
        "user_message_summary": summary,
        "user_message": _compose_message(summary),
    }


def build_user_message_summary(result: AccessibilityResult) -> UserMessageSummary:
    key_points = _key_points(result)
    data_basis = _data_basis(result)
    notices = _notices(result)
    judgement = _judgement(result)
    return UserMessageSummary(
        judgement=judgement,
        headline=_headline(judgement, result.origin, result.destination),
        route_overview=_route_overview(result.selected_route, result.origin, result.destination),
        key_points=key_points if result.accessibility_checks else key_points[:3],
        source_summary="\n".join(data_basis),
        pre_departure_notice=notices[0] if notices else DEFAULT_SAFETY_NOTICE,
        reasons=_reasons(result),
        recommended_route=_recommended_route(result),
        mobility_condition_summary=_mobility_condition_summary(result.mobility_profile),
        data_basis=data_basis,
        notices=notices,
    )


def _headline(judgement: str, origin: str, destination: str) -> str:
    if judgement == "추가 정보 필요":
        return "확인을 위해 이동 조건이나 역명 정보가 더 필요합니다."
    if judgement == "확인 불가":
        return f"현재 정보만으로는 {origin}에서 {destination} 경로를 안내하기 어렵습니다."
    if judgement == "가능":
        return (
            f"현재 공공데이터 기준으로 {origin}에서 {destination}까지 "
            "필요한 접근성 정보가 확인되었습니다."
        )
    if judgement == "주의 필요":
        return (
            f"현재 공공데이터 기준으로 {origin}에서 {destination} 경로는 확인됐지만, "
            "일부 접근성 정보는 추가 확인이 필요합니다."
        )
    return f"현재 공공데이터 기준으로 {origin}에서 {destination}까지 이동은 권장하기 어렵습니다."


def _route_overview(route: RouteCandidate | None, origin: str, destination: str) -> str:
    if route is None:
        return "확인 가능한 경로 후보를 찾지 못했습니다."

    parts: list[str] = []
    line_summary = _line_summary(route)
    if line_summary:
        parts.append(line_summary)
    parts.append(f"환승 {route.transfer_count}회")
    return "지하철 경로 기준: " + ", ".join(parts) + "."


def _key_points(result: AccessibilityResult) -> list[str]:
    if result.accessibility_checks:
        return _accessibility_check_points(result)

    points: list[str] = []

    blocked_station_names = _ordered_station_names(
        [
            issue.station_name
            for issue in result.blocked_facilities
            if issue.facility_type == FacilityType.ELEVATOR
        ],
        result.selected_route,
    )
    if blocked_station_names:
        points.append(
            "엘리베이터 이용 제한: "
            + _format_station_list(blocked_station_names)
        )

    available_elevators = [
        facility
        for facility in result.accessible_facilities
        if facility.facility_type == FacilityType.ELEVATOR
        and facility.status == FacilityStatus.AVAILABLE
    ]
    available_elevator_stations = _ordered_station_names(
        [facility.station_name for facility in available_elevators],
        result.selected_route,
    )
    if available_elevator_stations:
        key_available_elevator_stations = _key_accessibility_stations(
            available_elevator_stations,
            result.selected_route,
        )
        key_available_elevators = _facilities_for_station_names(
            available_elevators,
            key_available_elevator_stations,
        )
        points.append(
            "엘리베이터 위치: "
            + _format_facility_station_list(
                key_available_elevators,
                fallback_station_names=key_available_elevator_stations,
            )
        )

    missing_elevator_stations = _ordered_station_names(
        _station_names_for_reason(result, {"elevator_not_found"}),
        result.selected_route,
    )
    if missing_elevator_stations:
        points.append(
            "엘리베이터 정보 미확인: "
            + _format_station_list(missing_elevator_stations)
        )

    unknown_elevator_stations = _ordered_station_names(
        _station_names_for_reason(result, {"elevator_unknown"}),
        result.selected_route,
    )
    if unknown_elevator_stations:
        points.append(
            "엘리베이터 상태 미확인: "
            + _format_station_list(unknown_elevator_stations)
        )

    if result.failed_sources or result.status == ResponseStatus.PARTIAL:
        points.append("일부 공공 정보가 확인되지 않아 현장 확인이 필요합니다.")

    station_specific_codes = {
        "elevator_not_found",
        "elevator_unknown",
        "elevator_unavailable",
    }
    for reason in result.risk_reasons:
        if reason.code in station_specific_codes:
            continue
        user_reason = _user_facing_reason(reason.code)
        if user_reason:
            points.append(user_reason)
            break

    if not points:
        points.append("점검 또는 이용 제한으로 확인된 엘리베이터는 없습니다.")

    return _dedupe_strings(points)


def _source_summary(result: AccessibilityResult) -> str:
    return "\n".join(_data_basis(result))


def _data_basis(result: AccessibilityResult) -> list[str]:
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


def _compose_message(summary: UserMessageSummary) -> str:
    main_lines = []
    if summary.judgement:
        main_lines.append(f"판단: {summary.judgement}")
    main_lines.append(_ensure_sentence(summary.headline))

    sections = ["\n".join(main_lines)]

    sections.append(_section("이유", summary.reasons))

    route_items = [summary.recommended_route] if summary.recommended_route else []
    sections.append(_section("추천 경로", route_items))

    if summary.key_points:
        sections.append(_section("접근성 체크", summary.key_points))
    else:
        sections.append(_section("접근성 체크", ["역명과 경로 확정 후 확인 가능합니다."]))

    sections.append(_section("사용자 조건 반영", summary.mobility_condition_summary))
    sections.append(_section("기준 시각", summary.data_basis))
    sections.append(_section("주의사항", summary.notices))

    return "\n\n".join(section for section in sections if section).strip()


def _section(title: str, items: list[str]) -> str:
    if not items:
        return ""
    return title + "\n" + "\n".join(f"- {_ensure_sentence(item)}" for item in items if item)


def _ensure_sentence(sentence: str) -> str:
    normalized = sentence.strip()
    if not normalized:
        return normalized
    if normalized.endswith((".", "!", "?")):
        return normalized
    return normalized + "."


def _judgement(result: AccessibilityResult) -> str:
    if result.status == ResponseStatus.NEEDS_CLARIFICATION:
        return "추가 정보 필요"
    if (
        result.status == ResponseStatus.FAILED
        or result.risk_level == "UNKNOWN"
        or _has_critical_source_failure(result)
    ):
        return "확인 불가"
    if result.risk_level == "HIGH":
        return "권장하지 않음"
    if (
        result.risk_level == "CAUTION"
        or _has_unverified_required_condition(result)
        or _has_caution_reason(result)
    ):
        return "주의 필요"
    if result.status == ResponseStatus.PARTIAL or result.failed_sources:
        return "주의 필요"
    if result.risk_level == "LOW":
        return "가능"
    return "권장하지 않음"


def _reasons(result: AccessibilityResult) -> list[str]:
    if result.status == ResponseStatus.NEEDS_CLARIFICATION:
        return _dedupe_strings(
            [
                "출발역, 도착역 또는 이동 조건을 확정해야 합니다.",
                *result.questions,
            ]
        )

    reasons: list[str] = []
    if result.accessibility_checks:
        available_checks = [
            check
            for check in result.accessibility_checks
            if check.elevator_status == FacilityStatus.AVAILABLE
        ]
        restricted_checks = [
            check
            for check in result.accessibility_checks
            if check.elevator_status in {FacilityStatus.MAINTENANCE, FacilityStatus.UNAVAILABLE}
        ]
        unknown_checks = [
            check
            for check in result.accessibility_checks
            if check.elevator_status == FacilityStatus.UNKNOWN
        ]
        if available_checks:
            reasons.append("출발역, 환승역 또는 도착역의 엘리베이터 정보가 확인되었습니다.")
        if restricted_checks:
            restricted_stations = _format_station_list(
                [check.station for check in restricted_checks]
            )
            reasons.append(
                f"엘리베이터 점검 또는 이용 제한 역: {restricted_stations}"
            )
        if unknown_checks:
            unknown_stations = _format_station_list([check.station for check in unknown_checks])
            reasons.append(f"엘리베이터 상태 미확인 역: {unknown_stations}")
        missing_restroom_stations = _restroom_missing_station_names(result)
        if missing_restroom_stations:
            reasons.append(
                "장애인화장실 미확인 역: "
                + _format_station_list(missing_restroom_stations)
            )

    if result.selected_route and result.selected_route.transfer_count > 0:
        reasons.append("경로상 환승이 필요합니다.")

    if _requires_elevator_for_message(result.mobility_profile):
        reasons.append(
            "사용자 조건상 계단이나 에스컬레이터 대신 엘리베이터 동선 확인이 중요합니다."
        )

    for reason in result.risk_reasons:
        user_reason = _user_facing_reason(reason.code, station_specific=bool(reason.station_name))
        if user_reason:
            if reason.station_name:
                reasons.append(f"{reason.station_name}: {user_reason}")
            else:
                reasons.append(user_reason)

    if result.failed_sources or result.status == ResponseStatus.PARTIAL:
        reasons.append("일부 공공 데이터가 확인되지 않아 결과에 한계가 있습니다.")

    if not reasons:
        reasons.append("필수 접근성 시설에서 점검 또는 이용 제한으로 확인된 항목은 없습니다.")

    return _dedupe_strings(reasons)


def _recommended_route(result: AccessibilityResult) -> str:
    route = result.selected_route
    if route is None:
        if result.alternatives:
            return result.alternatives[0].description
        return "확인 가능한 추천 경로 없음."

    station_labels = _recommended_route_station_labels(route)
    return " → ".join(station_labels)


def _recommended_route_station_labels(route: RouteCandidate) -> list[str]:
    critical_stations = _critical_route_stations(route)
    if len(critical_stations) <= 2:
        return [_station_label(route.origin), _station_label(route.destination)]

    labels: list[str] = []
    for station_name in critical_stations:
        label = _station_label(station_name)
        if station_name not in {route.origin, route.destination}:
            label += " 환승"
        labels.append(label)
    return labels


def _station_label(station_name: str) -> str:
    stripped = station_name.strip()
    if stripped.endswith("역"):
        return stripped
    return stripped + "역"


def _requires_elevator_for_message(mobility_profile: MobilityProfile) -> bool:
    return (
        mobility_profile.wheelchair
        or mobility_profile.stroller
        or mobility_profile.cane_or_walker
        or not mobility_profile.can_use_stairs
        or not mobility_profile.can_use_escalator
        or mobility_profile.need_elevator_only
    )


def _mobility_condition_summary(mobility_profile: MobilityProfile) -> list[str]:
    conditions: list[str] = []
    if mobility_profile.wheelchair:
        conditions.append("휠체어 이용 조건을 반영했습니다.")
    if mobility_profile.stroller:
        conditions.append("유모차 이용 조건을 반영했습니다.")
    if mobility_profile.cane_or_walker:
        conditions.append("보행 보조기 또는 지팡이 이용 조건을 반영했습니다.")
    if not mobility_profile.can_use_stairs:
        conditions.append("계단 이용 불가 조건을 반영했습니다.")
    if not mobility_profile.can_use_escalator:
        conditions.append("에스컬레이터 이용 불가 조건을 반영했습니다.")
    if mobility_profile.need_elevator_only:
        conditions.append("엘리베이터 동선이 필수인 조건을 반영했습니다.")
    if mobility_profile.need_accessible_restroom:
        conditions.append(
            "장애인화장실: "
            + _restroom_requirement_label(mobility_profile.accessible_restroom_requirement)
            + " 조건을 반영했습니다."
        )
    if mobility_profile.need_wheelchair_charger:
        conditions.append("휠체어 충전기 필요 조건을 반영했습니다.")
    if mobility_profile.max_transfer_count is not None:
        conditions.append(f"최대 환승 {mobility_profile.max_transfer_count}회 조건을 반영했습니다.")

    if not conditions:
        conditions.append("별도 이동 제약 조건이 제공되지 않았습니다.")
    return conditions


def _restroom_requirement_label(requirement: AccessibleRestroomRequirement) -> str:
    labels = {
        AccessibleRestroomRequirement.ANY_ROUTE_STATION: "경로 중 한 역 이상 확인",
        AccessibleRestroomRequirement.ORIGIN: "출발역 확인",
        AccessibleRestroomRequirement.TRANSFER: "환승역 확인",
        AccessibleRestroomRequirement.DESTINATION: "도착역 확인",
        AccessibleRestroomRequirement.ORIGIN_OR_DESTINATION: "출발역 또는 도착역 확인",
        AccessibleRestroomRequirement.ALL_KEY_STATIONS: "출발역·환승역·도착역 확인",
    }
    return labels[requirement]


def _notices(result: AccessibilityResult) -> list[str]:
    notices = [
        DEFAULT_SAFETY_NOTICE,
        "공공 API 기준 정보이므로 현장 상황과 다를 수 있습니다.",
    ]
    if result.status in {ResponseStatus.PARTIAL, ResponseStatus.FAILED} or result.failed_sources:
        notices.append("일부 데이터가 확인되지 않아 결과가 제한적입니다.")
    if result.status == ResponseStatus.NEEDS_CLARIFICATION:
        notices.append("역명과 이동 조건을 확인한 뒤 다시 조회하는 것을 권장합니다.")
    for limitation in result.limitations:
        if limitation == (
            "대표 접근성 시설만 포함했습니다. 전체 시설 목록은 개별 시설 조회 도구로 확인하세요."
        ):
            notices.append("전체 시설 목록은 개별 시설 조회로 추가 확인할 수 있습니다.")
        elif _looks_sensitive(limitation):
            notices.append("일부 출처 세부 정보는 보안상 표시하지 않았습니다.")
        elif limitation:
            notices.append(limitation)
    return _dedupe_strings(notices)


def _accessibility_check_points(result: AccessibilityResult) -> list[str]:
    points: list[str] = []
    for check in result.accessibility_checks:
        parts = [f"{_role_label(check.role)} {check.station}: "]
        details = [f"엘리베이터 {_status_label(check.elevator_status)}"]
        if check.elevator_location:
            details[-1] += f"({check.elevator_location})"
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

    return _dedupe_strings(points)


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


def _line_summary(route: RouteCandidate) -> str | None:
    lines = _dedupe_strings(
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


def _user_facing_reason(code: str, *, station_specific: bool = False) -> str | None:
    if code == "elevator_unavailable":
        return (
            "엘리베이터 이용이 제한될 수 있습니다."
            if station_specific
            else "일부 역에서 엘리베이터 이용이 제한될 수 있습니다."
        )
    if code == "elevator_unknown":
        return (
            "엘리베이터 상태가 명확히 확인되지 않았습니다."
            if station_specific
            else "일부 엘리베이터 상태는 명확히 확인되지 않았습니다."
        )
    if code == "elevator_not_found":
        return (
            "엘리베이터 정보를 찾지 못했습니다."
            if station_specific
            else "일부 역의 엘리베이터 정보를 찾지 못했습니다."
        )
    if code == "transfer_required":
        return "환승 구간의 엘리베이터 동선을 확인해야 합니다."
    if code == "too_many_transfers":
        return "환승이 많아 엘리베이터 동선 확인이 더 중요합니다."
    if code == "no_accessible_restroom_when_required":
        return (
            "장애인화장실 필수 확인 조건이 충족되지 않았습니다."
            if station_specific
            else "경로 기준 장애인화장실 확인 조건이 충족되지 않았습니다."
        )
    if code == "api_failure":
        return "일부 공공 정보를 확인하지 못했습니다."
    if code == "stale_data":
        return "일부 정보는 최신 상태가 아닐 수 있습니다."
    return None


def _has_critical_source_failure(result: AccessibilityResult) -> bool:
    critical_sources = {"shortest_route", "elevator_status"}
    return any(source.source_name in critical_sources for source in result.failed_sources)


def _has_unverified_required_condition(result: AccessibilityResult) -> bool:
    if _requires_elevator_for_message(result.mobility_profile) and any(
        check.elevator_status == FacilityStatus.UNKNOWN for check in result.accessibility_checks
    ):
        return True
    return bool(_restroom_missing_station_names(result))


def _has_caution_reason(result: AccessibilityResult) -> bool:
    caution_codes = {
        "too_many_transfers",
        "transfer_required",
        "no_accessible_restroom_when_required",
        "elevator_unknown",
        "elevator_not_found",
        "elevator_unavailable",
    }
    return any(reason.code in caution_codes for reason in result.risk_reasons)


def _restroom_missing_station_names(result: AccessibilityResult) -> list[str]:
    if not result.mobility_profile.need_accessible_restroom:
        return []
    return [
        check.station
        for check in result.accessibility_checks
        if check.restroom_required is True and check.restroom_available is False
    ]


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

    successful_sources = [source for source in sources if source.success]
    failed_sources = [source for source in sources if not source.success]
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
                if check.restroom_required is True:
                    station_parts.append(f"{check.station} 미확인(필수)")
                elif check.restroom_required is False:
                    station_parts.append(f"{check.station} 미확인(참고)")
                else:
                    station_parts.append(f"{check.station} 미확인")

    if station_parts:
        suffix = ", ".join(_dedupe_strings(station_parts))
        if checked_at:
            suffix += f" ({_format_time_only(checked_at)} 조회)"
        elif sources and all(not source.success for source in sources):
            suffix += " (확인 실패)"
        return f"장애인화장실 정보: {suffix}"

    if not sources:
        return "장애인화장실 정보: 미확인"
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


def _dedupe_strings(values: list[str]) -> list[str]:
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


def _station_names_for_reason(
    result: AccessibilityResult,
    codes: set[str],
) -> list[str]:
    return _dedupe_strings(
        [
            reason.station_name
            for reason in result.risk_reasons
            if reason.code in codes and reason.station_name
        ]
    )


def _ordered_station_names(
    station_names: list[str],
    route: RouteCandidate | None,
) -> list[str]:
    deduped = _dedupe_strings(station_names)
    if route is None or not route.stations:
        return deduped
    route_order = {station_name: index for index, station_name in enumerate(route.stations)}
    return sorted(deduped, key=lambda station_name: route_order.get(station_name, 10_000))


def _key_accessibility_stations(
    station_names: list[str],
    route: RouteCandidate | None,
) -> list[str]:
    if route is None:
        return station_names

    critical_station_names = _critical_route_stations(route)
    key_station_names = [
        station_name
        for station_name in critical_station_names
        if station_name in set(station_names)
    ]
    return key_station_names or station_names[:3]


def _critical_route_stations(route: RouteCandidate) -> list[str]:
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

    return _ordered_station_names(stations, route)


def _facilities_for_station_names(
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


def _format_facility_station_list(
    facilities: list[AccessibleFacility],
    *,
    fallback_station_names: list[str],
) -> str:
    if not facilities:
        return _format_station_list(fallback_station_names)

    formatted: list[str] = []
    for facility in facilities:
        location = (facility.location_description or "").strip()
        if location:
            formatted.append(f"{facility.station_name}({location})")
        else:
            formatted.append(facility.station_name)
    return ", ".join(formatted)


def _format_station_list(station_names: list[str]) -> str:
    return ", ".join(station_names)


def _normalize_for_message(station_name: str) -> str:
    return station_name.replace("역", "").split("(")[0].strip()


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
