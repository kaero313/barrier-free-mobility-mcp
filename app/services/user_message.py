from __future__ import annotations

from app.schemas.accessibility import (
    DEFAULT_SAFETY_NOTICE,
    AccessibilityResult,
    UserMessageSummary,
)
from app.schemas.common import ResponseStatus
from app.schemas.facility import FacilityStatus, FacilityType
from app.schemas.route import RouteCandidate
from app.services.user_message_accessibility import (
    accessibility_check_points,
    build_accessibility_table,
    dedupe_strings,
    facilities_for_station_names,
    format_facility_station_list,
    format_station_list,
    key_accessibility_stations,
    line_summary,
    ordered_station_names,
    station_names_for_reason,
)
from app.services.user_message_decision import (
    action_heading,
    headline,
    judgement,
    mobility_condition_summary,
    pre_departure_actions,
    primary_action,
    reasons,
    recommended_route,
    user_facing_reason,
)
from app.services.user_message_sources import data_basis, notices


def build_user_message_context(result: AccessibilityResult) -> dict[str, object]:
    summary = build_user_message_summary(result)
    return {
        "user_message_summary": summary,
        "user_message": _compose_message(summary, result),
    }


def build_user_message_summary(result: AccessibilityResult) -> UserMessageSummary:
    key_points = _key_points(result)
    source_lines = data_basis(result)
    notice_items = notices(result)
    result_judgement = judgement(result)
    return UserMessageSummary(
        judgement=result_judgement,
        headline=headline(result_judgement, result),
        route_overview=_route_overview(
            result.selected_route,
            result.origin,
            result.destination,
        ),
        key_points=key_points if result.accessibility_checks else key_points[:3],
        source_summary="\n".join(source_lines),
        pre_departure_notice=(
            notice_items[0] if notice_items else DEFAULT_SAFETY_NOTICE
        ),
        reasons=reasons(result),
        recommended_route=recommended_route(result),
        mobility_condition_summary=mobility_condition_summary(result.mobility_profile),
        data_basis=source_lines,
        notices=notice_items,
    )


def _route_overview(
    route: RouteCandidate | None,
    origin: str,
    destination: str,
) -> str:
    if route is None:
        return "확인 가능한 경로 후보를 찾지 못했습니다."

    parts: list[str] = []
    route_line_summary = line_summary(route)
    if route_line_summary:
        parts.append(route_line_summary)
    parts.append(f"환승 {route.transfer_count}회")
    return "지하철 경로 기준: " + ", ".join(parts) + "."


def _key_points(result: AccessibilityResult) -> list[str]:
    if result.accessibility_checks:
        return accessibility_check_points(result)

    points: list[str] = []

    blocked_station_names = ordered_station_names(
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
            + format_station_list(blocked_station_names)
        )

    available_elevators = [
        facility
        for facility in result.accessible_facilities
        if facility.facility_type == FacilityType.ELEVATOR
        and facility.status == FacilityStatus.AVAILABLE
    ]
    available_elevator_stations = ordered_station_names(
        [facility.station_name for facility in available_elevators],
        result.selected_route,
    )
    if available_elevator_stations:
        key_available_elevator_stations = key_accessibility_stations(
            available_elevator_stations,
            result.selected_route,
        )
        key_available_elevators = facilities_for_station_names(
            available_elevators,
            key_available_elevator_stations,
        )
        points.append(
            "엘리베이터 위치: "
            + format_facility_station_list(
                key_available_elevators,
                fallback_station_names=key_available_elevator_stations,
            )
        )

    missing_elevator_stations = ordered_station_names(
        station_names_for_reason(
            result,
            {"elevator_not_found", "elevator_source_unsupported"},
        ),
        result.selected_route,
    )
    if missing_elevator_stations:
        points.append(
            "엘리베이터 정보 미확인: "
            + format_station_list(missing_elevator_stations)
        )

    unknown_elevator_stations = ordered_station_names(
        station_names_for_reason(result, {"elevator_unknown"}),
        result.selected_route,
    )
    if unknown_elevator_stations:
        points.append(
            "엘리베이터 상태 미확인: "
            + format_station_list(unknown_elevator_stations)
        )

    if result.failed_sources or result.status == ResponseStatus.PARTIAL:
        points.append("일부 공공 정보가 확인되지 않아 현장 확인이 필요합니다.")

    station_specific_codes = {
        "elevator_not_found",
        "elevator_source_unsupported",
        "elevator_unknown",
        "elevator_unavailable",
    }
    for risk_reason in result.risk_reasons:
        if risk_reason.code in station_specific_codes:
            continue
        user_reason = user_facing_reason(risk_reason.code)
        if user_reason:
            points.append(user_reason)
            break

    if not points:
        points.append("점검 또는 이용 제한으로 확인된 엘리베이터는 없습니다.")

    return dedupe_strings(points)


def _compose_message(
    summary: UserMessageSummary,
    result: AccessibilityResult,
) -> str:
    actions = pre_departure_actions(result)
    result_primary_action = primary_action(summary.judgement, result, actions)
    main_lines = [
        f"**{action_heading(summary.judgement)}**",
        _ensure_sentence(summary.headline),
    ]
    if result_primary_action:
        action_label = (
            "확인할 내용" if summary.judgement == "추가 정보 필요" else "지금 할 일"
        )
        main_lines.append(
            f"**{action_label}:** {_ensure_sentence(result_primary_action)}"
        )

    sections = ["\n".join(main_lines)]

    route_section = _route_section(summary.recommended_route, result.selected_route)
    if route_section:
        sections.append(route_section)

    if result.accessibility_checks:
        sections.append(build_accessibility_table(result))
    else:
        evidence_items = (
            result.available_partial_info
            if summary.judgement == "추가 정보 필요" and result.available_partial_info
            else summary.key_points[:3]
        )
        sections.append(_section("확인 결과", evidence_items))

    remaining_actions = (
        actions[1:] if result_primary_action and actions else actions
    )
    if remaining_actions:
        sections.append(_section("추가 확인", remaining_actions))
    sections.append(_section("기준 시각", summary.data_basis))
    sections.append(_notice_section(summary.notices))

    return "\n\n".join(section for section in sections if section).strip()


def _section(title: str, items: list[str]) -> str:
    if not items:
        return ""
    return "### " + title + "\n\n" + "\n".join(
        f"- {_ensure_sentence(item)}" for item in items if item
    )


def _route_section(
    recommended_route_text: str | None,
    route: RouteCandidate | None,
) -> str:
    if not recommended_route_text or route is None or route.transfer_count == 0:
        return ""
    route_text = _ensure_sentence(recommended_route_text)
    return f"### 환승 정보\n\n**{route_text}**"


def _notice_section(items: list[str]) -> str:
    notice_items = [_ensure_sentence(item) for item in items if item]
    if not notice_items:
        return ""
    visible_notices = notice_items[:3]
    lines = ["### 주의사항", "", f"> {visible_notices[0]}"]
    lines.extend(f"- {notice}" for notice in visible_notices[1:])
    return "\n".join(lines)


def _ensure_sentence(sentence: str) -> str:
    normalized = sentence.strip()
    if not normalized:
        return normalized
    if normalized.endswith((".", "!", "?")):
        return normalized
    return normalized + "."
