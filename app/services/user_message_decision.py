from __future__ import annotations

from app.schemas.accessibility import (
    AccessibilityCheck,
    AccessibilityEvidenceStatus,
    AccessibilityResult,
    AccessibleRestroomRequirement,
    FacilityAnswerState,
    MobilityProfile,
)
from app.schemas.common import ResponseStatus
from app.schemas.facility import FacilityStatus
from app.schemas.route import RouteCandidate
from app.services.user_message_accessibility import (
    critical_route_stations,
    dedupe_strings,
    detail_location_labels,
    elevator_location_label,
    format_station_list,
    format_station_subject,
    restricted_elevator_location_labels,
    restroom_missing_station_names,
    station_label,
)


def headline(judgement: str, result: AccessibilityResult) -> str:
    origin = station_label(result.origin)
    destination = station_label(result.destination)
    if judgement == "추가 정보 필요":
        return "확인에 필요한 정보가 아직 정해지지 않았습니다."
    if judgement == "확인 불가":
        return (
            f"{origin}에서 {destination}까지 판단하는 데 필요한 공공데이터를 "
            "확인하지 못했습니다."
        )
    if judgement == "가능":
        return (
            f"{origin}에서 {destination}까지 필요한 접근성 정보에서 점검 또는 "
            "이용 제한은 확인되지 않았습니다."
        )
    if judgement == "주의 필요":
        return _caution_headline(result, origin, destination)
    return (
        f"확인된 시설 제한 때문에 현재는 {origin}에서 {destination}까지 이 경로 이용을 "
        "권장하지 않습니다. 대안 경로를 먼저 확인하세요."
    )


def action_heading(judgement: str) -> str:
    if judgement == "추가 정보 필요":
        return "한 가지만 더 알려주세요."
    if judgement == "확인 불가":
        return "현재 정보만으로는 이용 여부를 판단할 수 없습니다."
    if judgement == "가능":
        return "현재 확인된 범위에서는 이용할 수 있습니다."
    if judgement == "권장하지 않음":
        return "현재 확인된 경로는 이용을 권장하지 않습니다."
    return "출발 전에 확인이 필요합니다."


def _caution_headline(
    result: AccessibilityResult,
    origin: str,
    destination: str,
) -> str:
    checks = result.accessibility_checks
    restricted_locations = restricted_elevator_location_labels(checks)
    if restricted_locations:
        available_locations = dedupe_strings(
            [
                label
                for check in checks
                for label in detail_location_labels(
                    check,
                    {FacilityStatus.AVAILABLE},
                )
            ]
        )
        if available_locations:
            return (
                f"{format_station_list(restricted_locations[:3])}의 엘리베이터는 점검 또는 "
                "이용 제한 상태입니다. 다른 위치의 엘리베이터는 이용 가능으로 확인되지만, "
                "필요한 이동 동선과 연결되는지 출발 전에 확인하세요."
            )
        return (
            f"{format_station_list(restricted_locations)}에서 엘리베이터 점검 또는 이용 제한이 "
            "확인되어 현재 경로 이용 전 대안 확인이 필요합니다."
        )

    if _all_elevators_operating(checks) and _has_unverified_path(checks):
        station_names = format_station_subject(
            [
                station_label(check.station)
                for check in checks
                if check.station_has_elevator == AccessibilityEvidenceStatus.CONFIRMED
            ]
        )
        return (
            f"{station_names}의 엘리베이터는 현재 운행 중으로 확인됐습니다. "
            "다만 승강장에서 출구까지 엘리베이터만으로 이어지는지는 확인되지 않았습니다."
        )

    missing_restroom_stations = restroom_missing_station_names(result)
    if missing_restroom_stations:
        return (
            f"이동 경로는 확인됐지만 {format_station_list(missing_restroom_stations)}의 "
            "필수 장애인화장실 정보가 확인되지 않아 출발 전 확인이 필요합니다."
        )

    return (
        f"{origin}에서 {destination}까지 확인이 필요한 정보가 남아 있어 "
        "현재 공공데이터만으로 이용 여부를 확정하기 어렵습니다."
    )


