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
    lead_points,
    mobility_condition_summary,
    pre_departure_actions,
    primary_action,
    reasons,
    recommended_route,
    user_facing_reason,
)
from app.services.user_message_sources import TRIP_SCOPE_NOTICE, data_basis, notices


def build_user_message_context(
    result: AccessibilityResult,
    *,
    alternative_lines: list[str] | None = None,
) -> dict[str, object]:
    """``alternative_lines``가 있으면 대안 경로 질문의 답으로 "다른 경로" 구역을 넣는다."""
    summary = build_user_message_summary(result)
    return {
        "user_message_summary": summary,
        "user_message": _compose_message(summary, result, alternative_lines=alternative_lines),
        "safety_notice": _carried_safety_notice(summary.notices),
    }


def _carried_safety_notice(notice_items: list[str]) -> str:
    # 화면은 본문에 없는 안전 안내만 따로 보여 준다. 운행 상태를 하나도 보여 주지 않아 본문이
    # 운행 상태 안내를 뺀 답변에서는 본문이 실제로 담은 경로 범위 안내를 안전 안내로 내보낸다.
    if DEFAULT_SAFETY_NOTICE not in notice_items and TRIP_SCOPE_NOTICE in notice_items:
        return TRIP_SCOPE_NOTICE
    return DEFAULT_SAFETY_NOTICE


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
        points.append(
            "경로를 확인하지 못해 역별 엘리베이터 정보는 조회하지 않았습니다."
            if result.selected_route is None
            else "점검 또는 이용 제한으로 확인된 엘리베이터는 없습니다."
        )

    return dedupe_strings(points)


def _compose_message(
    summary: UserMessageSummary,
    result: AccessibilityResult,
    *,
    alternative_lines: list[str] | None = None,
) -> str:
    actions = pre_departure_actions(
        result,
        blocking_only=summary.judgement == "권장하지 않음",
    )
    result_primary_action = primary_action(summary.judgement, result, actions)
    if summary.judgement == "추가 정보 필요" and result_primary_action:
        # 되묻는 답변은 물을 내용만 쓴다. 아직 경로를 조회하지 않았다는 사실은 질문이 드러낸다.
        return _ensure_sentence(result_primary_action)
    action_line = None
    if result_primary_action:
        action_label = "확인할 내용" if summary.judgement == "추가 정보 필요" else "권장 확인"
        action_line = f"**{action_label}:** {_ensure_sentence(result_primary_action)}"

    main_lines = [f"**{action_heading(summary.judgement, result)}**"]
    labelled_points = lead_points(summary.judgement, result)
    if labelled_points:
        # 문제, 확인된 것, 확인 안 된 것, 할 일을 라벨 붙은 줄로 나눠 끝까지 읽지 않아도 훑어 보이게
        # 한다. 할 일은 모두 이 요약에 모아 표 아래 "추가 확인"으로 흩어 놓지 않는다.
        main_lines.extend(["", *(f"- {point}" for point in labelled_points)])
        lead_actions = (
            dedupe_strings([result_primary_action, *actions]) if result_primary_action else actions
        )
        main_lines.extend(_action_items(lead_actions))
        actions = []
    else:
        # 확인 불가는 첫 줄이 이미 이유를 말하므로 같은 내용의 요약 문장을 덧붙이지 않는다.
        if summary.judgement != "확인 불가":
            main_lines.append(_ensure_sentence(summary.headline))
        if action_line:
            main_lines.extend(["", action_line])

    sections = ["\n".join(main_lines)]

    route_section = _route_section(summary.recommended_route, result.selected_route)
    if route_section:
        sections.append(route_section)
    if alternative_lines and result.selected_route is not None:
        sections.append(_section("다른 경로", alternative_lines))

    if result.accessibility_checks:
        sections.append(build_accessibility_table(result))
    elif summary.judgement != "추가 정보 필요":
        # 되묻는 답변은 아직 아무것도 조회하지 않았으므로 확인 결과 구역을 두지 않는다.
        evidence_items = (
            result.available_partial_info
            if result.selected_route is None and result.available_partial_info
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


def _action_items(actions: list[str]) -> list[str]:
    if not actions:
        return []
    if len(actions) == 1:
        return [f"- **권장 확인:** {_ensure_sentence(actions[0])}"]
    return ["- **권장 확인:**", *(f"  - {_ensure_sentence(action)}" for action in actions)]


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
