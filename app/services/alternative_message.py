from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from app.schemas.accessibility import AccessibilityResult, FacilityQuestionResult
from app.schemas.common import ResponseStatus
from app.schemas.facility import FacilityStatus, FacilityType

MAX_ALTERNATIVE_ITEMS = 5


def build_station_facility_alternative_message(
    result: FacilityQuestionResult,
) -> str:
    available = [
        facility
        for item in result.items
        for facility in item.facilities
        if facility.status == FacilityStatus.AVAILABLE
        and facility.location_description
    ]
    blocked = [
        facility
        for item in result.items
        for facility in item.facilities
        if facility.status in {FacilityStatus.MAINTENANCE, FacilityStatus.UNAVAILABLE}
    ]
    if result.status == ResponseStatus.FAILED:
        judgement = "확인 불가"
        headline = "공공데이터 조회 실패로 대체 가능한 시설을 확인하지 못했습니다."
    elif available and blocked:
        judgement = "대체 시설 확인"
        headline = "이용이 제한된 시설 외에 정상 상태와 위치가 확인된 시설이 있습니다."
    elif available:
        judgement = "현재 고장 정보 없음"
        headline = (
            "현재 조회에서는 고장 또는 점검으로 확인된 시설이 없으며 "
            "이용 가능한 시설이 있습니다."
        )
    else:
        judgement = "확인된 대안 없음"
        headline = "현재 공공데이터에서 정상 상태와 위치가 모두 확인된 대체 시설을 찾지 못했습니다."

    return "\n\n".join(
        [
            f"**확인 결과: {judgement}**\n{headline}",
            "### 역·호선\n"
            f"- {_station_label(result.station_name, result.line)}",
            "### 현재 시설 상태\n" + "\n".join(_station_status_lines(result)),
            _available_facility_table(available),
            "### 기준 시각\n" + "\n".join(_facility_checked_at_lines(result)),
            _notice_section(
                "한계·주의사항",
                [
                    result.safety_notice,
                    "위치가 없거나 상태가 미확인인 시설은 대안으로 추천하지 않았습니다.",
                    "공공 API 기준 정보이므로 현장 상황과 다를 수 있습니다.",
                ],
            ),
        ]
    )


def build_route_alternative_message(result: AccessibilityResult) -> str:
    judgement = _route_alternative_judgement(result)
    route = result.selected_route
    route_text = (
        result.user_message_summary.recommended_route
        or (f"{route.origin}역 → {route.destination}역" if route else None)
    )
    if route is None:
        recommendation_lines = ["- 비교 가능한 경로 후보를 확인하지 못했습니다."]
    elif result.risk_level in {"HIGH", "UNKNOWN"}:
        recommendation_lines = [
            f"- 검토 후보: {route_text}.",
            "- 접근성 위험 또는 미확인 정보가 커서 추천 경로로 단정하지 않습니다.",
        ]
    else:
        recommendation_lines = [f"- {route_text}."]

    return "\n\n".join(
        [
            f"**판단: {judgement}**\n{_route_alternative_headline(result)}",
            "### 대안 요청 조건\n" + "\n".join(_mobility_condition_lines(result)),
            "### 추천 대안\n" + "\n".join(recommendation_lines),
            "### 접근성 근거\n" + "\n".join(_accessibility_evidence_lines(result)),
            "### 다른 후보\n" + "\n".join(_other_route_lines(result)),
            "### 기준 시각\n" + "\n".join(_route_checked_at_lines(result)),
            _notice_section(
                "주의사항",
                [
                    result.safety_notice,
                    "공공 API가 반환한 경로 후보 안에서만 비교했으며 "
                    "특정 역 회피를 보장하지 않습니다.",
                    "공공 API 기준 정보이므로 현장 상황과 다를 수 있습니다.",
                ],
            ),
        ]
    )