def _all_elevators_operating(checks: list[AccessibilityCheck]) -> bool:
    return bool(checks) and all(
        check.station_has_elevator == AccessibilityEvidenceStatus.CONFIRMED
        and check.status_verified == AccessibilityEvidenceStatus.CONFIRMED
        and check.elevator_answer_state in {None, FacilityAnswerState.AVAILABLE}
        and check.elevator_status == FacilityStatus.AVAILABLE
        for check in checks
    )


def _has_unverified_path(checks: list[AccessibilityCheck]) -> bool:
    return any(
        status in {
            AccessibilityEvidenceStatus.UNVERIFIED,
            AccessibilityEvidenceStatus.FAILED,
        }
        for check in checks
        for status in (
            check.platform_to_concourse_verified,
            check.transfer_path_elevator_verified,
            check.exit_elevator_verified,
        )
    )


def primary_action(
    judgement: str,
    result: AccessibilityResult,
    actions: list[str],
) -> str | None:
    if judgement == "추가 정보 필요":
        return result.questions[0] if result.questions else "역명과 호선을 알려 주세요"
    if judgement == "확인 불가":
        return "잠시 후 다시 조회하고, 이동 전 역무실에 접근성 동선을 문의하세요"
    if judgement == "권장하지 않음":
        return "이 경로 대신 다른 경로나 역무원 지원을 먼저 확인하세요"
    return actions[0] if actions else None


def pre_departure_actions(result: AccessibilityResult) -> list[str]:
    actions: list[str] = []
    path_stations: list[str] = []
    transfer_stations: list[str] = []
    location_stations: list[str] = []
    line_stations: list[str] = []
    status_stations: list[str] = []
    restroom_stations: list[str] = []
    restricted_elevators: list[str] = []

    for check in result.accessibility_checks:
        station = station_label(check.station)
        if check.station_has_elevator != AccessibilityEvidenceStatus.CONFIRMED:
            location_stations.append(station)
        if (
            check.line
            and check.line_matched_elevator != AccessibilityEvidenceStatus.CONFIRMED
        ):
            line_stations.append(f"{check.line}호선 {station}")
        if any(
            status in {
                AccessibilityEvidenceStatus.UNVERIFIED,
                AccessibilityEvidenceStatus.FAILED,
            }
            for status in (
                check.platform_to_concourse_verified,
                check.exit_elevator_verified,
            )
        ):
            path_stations.append(station)
        if check.transfer_path_elevator_verified in {
            AccessibilityEvidenceStatus.UNVERIFIED,
            AccessibilityEvidenceStatus.FAILED,
        }:
            transfer_stations.append(station)
        if check.status_verified in {
            AccessibilityEvidenceStatus.UNVERIFIED,
            AccessibilityEvidenceStatus.FAILED,
        }:
            status_stations.append(station)
        if check.restroom_required is True and check.restroom_available is not True:
            restroom_stations.append(station)
        restricted_elevators.extend(
            detail_location_labels(
                check,
                {FacilityStatus.MAINTENANCE, FacilityStatus.UNAVAILABLE},
            )
        )

    if restricted_elevators:
        actions.append(
            "점검 또는 이용 제한 위치를 피하세요: "
            f"{', '.join(dedupe_strings(restricted_elevators)[:3])}. "
            "표에 표시된 이용 가능 엘리베이터를 확인하세요"
        )

    if path_stations:
        station_scope = ", ".join(dedupe_strings(path_stations))
        actions.append(
            f"{station_scope} 각 역무실에 "
            '"승강장에서 출구까지 엘리베이터로만 이동할 수 있나요?"라고 문의하세요'
        )
    if transfer_stations:
        station_scope = ", ".join(dedupe_strings(transfer_stations))
        actions.append(
            f"{station_scope} 각 역무실에 "
            '"환승 구간도 계단 없이 엘리베이터로 이동할 수 있나요?"라고 문의하세요'
        )
    if location_stations:
        station_scope = ", ".join(dedupe_strings(location_stations))
        actions.append(
            f"{station_scope}에서 이용 가능한 엘리베이터 "
            "위치를 확인하세요"
        )
    if line_stations:
        station_scope = ", ".join(dedupe_strings(line_stations))
        actions.append(
            f"{station_scope}의 엘리베이터 위치가 맞는지 "
            "확인하세요"
        )
    if status_stations:
        station_scope = ", ".join(dedupe_strings(status_stations))
        actions.append(
            f"{station_scope}의 엘리베이터가 현재 운행 "
            "중인지 확인하세요"
        )
    if restroom_stations:
        station_scope = ", ".join(dedupe_strings(restroom_stations))
        actions.append(
            f"{station_scope}의 장애인화장실 위치와 "
            "이용 가능 여부를 확인하세요"
        )

    if len(actions) > 4:
        remaining = len(actions) - 4
        actions = [*actions[:4], f"그 밖의 핵심역 {remaining}곳도 같은 기준으로 확인하세요"]
    if actions:
        return actions
    return ["출발 직전에 이용할 엘리베이터의 운행 상태를 다시 확인하세요"]


