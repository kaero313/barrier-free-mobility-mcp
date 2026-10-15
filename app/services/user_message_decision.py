from __future__ import annotations

from app.schemas.accessibility import (
    CHARGER_SOURCE_UNSUPPORTED_NOTE,
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
from app.services.station_context import is_route_line_mismatch_note
from app.services.user_message_accessibility import (
    critical_route_stations,
    dedupe_strings,
    detail_location_labels,
    elevator_location_label,
    format_station_list,
    format_station_subject,
    has_platform_elevator,
    restricted_elevator_location_labels,
    restroom_missing_checks,
    restroom_missing_station_names,
    restroom_source_unsupported,
    station_label,
)


def headline(judgement: str, result: AccessibilityResult) -> str:
    origin = station_label(result.origin)
    destination = station_label(result.destination)
    if judgement == "추가 정보 필요":
        return result.route_summary
    if judgement == "확인 불가":
        if _route_not_found(result):
            if _route_line_mismatch(result):
                return (
                    f"{origin}에서 {destination}까지 입력한 역·호선과 맞는 지하철 경로를 "
                    "경로 데이터에서 찾지 못했습니다."
                )
            return f"{origin}에서 {destination}까지 가는 지하철 경로를 찾지 못했습니다."
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
    # 점검·이용 불가가 실제로 확인됐을 때만 "시설 제한"이라고 쓴다. 엘리베이터 정보가 없어서
    # 권장하지 않는 경우와 구분한다.
    if _has_confirmed_restriction(result):
        reason = "확인된 시설 제한 때문에"
    else:
        reason = "엘리베이터 이용을 확인하지 못한 역이 있어"
    return (
        f"{reason} 현재는 {origin}에서 {destination}까지 이 경로 이용을 "
        "권장하지 않습니다. 대안 경로를 먼저 확인하세요."
    )


def action_heading(judgement: str, result: AccessibilityResult) -> str:
    if judgement == "추가 정보 필요":
        return "한 가지만 더 알려주세요."
    if judgement == "확인 불가":
        # 판단하지 못했다는 사실은 화면 제목이 말하므로 첫 줄은 그 이유를 말한다.
        if _route_not_found(result):
            # 사용자가 호선을 지정했을 때만 "입력한 호선"이라고 쓴다.
            if _route_line_mismatch(result):
                return "입력한 역·호선과 맞는 지하철 경로를 찾지 못했습니다."
            return (
                f"{station_label(result.origin)}에서 {station_label(result.destination)}까지 "
                "가는 지하철 경로를 찾지 못했습니다."
            )
        return "판단에 필요한 공공데이터를 확인하지 못해 이용 여부를 판단할 수 없습니다."
    if judgement == "가능":
        return "현재 확인된 범위에서는 이용할 수 있습니다."
    if judgement == "권장하지 않음":
        # 점검·이용 불가가 확인된 경로와, 정보가 없어 권장하지 못하는 경로를 구분한다.
        if _has_confirmed_restriction(result):
            return "현재 확인된 경로는 이용을 권장하지 않습니다."
        return "지금 확인한 정보만으로는 이 경로를 권장할 수 없습니다."
    # 주의 결과는 웹 제목("출발 전에 확인할 점이 있습니다")과 겹치지 않게 확인할 대상을 말한다.
    checks = result.accessibility_checks
    if restricted_elevator_location_labels(checks):
        return f"{_restriction_adjective(checks)} 엘리베이터를 피할 동선을 확인하세요."
    missing = _missing_elevator_checks(result)
    if missing:
        return (
            f"{format_station_subject([_line_station_label(check) for check in missing])}의 "
            "엘리베이터 위치를 먼저 확인하세요."
        )
    if _all_elevators_operating(checks) and _has_unverified_path(checks):
        return _mobility_path_heading(result.mobility_profile)
    missing_restroom = restroom_missing_station_names(result)
    if missing_restroom:
        return (
            f"{format_station_subject([station_label(name) for name in missing_restroom])}의 "
            "장애인화장실을 출발 전에 확인하세요."
        )
    return "출발 전에 확인이 필요합니다."


def _mobility_path_heading(profile: MobilityProfile) -> str:
    # 첫 줄에는 해야 할 일만 둔다. 엘리베이터 운행 사실은 바로 다음 문장이 역 이름과 함께 말하므로
    # 여기서 반복하지 않는다.
    if profile.wheelchair:
        return "휠체어 이동 동선을 추가로 확인하세요."
    if profile.stroller:
        return "유모차 이동 동선을 추가로 확인하세요."
    if profile.cane_or_walker:
        return "보행 보조기구로 계단 없이 이동할 동선을 추가로 확인하세요."
    return "계단 없는 연결 동선을 추가로 확인하세요."


def _caution_headline(
    result: AccessibilityResult,
    origin: str,
    destination: str,
) -> str:
    checks = result.accessibility_checks
    restricted = _restricted_sentences(checks)
    if restricted:
        return " ".join(restricted)
    missing = _missing_elevator_sentences(result)
    if missing:
        return " ".join(missing)

    operating_path = _operating_path_sentences(checks)
    if operating_path is not None:
        confirmed, unverified = operating_path
        return f"{confirmed}. 다만 {unverified}."

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


def lead_points(judgement: str, result: AccessibilityResult) -> list[str]:
    """Split a caution result into labelled lines so the problem and the gaps stand out.

    Returns an empty list when there is no restriction or missing evidence to point at;
    callers then keep the single-sentence headline.
    """
    if judgement not in {"주의 필요", "권장하지 않음"}:
        return []
    checks = result.accessibility_checks
    restricted = _restricted_sentences(checks)
    unconfirmed = [
        *_missing_elevator_sentences(result),
        *_unknown_status_sentences(checks),
        *_unverified_path_sentences(checks),
        *_missing_restroom_sentences(result),
        *([CHARGER_SOURCE_UNSUPPORTED_NOTE] if charger_unchecked(result) else []),
    ]
    if not restricted and not unconfirmed:
        return []
    points: list[str] = []
    if restricted:
        points.append("**이용 제한:** " + " ".join(restricted))
    confirmed = _operating_sentence(checks)
    if confirmed:
        points.append(f"**확인됨:** {confirmed}")
    if unconfirmed:
        points.append("**확인 안 됨:** " + " ".join(unconfirmed))
    return points


def charger_unchecked(result: AccessibilityResult) -> bool:
    # 경로를 찾은 답변에서만 말한다. 경로가 없으면 역 시설을 조회하지 않았다.
    return result.mobility_profile.need_wheelchair_charger and result.selected_route is not None


def _operating_path_sentences(checks: list[AccessibilityCheck]) -> tuple[str, str] | None:
    if not (_all_elevators_operating(checks) and _has_unverified_path(checks)):
        return None
    confirmed = _operating_sentence(checks)
    unverified = _unverified_path_sentences(checks)
    if confirmed is None or not unverified:
        return None
    return confirmed.removesuffix("."), unverified[0].removesuffix(".")


_RESTRICTED_STATUSES = {FacilityStatus.MAINTENANCE, FacilityStatus.UNAVAILABLE}
_UNVERIFIED_VALUES = {
    AccessibilityEvidenceStatus.UNVERIFIED,
    AccessibilityEvidenceStatus.FAILED,
}


def _is_operating(check: AccessibilityCheck) -> bool:
    return (
        check.station_has_elevator == AccessibilityEvidenceStatus.CONFIRMED
        and check.status_verified == AccessibilityEvidenceStatus.CONFIRMED
        and check.elevator_answer_state in {None, FacilityAnswerState.AVAILABLE}
        and check.elevator_status == FacilityStatus.AVAILABLE
    )


def _is_restricted(check: AccessibilityCheck) -> bool:
    return bool(restricted_elevator_location_labels([check]))


def _has_operating_elevator(check: AccessibilityCheck) -> bool:
    if check.elevator_details:
        return bool(detail_location_labels(check, {FacilityStatus.AVAILABLE}))
    return (
        check.elevator_answer_state == FacilityAnswerState.MIXED
        or check.elevator_status == FacilityStatus.AVAILABLE
    )


def _restricted_statuses(check: AccessibilityCheck) -> set[FacilityStatus]:
    statuses = {
        detail.status
        for detail in check.elevator_details
        if detail.status in _RESTRICTED_STATUSES
        and detail.status_verified == AccessibilityEvidenceStatus.CONFIRMED
    }
    if not statuses and check.elevator_status in _RESTRICTED_STATUSES:
        statuses.add(check.elevator_status)
    return statuses


def _restriction_adjective(checks: list[AccessibilityCheck]) -> str:
    statuses = {status for check in checks for status in _restricted_statuses(check)}
    if statuses == {FacilityStatus.MAINTENANCE}:
        return "점검 중인"
    if statuses == {FacilityStatus.UNAVAILABLE}:
        return "이용할 수 없는"
    return "점검 중이거나 이용할 수 없는"


def _restriction_predicate(statuses: set[FacilityStatus]) -> str:
    if statuses == {FacilityStatus.MAINTENANCE}:
        return "점검 중입니다"
    if statuses == {FacilityStatus.UNAVAILABLE}:
        return "이용할 수 없습니다"
    return "점검 중이거나 이용할 수 없습니다"


def _restricted_sentences(checks: list[AccessibilityCheck]) -> list[str]:
    # 같은 역에 대신 탈 엘리베이터가 있는지가 휠체어 이용자에게 가장 중요하므로 역마다 함께 밝힌다.
    sentences: list[str] = []
    for check in checks:
        if not _is_restricted(check):
            continue
        station = station_label(check.station)
        locations = dedupe_strings(
            [
                detail.location or "위치 미확인"
                for detail in check.elevator_details
                if detail.status in _RESTRICTED_STATUSES
                and detail.status_verified == AccessibilityEvidenceStatus.CONFIRMED
            ]
        )
        if locations:
            subject = f"{station} {', '.join(locations[:3])} 엘리베이터는"
        elif check.elevator_answer_state == FacilityAnswerState.MIXED:
            subject = f"{station}의 일부 엘리베이터는"
        else:
            subject = f"{station} 엘리베이터는"
        alternative = (
            "같은 역에 운행 중인 다른 엘리베이터가 있습니다."
            if _has_operating_elevator(check)
            else "이 역에서 운행이 확인된 다른 엘리베이터는 없습니다."
        )
        sentences.append(
            f"{subject} {_restriction_predicate(_restricted_statuses(check))}. {alternative}"
        )
    return sentences


def _operating_sentence(checks: list[AccessibilityCheck]) -> str | None:
    operating = [check for check in checks if _is_operating(check)]
    if not operating:
        return None
    station_names = format_station_subject([station_label(check.station) for check in operating])
    sentence = f"{station_names}의 엘리베이터는 현재 운행 중"
    if not _all_endpoint_exit_paths_confirmed(operating):
        return sentence + "입니다."
    endpoints = [check for check in operating if check.role in {"origin", "destination"}]
    if len(endpoints) == len(operating):
        return sentence + "이고 대합실에서 출구까지 연결도 확인됐습니다."
    # 환승역에서는 출구로 나가지 않으므로 출구 연결은 출발·도착역에 대해서만 말한다.
    endpoint_names = format_station_subject([station_label(check.station) for check in endpoints])
    return sentence + f"이고, {endpoint_names}은 대합실에서 출구까지 연결도 확인됐습니다."


def _missing_elevator_checks(result: AccessibilityResult) -> list[AccessibilityCheck]:
    return [
        check
        for check in result.accessibility_checks
        if not check.elevator_details and check.station_has_elevator in _UNVERIFIED_VALUES
    ]


def _line_station_label(check: AccessibilityCheck) -> str:
    station = station_label(check.station)
    return f"{check.line}호선 {station}" if check.line else station


def _missing_elevator_sentences(result: AccessibilityResult) -> list[str]:
    predicates: dict[str, list[str]] = {}
    for check in _missing_elevator_checks(result):
        # 표의 같은 역 칸과 같은 이유를 말하도록 조회 결과 상태를 먼저 본다.
        if _all_station_data_unsupported(result, check):
            predicate = "엘리베이터와 필수 장애인화장실 정보는 현재 공공데이터 제공 범위 밖입니다"
        elif check.elevator_answer_state == FacilityAnswerState.UNSUPPORTED:
            predicate = "엘리베이터 정보는 현재 공공데이터 제공 범위 밖입니다"
        elif check.elevator_answer_state == FacilityAnswerState.NOT_FOUND:
            predicate = "엘리베이터 정보를 공공데이터에서 찾지 못했습니다"
        elif check.station_has_elevator == AccessibilityEvidenceStatus.FAILED:
            predicate = "엘리베이터 정보를 불러오지 못했습니다"
        else:
            predicate = "엘리베이터 정보를 확인하지 못했습니다"
        predicates.setdefault(predicate, []).append(_line_station_label(check))
    return [
        f"{format_station_subject(stations)}의 {predicate}."
        for predicate, stations in predicates.items()
    ]


def _unknown_status_sentences(checks: list[AccessibilityCheck]) -> list[str]:
    stations = [
        station_label(check.station)
        for check in checks
        if check.station_has_elevator == AccessibilityEvidenceStatus.CONFIRMED
        and not _is_operating(check)
        and not _is_restricted(check)
    ]
    if not stations:
        return []
    return [f"{format_station_subject(stations)}의 엘리베이터 운행 상태를 확인하지 못했습니다."]


def _unverified_path_sentences(checks: list[AccessibilityCheck]) -> list[str]:
    # 공공데이터는 엘리베이터 설명에 연결 구간이 적혀 있을 때만 연결을 확인으로 본다. 표에 운행 중인
    # 엘리베이터가 보이는데도 연결을 확인 못 한 이유를 함께 밝혀 모순처럼 읽히지 않게 한다.
    path_checks = [
        check
        for check in checks
        if check.station_has_elevator == AccessibilityEvidenceStatus.CONFIRMED
        and _has_operating_elevator(check)
    ]
    if not _has_unverified_path(path_checks):
        return []
    labels = _unverified_path_labels(path_checks)
    platform_checks = [
        check for check in path_checks if check.platform_to_concourse_verified in _UNVERIFIED_VALUES
    ]
    if platform_checks and all(has_platform_elevator(check) for check in platform_checks):
        # 표가 승강장 엘리베이터를 운행 중으로 보여 주므로, 모르는 것은 엘리베이터가 있는지가
        # 아니라 그 엘리베이터가 대합실까지 이어지는지라고 쓴다.
        others = [label for label in labels if label != "승강장과 대합실 사이"]
        subject = "승강장 엘리베이터가 대합실까지 이어지는지"
        if others:
            subject += f"와 {', '.join(others)} 연결은"
        else:
            subject += "는"
        return [f"{subject} 공공데이터 시설 설명에 나오지 않습니다."]
    paths = ", ".join(labels)
    return [
        f"엘리베이터가 {paths}{_object_particle(paths)} 잇는지는 "
        "공공데이터 시설 설명에 나오지 않습니다."
    ]


def _missing_restroom_sentences(result: AccessibilityResult) -> list[str]:
    predicates: dict[str, list[str]] = {}
    for check in restroom_missing_checks(result):
        if _all_station_data_unsupported(result, check):
            # 엘리베이터 문장이 이미 함께 말했다.
            continue
        predicate = (
            "필수 장애인화장실 정보는 현재 공공데이터 제공 범위 밖입니다"
            if restroom_source_unsupported(check)
            else "필수 장애인화장실 정보를 확인하지 못했습니다"
        )
        predicates.setdefault(predicate, []).append(_line_station_label(check))
    return [
        f"{format_station_subject(stations)}의 {predicate}."
        for predicate, stations in predicates.items()
    ]


def _all_station_data_unsupported(result: AccessibilityResult, check: AccessibilityCheck) -> bool:
    # 같은 역의 엘리베이터와 필수 장애인화장실이 모두 제공 범위 밖이면 한 문장으로 묶는다.
    return (
        check.elevator_answer_state == FacilityAnswerState.UNSUPPORTED
        and restroom_source_unsupported(check)
        and check in restroom_missing_checks(result)
    )


def _object_particle(word: str) -> str:
    last = word[-1]
    if "가" <= last <= "힣":
        return "을" if (ord(last) - ord("가")) % 28 else "를"
    return "를"


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


def _all_endpoint_exit_paths_confirmed(checks: list[AccessibilityCheck]) -> bool:
    endpoint_checks = [check for check in checks if check.role in {"origin", "destination"}]
    return bool(endpoint_checks) and all(
        check.exit_elevator_verified == AccessibilityEvidenceStatus.CONFIRMED
        for check in endpoint_checks
    )


def _unverified_path_labels(checks: list[AccessibilityCheck]) -> list[str]:
    unverified_values = {
        AccessibilityEvidenceStatus.UNVERIFIED,
        AccessibilityEvidenceStatus.FAILED,
    }
    labels: list[str] = []
    if any(check.platform_to_concourse_verified in unverified_values for check in checks):
        labels.append("승강장과 대합실 사이")
    if any(check.transfer_path_elevator_verified in unverified_values for check in checks):
        labels.append("환승 구간")
    if any(check.exit_elevator_verified in unverified_values for check in checks):
        labels.append("대합실과 출구 사이")
    return labels or ["승강장에서 출구까지 전체"]


def primary_action(
    judgement: str,
    result: AccessibilityResult,
    actions: list[str],
) -> str | None:
    if judgement == "추가 정보 필요":
        return result.questions[0] if result.questions else "역명과 호선을 알려 주세요"
    if judgement == "확인 불가":
        if _route_line_mismatch(result):
            return "호선을 빼고 다시 조회하거나, 이동 전 역무실에 접근성 동선을 문의하세요"
        if _route_not_found(result):
            # 경로 데이터에 경로가 없었으니 다시 조회해도 같은 결과다.
            return "이동 전 역무실에 접근성 동선을 문의하세요"
        return "잠시 후 다시 조회하고, 이동 전 역무실에 접근성 동선을 문의하세요"
    if judgement == "권장하지 않음":
        # 역무실에 물을 구체적인 질문이 있으면 그것을 먼저 쓴다.
        return actions[0] if actions else "이 경로 대신 다른 경로나 역무원 지원을 먼저 확인하세요"
    if actions:
        return actions[0]
    if judgement == "주의 필요":
        return "출발 전에 역무실에 엘리베이터 이동 동선을 문의하세요"
    # 이용 가능 판단에서 남은 할 일은 출발 직전 재확인뿐이고, 주의사항의 안전 안내가 이미 말한다.
    return None


def _has_confirmed_restriction(result: AccessibilityResult) -> bool:
    return bool(
        result.blocked_facilities
        or restricted_elevator_location_labels(result.accessibility_checks)
    )


def _route_line_mismatch(result: AccessibilityResult) -> bool:
    return any(is_route_line_mismatch_note(info) for info in result.available_partial_info)


def _route_not_found(result: AccessibilityResult) -> bool:
    return (
        result.status == ResponseStatus.FAILED
        and result.selected_route is None
        and not result.failed_sources
    )


def pre_departure_actions(
    result: AccessibilityResult,
    *,
    blocking_only: bool = False,
) -> list[str]:
    """List station-office checks; ``blocking_only`` keeps those about restricted or missing
    elevators, for answers that already advise against the route."""
    checks = result.accessibility_checks
    profile = result.mobility_profile
    restricted_stations = [
        station_label(check.station) for check in checks if _is_restricted(check)
    ]
    missing_stations = [station_label(check.station) for check in _missing_elevator_checks(result)]
    # 이용 제한이나 엘리베이터 정보가 없는 역은 역무실 문의 한 번으로 묶고, 같은 역무실에 동선을
    # 또 묻지 않도록 아래 구간별 문의에서 뺀다.
    handled = {*restricted_stations, *missing_stations}
    path_questions: dict[str, list[str]] = {}
    line_stations: list[str] = []
    status_stations: list[str] = []
    restroom_stations: list[str] = []

    for check in checks:
        station = station_label(check.station)
        if check.restroom_required is True and check.restroom_available is not True:
            restroom_stations.append(station)
        if station in handled:
            continue
        if (
            check.line
            and check.line_matched_elevator != AccessibilityEvidenceStatus.CONFIRMED
        ):
            line_stations.append(f"{check.line}호선 {station}")
        path_question = _path_question(check)
        if path_question:
            path_questions.setdefault(path_question, []).append(station)
        if check.status_verified in _UNVERIFIED_VALUES:
            status_stations.append(station)

    actions: list[str] = []
    # 같은 역에 운행 중인 엘리베이터가 남아 있으면 그것만으로 이동할 수 있는지, 없으면 다른 수단이
    # 있는지를 묻는다.
    restricted_checks = [check for check in checks if _is_restricted(check)]
    for has_alternative, question in (
        (True, "운행 중인 다른 엘리베이터만으로 이동할 수 있나요?"),
        (False, "이용할 수 있는 다른 엘리베이터나 이동 지원이 있나요?"),
    ):
        stations = [
            station_label(check.station)
            for check in restricted_checks
            if _has_operating_elevator(check) is has_alternative
        ]
        if stations:
            actions.append(_station_office_action(stations, profile, question))
    # 엘리베이터 정보가 없는 역에서 필요한 장애인화장실도 확인하지 못했으면 같은 질문에 담는다.
    with_restroom = [station for station in missing_stations if station in restroom_stations]
    for stations, question in (
        (with_restroom, "이용할 수 있는 엘리베이터와 장애인화장실이 어디 있나요?"),
        (
            [station for station in missing_stations if station not in with_restroom],
            "이용할 수 있는 엘리베이터가 어디 있나요?",
        ),
    ):
        if stations:
            actions.append(_station_office_action(stations, profile, question))
    if blocking_only:
        # 이 경로를 권장하지 않는 답변에서는 이 경로의 세부 동선 문의를 늘어놓지 않는다.
        return actions
    # 한 역무실에는 확인이 필요한 구간을 모두 담아 한 번만 묻는다.
    for question, stations in path_questions.items():
        actions.append(_station_office_action(stations, profile, question))
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
    restroom_stations = [station for station in restroom_stations if station not in with_restroom]
    if charger_unchecked(result):
        actions.append("이동 전 역무실에 경로 역의 휠체어 충전기 위치를 문의하세요")
    if restroom_stations:
        station_scope = ", ".join(dedupe_strings(restroom_stations))
        actions.append(
            f"{station_scope}의 장애인화장실 위치와 "
            "이용 가능 여부를 확인하세요"
        )
    # 할 일이 없으면 비워 둔다. 출발 직전 재확인은 주의사항의 안전 안내가 이미 말한다.
    return actions


def _path_question(check: AccessibilityCheck) -> str | None:
    platform = check.platform_to_concourse_verified in _UNVERIFIED_VALUES
    exit_path = check.exit_elevator_verified in _UNVERIFIED_VALUES
    segments: list[str] = []
    if platform and exit_path:
        segments.append("승강장에서 출구까지")
    elif platform:
        segments.append("승강장에서 대합실까지")
    elif exit_path:
        segments.append("대합실에서 출구까지")
    if check.transfer_path_elevator_verified in _UNVERIFIED_VALUES:
        segments.append("환승 구간을")
    if not segments:
        return None
    return f"{', '.join(segments)} 엘리베이터로 이동할 수 있나요?"


def _station_office_action(
    stations: list[str],
    profile: MobilityProfile,
    question: str,
) -> str:
    station_scope = format_station_subject(dedupe_strings(stations))
    return f'{station_scope}의 역무실에 "{_mobility_subject(profile)} {question}"라고 문의하세요'


def _mobility_subject(profile: MobilityProfile) -> str:
    if profile.wheelchair:
        return "휠체어로"
    if profile.stroller:
        return "유모차로"
    if profile.cane_or_walker:
        return "보행 보조기구를 사용해 계단 없이"
    return "계단 없이"


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
        # 충전기는 연결된 데이터에 없어 판단에 반영하지 못한다.
        conditions.append("휠체어 충전기 필요 조건은 데이터 제공 범위 밖이라 확인하지 못했습니다.")
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