def _available_facility_table(facilities) -> str:
    lines = [
        "### 대체 가능한 시설",
        "",
        "| 시설 | 위치 | 상태 |",
        "|---|---|---|",
    ]
    if not facilities:
        lines.append("| 확인된 대안 없음 | 위치 미확인 | 추천하지 않음 |")
        lines.extend(
            [
                "",
                "- 정상 상태와 위치가 모두 확인된 대체 시설이 없습니다.",
            ]
        )
        return "\n".join(lines)

    for facility in facilities[:MAX_ALTERNATIVE_ITEMS]:
        lines.append(
            f"| {_markdown_table_cell(_facility_type_label(facility.facility_type))} | "
            f"{_markdown_table_cell(facility.location_description or '위치 미확인')} | "
            f"{_markdown_table_cell(_status_label(facility.status))} |"
        )
    remaining = len(facilities) - min(len(facilities), MAX_ALTERNATIVE_ITEMS)
    if remaining > 0:
        lines.extend(
            [
                "",
                f"- 그 외 {remaining}건은 구조화된 시설 결과에 포함되어 있습니다.",
            ]
        )
    return "\n".join(lines)


def _notice_section(title: str, notices: list[str]) -> str:
    values = [notice for notice in notices if notice]
    if not values:
        return ""
    lines = [f"### {title}", "", f"> {values[0]}"]
    lines.extend(f"- {notice}" for notice in values[1:])
    return "\n".join(lines)


def _markdown_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _station_status_lines(result: FacilityQuestionResult) -> list[str]:
    lines: list[str] = []
    for item in result.items:
        label = _facility_type_label(item.facility_type)
        counts = Counter(facility.status for facility in item.facilities)
        details = [
            f"{_status_label(status)} {counts[status]}건"
            for status in (
                FacilityStatus.AVAILABLE,
                FacilityStatus.MAINTENANCE,
                FacilityStatus.UNAVAILABLE,
                FacilityStatus.UNKNOWN,
            )
            if counts[status]
        ]
        lines.append(f"- {label}: {' / '.join(details) if details else '상태 미확인'}.")
    return lines or ["- 시설 상태를 확인하지 못했습니다."]


def _available_facility_lines(facilities) -> list[str]:
    if not facilities:
        return ["- 정상 상태와 위치가 모두 확인된 대체 시설이 없습니다."]
    lines = [
        f"- {_facility_type_label(facility.facility_type)}: {facility.location_description}."
        for facility in facilities[:MAX_ALTERNATIVE_ITEMS]
    ]
    remaining = len(facilities) - len(lines)
    if remaining > 0:
        lines.append(f"- 그 외 {remaining}건은 구조화된 시설 결과에 포함되어 있습니다.")
    return lines


def _facility_checked_at_lines(result: FacilityQuestionResult) -> list[str]:
    lines = [
        "- 전체 조회 시각: "
        + (_format_datetime(result.last_checked_at) or "확인된 기준 시각 없음")
        + "."
    ]
    for source in result.evidence_sources:
        label = _source_label(source.source_name)
        if source.success and source.checked_at is not None:
            lines.append(f"- {label}: {_format_time(source.checked_at)} 확인.")
        elif not source.success:
            lines.append(f"- {label}: 확인 실패.")
    return _dedupe(lines)


def _route_alternative_judgement(result: AccessibilityResult) -> str:
    if result.status == ResponseStatus.FAILED or result.risk_level == "UNKNOWN":
        return "확인 불가"
    if result.risk_level == "HIGH":
        return "권장할 대안 없음"
    if result.risk_level == "CAUTION":
        return "주의가 필요한 대안"
    return "대안 경로 확인"


def _route_alternative_headline(result: AccessibilityResult) -> str:
    if result.selected_route is None:
        return "비교 가능한 지하철 경로 후보를 확인하지 못했습니다."
    if result.risk_level in {"HIGH", "UNKNOWN"}:
        return "현재 후보 중 접근성 조건을 충족한다고 권장할 수 있는 경로를 확인하지 못했습니다."
    return "현재 공공데이터 후보 중 접근성 위험이 가장 낮은 경로를 우선 표시합니다."


def _mobility_condition_lines(result: AccessibilityResult) -> list[str]:
    profile = result.mobility_profile
    lines: list[str] = []
    if profile.wheelchair:
        lines.append("- 휠체어 이용 조건을 반영했습니다.")
    if profile.stroller:
        lines.append("- 유모차 이용 조건을 반영했습니다.")
    if profile.cane_or_walker:
        lines.append("- 보행 보조 조건을 반영했습니다.")
    if profile.need_elevator_only or not profile.can_use_stairs:
        lines.append("- 엘리베이터가 필요한 경로 조건을 반영했습니다.")
    if profile.max_transfer_count is not None:
        lines.append(f"- 환승 {profile.max_transfer_count}회 이하 조건을 반영했습니다.")
    return _dedupe(lines) or ["- 전달된 이동 조건을 기준으로 후보를 비교했습니다."]