def judgement(result: AccessibilityResult) -> str:
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


def reasons(result: AccessibilityResult) -> list[str]:
    if result.status == ResponseStatus.NEEDS_CLARIFICATION:
        return dedupe_strings(
            [
                "출발역, 도착역 또는 이동 조건을 확정해야 합니다.",
                *result.questions,
            ]
        )

    result_reasons: list[str] = []
    if result.accessibility_checks:
        available_locations = dedupe_strings(
            [
                label
                for check in result.accessibility_checks
                for label in (
                    detail_location_labels(check, {FacilityStatus.AVAILABLE})
                    or (
                        [elevator_location_label(check)]
                        if check.elevator_status == FacilityStatus.AVAILABLE
                        else []
                    )
                )
            ]
        )
        restricted_locations = restricted_elevator_location_labels(
            result.accessibility_checks
        )
        unknown_status_checks = [
            check
            for check in result.accessibility_checks
            if (
                not any(
                    detail.status_verified == AccessibilityEvidenceStatus.CONFIRMED
                    for detail in check.elevator_details
                )
                and (
                    check.elevator_status == FacilityStatus.UNKNOWN
                    or check.status_verified != AccessibilityEvidenceStatus.CONFIRMED
                )
            )
        ]
        unverified_path_checks = [
            check
            for check in result.accessibility_checks
            if any(
                status in {
                    AccessibilityEvidenceStatus.UNVERIFIED,
                    AccessibilityEvidenceStatus.FAILED,
                }
                for status in (
                    check.platform_to_concourse_verified,
                    check.transfer_path_elevator_verified,
                    check.exit_elevator_verified,
                )
            )
        ]
        if available_locations:
            visible = available_locations[:3]
            suffix = (
                f" 외 {len(available_locations) - len(visible)}건"
                if len(available_locations) > len(visible)
                else ""
            )
            result_reasons.append(
                "현재 운행 중인 엘리베이터: " + ", ".join(visible) + suffix
            )
        if restricted_locations:
            result_reasons.append(
                "엘리베이터 점검 또는 이용 제한 위치: "
                + format_station_list(restricted_locations[:3])
            )
        if unknown_status_checks:
            unknown_stations = format_station_list(
                [station_label(check.station) for check in unknown_status_checks]
            )
            result_reasons.append(f"운행 상태를 다시 확인해야 하는 역: {unknown_stations}")
        if unverified_path_checks:
            path_stations = format_station_list(
                [station_label(check.station) for check in unverified_path_checks]
            )
            result_reasons.append(
                f"공공데이터에서는 {path_stations}의 승강장부터 출구까지 전체 연결 "
                "동선을 확인할 수 없습니다."
            )
        missing_restroom_stations = restroom_missing_station_names(result)
        if missing_restroom_stations:
            result_reasons.append(
                "장애인화장실 미확인 역: "
                + format_station_list(missing_restroom_stations)
            )

    if result.selected_route and result.selected_route.transfer_count > 0:
        result_reasons.append("경로상 환승이 필요합니다.")

    mobility_reason = _mobility_impact_reason(result.mobility_profile)
    if mobility_reason:
        result_reasons.append(mobility_reason)

    for reason in result.risk_reasons:
        user_reason = user_facing_reason(
            reason.code,
            station_specific=bool(reason.station_name),
        )
        if user_reason:
            if reason.station_name:
                result_reasons.append(f"{reason.station_name}: {user_reason}")
            else:
                result_reasons.append(user_reason)

    if result.failed_sources or result.status == ResponseStatus.PARTIAL:
        result_reasons.append("일부 공공 데이터가 확인되지 않아 결과에 한계가 있습니다.")

    if not result_reasons:
        result_reasons.append(
            "필수 접근성 시설에서 점검 또는 이용 제한으로 확인된 항목은 없습니다."
        )

    return dedupe_strings(result_reasons)