def _accessibility_evidence_lines(result: AccessibilityResult) -> list[str]:
    lines: list[str] = []
    for check in result.accessibility_checks[:MAX_ALTERNATIVE_ITEMS]:
        role = {"origin": "출발역", "transfer": "환승역", "destination": "도착역"}.get(
            check.role,
            "확인역",
        )
        location = check.elevator_location or "위치 미확인"
        lines.append(
            f"- {role} {check.station}역: 엘리베이터 "
            f"{_status_label(check.elevator_status)}, {location}."
        )
    if result.failed_sources:
        lines.append("- 일부 공공데이터 출처가 확인되지 않아 비교 결과가 제한적입니다.")
    return lines or ["- 역별 접근성 근거를 확인하지 못했습니다."]


def _other_route_lines(result: AccessibilityResult) -> list[str]:
    if not result.alternatives:
        return ["- 비교 가능한 다른 경로 후보가 없습니다."]
    lines: list[str] = []
    for alternative in result.alternatives[:2]:
        route = alternative.route
        if route is None:
            continue
        lines.append(
            f"- {alternative.description}: 환승 {route.transfer_count}회, "
            f"접근성 판단 {_risk_label(alternative.expected_risk_level)}."
        )
    return lines or ["- 비교 가능한 다른 경로 후보가 없습니다."]


def _route_checked_at_lines(result: AccessibilityResult) -> list[str]:
    lines = [
        "- 전체 조회 시각: "
        + (_format_datetime(result.last_checked_at) or "확인된 기준 시각 없음")
        + "."
    ]
    latest_by_label: dict[str, datetime] = {}
    for source in result.evidence_sources:
        if source.success and source.checked_at is not None:
            label = _source_label(source.source_name)
            current = latest_by_label.get(label)
            if current is None or source.checked_at > current:
                latest_by_label[label] = source.checked_at
    lines.extend(
        f"- {label}: {_format_time(value)} 확인."
        for label, value in latest_by_label.items()
    )
    return lines


def _facility_type_label(facility_type: FacilityType) -> str:
    if facility_type == FacilityType.ELEVATOR:
        return "엘리베이터"
    if facility_type == FacilityType.ACCESSIBLE_RESTROOM:
        return "장애인화장실"
    return "접근성 시설"


def _station_label(station_name: str, line: str | None) -> str:
    station = station_name if station_name.endswith("역") else f"{station_name}역"
    return f"{line}호선 {station}" if line else station


def _status_label(status: FacilityStatus) -> str:
    return {
        FacilityStatus.AVAILABLE: "이용 가능",
        FacilityStatus.MAINTENANCE: "점검 중",
        FacilityStatus.UNAVAILABLE: "이용 불가",
        FacilityStatus.UNKNOWN: "상태 미확인",
    }[status]


def _risk_label(risk_level: str) -> str:
    return {
        "LOW": "비교적 낮음",
        "CAUTION": "주의 필요",
        "HIGH": "어려움 큼",
        "UNKNOWN": "확인 불가",
    }.get(risk_level, "확인 불가")


def _source_label(source_name: str) -> str:
    return {
        "shortest_route": "경로 정보",
        "elevator_status": "엘리베이터 운행상태",
        "elevator_info": "엘리베이터 위치 정보",
        "restroom": "장애인화장실 정보",
        "facility_info": "편의시설 정보",
    }.get(source_name, "시설 정보")


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    local = value.astimezone(timezone(timedelta(hours=9), "KST"))
    return (
        f"{local.year}년 {local.month}월 {local.day}일 "
        f"{local.hour:02d}:{local.minute:02d}"
    )


def _format_time(value: datetime) -> str:
    local = value.astimezone(timezone(timedelta(hours=9), "KST"))
    return f"{local.hour:02d}:{local.minute:02d}"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