def _mobility_impact_reason(profile: MobilityProfile) -> str | None:
    if not requires_elevator_for_message(profile):
        return None

    if profile.wheelchair:
        return (
            "휠체어 이동에는 승강장부터 출구까지 엘리베이터가 끊김 없이 이어지는지 "
            "확인이 필요합니다."
        )
    if profile.stroller:
        return (
            "유모차 이동에는 승강장부터 출구까지 엘리베이터가 이어지는지 확인이 "
            "필요합니다."
        )
    if profile.cane_or_walker:
        return "보행 보조기구 이용 시 계단을 피할 수 있는 동선 확인이 필요합니다."
    return "계단과 에스컬레이터를 피하려면 엘리베이터 연결 동선 확인이 필요합니다."


def recommended_route(result: AccessibilityResult) -> str:
    route = result.selected_route
    if route is None:
        if result.alternatives:
            return result.alternatives[0].description
        return "확인 가능한 추천 경로 없음."

    station_labels = _recommended_route_station_labels(route)
    return " → ".join(station_labels)


def _recommended_route_station_labels(route: RouteCandidate) -> list[str]:
    critical_stations = critical_route_stations(route)
    if len(critical_stations) <= 2:
        return [station_label(route.origin), station_label(route.destination)]

    labels: list[str] = []
    for station_name in critical_stations:
        label = station_label(station_name)
        if station_name not in {route.origin, route.destination}:
            label += " 환승"
        labels.append(label)
    return labels


def requires_elevator_for_message(mobility_profile: MobilityProfile) -> bool:
    return (
        mobility_profile.wheelchair
        or mobility_profile.stroller
        or mobility_profile.cane_or_walker
        or not mobility_profile.can_use_stairs
        or not mobility_profile.can_use_escalator
        or mobility_profile.need_elevator_only
    )


def mobility_condition_summary(mobility_profile: MobilityProfile) -> list[str]:
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
            + _restroom_requirement_label(
                mobility_profile.accessible_restroom_requirement
            )
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


def user_facing_reason(code: str, *, station_specific: bool = False) -> str | None:
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
    if code == "elevator_source_unsupported":
        return (
            "엘리베이터 정보가 현재 연결된 공공데이터 제공 범위 밖입니다."
            if station_specific
            else "일부 역의 엘리베이터 정보가 현재 데이터 제공 범위 밖입니다."
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
    if code == "restroom_source_unsupported":
        return (
            "장애인화장실 정보가 현재 연결된 공공데이터 제공 범위 밖입니다."
            if station_specific
            else "일부 역의 장애인화장실 정보가 현재 데이터 제공 범위 밖입니다."
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
    if requires_elevator_for_message(result.mobility_profile) and any(
        _has_unverified_elevator_evidence(check) for check in result.accessibility_checks
    ):
        return True
    return bool(restroom_missing_station_names(result))


def _has_unverified_elevator_evidence(check: AccessibilityCheck) -> bool:
    unverified_values = {
        AccessibilityEvidenceStatus.UNVERIFIED,
        AccessibilityEvidenceStatus.FAILED,
    }
    required_fields = [
        check.station_has_elevator,
        check.line_matched_elevator,
        check.platform_to_concourse_verified,
        check.status_verified,
    ]
    if check.role in {"origin", "destination"}:
        required_fields.append(check.exit_elevator_verified)
    if check.role == "transfer":
        required_fields.append(check.transfer_path_elevator_verified)
    return (
        check.elevator_status == FacilityStatus.UNKNOWN
        or any(value in unverified_values for value in required_fields)
    )


def _has_caution_reason(result: AccessibilityResult) -> bool:
    caution_codes = {
        "too_many_transfers",
        "transfer_required",
        "no_accessible_restroom_when_required",
        "restroom_source_unsupported",
        "elevator_unknown",
        "elevator_not_found",
        "elevator_source_unsupported",
        "elevator_unavailable",
    }
    return any(reason.code in caution_codes for reason in result.risk_reasons)
