from __future__ import annotations

from app.schemas.accessibility import (
    AccessibilityQuestionResult,
    AlternativeRequestKind,
    ParsedAccessibilityQuestion,
    QuestionIntent,
)
from app.schemas.common import ResponseStatus
from app.schemas.facility import FacilityType
from app.services.result_metadata import dedupe_strings
from app.services.station_context import (
    StationLookupContext,
    resolve_station_context,
)
from app.services.station_service import StationService

SERVICE_SCOPE_TEXT = (
    "이 서비스는 지하철 경로의 접근성과 역 엘리베이터·장애인화장실 정보를 확인합니다."
)
STATION_COVERAGE_TEXT = "현재는 서울교통공사 1~8호선과 9호선 역만 찾을 수 있습니다."


def question_clarification_reason(
    *,
    intent: QuestionIntent,
    parsed: ParsedAccessibilityQuestion,
    station_service: StationService,
) -> str | None:
    if intent == "alternative_request":
        return _alternative_clarification_reason(parsed, station_service)
    if intent == "facility_status":
        return _facility_clarification_reason(parsed, station_service)
    if intent != "trip_accessibility":
        return "unsupported_intent"
    if parsed.origin is None or parsed.destination is None:
        return "missing_station"
    if "mobility_profile" in parsed.missing_fields:
        return "missing_mobility_profile"

    origin_context = resolve_station_context(station_service, parsed.origin)
    destination_context = resolve_station_context(
        station_service,
        parsed.destination,
    )
    if origin_context.needs_clarification or destination_context.needs_clarification:
        if _has_unverified_station(origin_context, destination_context):
            return "station_not_in_coverage"
        return _station_context_clarification_reason(
            origin_context,
            destination_context,
        )
    return None


def build_question_clarification_result(
    *,
    question: str,
    intent: QuestionIntent,
    parsed: ParsedAccessibilityQuestion,
    reason: str,
    station_service: StationService,
) -> AccessibilityQuestionResult:
    questions = _question_clarification_questions(
        reason,
        parsed,
        station_question=_station_clarification_question(reason, parsed, station_service),
    )[:1]
    available_partial_info = _question_available_partial_info(reason, parsed)
    return AccessibilityQuestionResult(
        question=question,
        status=ResponseStatus.NEEDS_CLARIFICATION,
        intent=intent,
        parsed=parsed.model_copy(
            update={
                "missing_fields": dedupe_strings([*parsed.missing_fields, reason]),
            }
        ),
        result=None,
        user_message=_question_clarification_message(
            reason=reason,
            parsed=parsed,
            questions=questions,
        ),
        clarification_needed=True,
        questions=questions,
        available_partial_info=available_partial_info,
    )


def _alternative_clarification_reason(
    parsed: ParsedAccessibilityQuestion,
    station_service: StationService,
) -> str | None:
    if parsed.alternative_request_kind == AlternativeRequestKind.CURRENT_ROUTE:
        return "current_route_context"
    if parsed.alternative_request_kind == AlternativeRequestKind.STATION_FACILITY:
        return _facility_clarification_reason(parsed, station_service)
    if parsed.origin is None or parsed.destination is None:
        return "missing_alternative_route"
    if "mobility_profile" in parsed.missing_fields:
        return "missing_mobility_profile"

    origin_context = resolve_station_context(station_service, parsed.origin)
    destination_context = resolve_station_context(
        station_service,
        parsed.destination,
    )
    if origin_context.needs_clarification or destination_context.needs_clarification:
        return _station_context_clarification_reason(
            origin_context,
            destination_context,
        )
    return None


def _facility_clarification_reason(
    parsed: ParsedAccessibilityQuestion,
    station_service: StationService,
) -> str | None:
    if "accessible_restroom_confirmation" in parsed.missing_fields:
        return "accessible_restroom_confirmation"
    if not parsed.facility_types:
        return "missing_facility_type"
    if parsed.target_station is None:
        return "missing_facility_station"
    target_context = resolve_station_context(
        station_service,
        parsed.target_station,
        explicit_line=parsed.target_line,
    )
    if target_context.needs_clarification:
        if _has_unverified_station(target_context):
            return "station_not_in_coverage"
        return _station_context_clarification_reason(target_context)
    return None


def _station_context_clarification_reason(
    *contexts: StationLookupContext,
) -> str:
    if any(
        context.needs_clarification
        and context.line is not None
        and context.candidate_lines
        and context.line not in context.candidate_lines
        for context in contexts
    ):
        return "station_line_mismatch"
    return "ambiguous_station"


def _station_clarification_question(
    reason: str,
    parsed: ParsedAccessibilityQuestion,
    station_service: StationService,
) -> str | None:
    if reason not in {"ambiguous_station", "station_line_mismatch"}:
        return None
    if _is_facility_question(parsed):
        if parsed.target_station is None:
            return None
        contexts = [
            resolve_station_context(
                station_service,
                parsed.target_station,
                explicit_line=parsed.target_line,
            )
        ]
    else:
        contexts = [
            resolve_station_context(station_service, station)
            for station in (parsed.origin, parsed.destination)
            if station is not None
        ]
    for context in contexts:
        if context.needs_clarification and context.clarification_message:
            return context.clarification_message
    return None


def _question_clarification_questions(
    reason: str,
    parsed: ParsedAccessibilityQuestion,
    *,
    station_question: str | None = None,
) -> list[str]:
    place_questions = _place_candidate_questions(parsed)
    if place_questions:
        if _is_facility_question(parsed):
            return dedupe_strings(place_questions)
        questions = list(place_questions)
        if parsed.origin is None:
            questions.append("출발역을 지하철역 이름 기준으로 알려 주세요.")
        if parsed.destination is None:
            questions.append("도착역을 지하철역 이름 기준으로 알려 주세요.")
        if "mobility_profile" in parsed.missing_fields:
            questions.append("휠체어, 유모차, 계단 이용 불가 등 이동 조건을 알려 주세요.")
        return dedupe_strings(questions)

    if reason == "accessible_restroom_confirmation":
        return ["장애인화장실 정보를 확인할까요?"]
    if reason == "missing_facility_type":
        return ["엘리베이터와 장애인화장실 중 어떤 시설을 확인할까요?"]
    if reason == "missing_facility_station":
        return ["시설을 확인할 지하철역 이름을 알려 주세요."]
    if reason == "current_route_context":
        return [
            "확인할 경로의 출발역과 도착역을 알려 주세요.",
            "휠체어, 유모차, 계단 이용 불가 등 이동 조건도 함께 알려 주세요.",
        ]
    if reason == "missing_alternative_route":
        return [
            "대안 경로를 확인할 출발역과 도착역을 알려 주세요.",
            "필요한 경우 휠체어, 유모차 또는 엘리베이터 필수 조건도 알려 주세요.",
        ]
    if reason == "unsupported_intent":
        return [
            "출발역과 도착역을 함께 알려 주세요.",
            "휠체어, 유모차, 계단 이용 불가 등 이동 조건을 알려 주세요.",
        ]
    if reason == "missing_mobility_profile":
        return [
            "휠체어, 유모차, 보행약자 중 어떤 이동 조건인지 알려 주세요.",
            "계단이나 에스컬레이터를 사용할 수 있는지도 알려 주세요.",
        ]
    if station_question:
        return [station_question]
    if reason == "station_line_mismatch":
        return [
            "입력한 역과 호선 조합이 역 데이터와 일치하지 않습니다. "
            "역명 또는 호선을 다시 확인해 주세요."
        ]
    if reason == "station_not_in_coverage":
        return ["현재 검증된 역 목록에 있는 역명과 호선을 다시 알려 주세요."]
    if reason == "ambiguous_station":
        if _is_facility_question(parsed):
            return [
                "여러 호선이 있는 역은 '9호선 고속터미널'처럼 호선을 함께 알려 주세요."
            ]
        return [
            "여러 호선이 있는 역은 '9호선 고속터미널'처럼 호선을 함께 알려 주세요.",
            "출발역과 도착역을 지하철역 이름 기준으로 다시 확인해 주세요.",
        ]
    if parsed.station_mentions:
        return [
            "출발역과 도착역을 모두 알려 주세요.",
            "휠체어, 유모차, 계단 이용 불가 등 이동 조건을 함께 알려 주세요.",
        ]
    return [
        "출발역과 도착역을 지하철역 이름 기준으로 알려 주세요.",
        "휠체어, 유모차, 계단 이용 불가 등 이동 조건을 함께 알려 주세요.",
    ]


def _question_available_partial_info(
    reason: str,
    parsed: ParsedAccessibilityQuestion,
) -> list[str]:
    partial_info: list[str] = []
    if parsed.station_mentions:
        partial_info.append("확인된 역 후보: " + ", ".join(parsed.station_mentions))
    partial_info.extend(_place_candidate_summaries(parsed))
    if _is_facility_question(parsed) and parsed.facility_types:
        labels = [
            "엘리베이터"
            if facility_type == FacilityType.ELEVATOR
            else "장애인화장실"
            for facility_type in parsed.facility_types
        ]
        partial_info.append("확인 요청 시설: " + ", ".join(labels))
    if reason == "unsupported_intent":
        partial_info.append(
            "현재 질문에서 지원 가능한 접근성 조회 유형을 확정하지 못했습니다."
        )
    if reason == "current_route_context":
        partial_info.append("이전 대화의 경로는 이어받지 않습니다.")
    if reason == "missing_alternative_route":
        partial_info.append("출발역과 도착역이 확인되면 경로 후보를 비교할 수 있습니다.")
    if reason == "ambiguous_station":
        partial_info.append("호선이 확정되면 역별 엘리베이터 정보를 확인할 수 있습니다.")
    if reason == "station_line_mismatch":
        partial_info.append("역명과 호선 조합이 확정되면 접근성 정보를 조회할 수 있습니다.")
    if reason == "station_not_in_coverage":
        partial_info.append("질문에서 현재 검증된 역·호선 조합을 확인하지 못했습니다.")
    if not partial_info:
        partial_info.append("역명과 이동 조건이 확정되면 접근성 체크를 제공할 수 있습니다.")
    return partial_info


def _question_clarification_message(
    *,
    reason: str,
    parsed: ParsedAccessibilityQuestion,
    questions: list[str],
) -> str:
    # 되묻는 답변은 물을 내용과, 질문만으로 이유가 드러나지 않을 때 그 이유 한 줄만 쓴다.
    # 아직 아무것도 조회하지 않았으니 확인 결과·기준 시각·주의사항을 붙이지 않는다(답변 계약 5).
    # 질문에서 알아낸 역·시설은 available_partial_info로 따로 준다.
    facility = _is_facility_question(parsed)
    default_question = (
        "확인할 역과 시설을 알려 주세요." if facility else "출발역과 도착역을 알려 주세요."
    )
    reason_text = (
        _facility_reason_text(reason, parsed) if facility else _question_reason_text(reason, parsed)
    )
    lines = [_ensure_message_sentence(questions[0] if questions else default_question)]
    if reason_text:
        lines.append(reason_text)
    return "\n".join(lines)


def _question_reason_text(reason: str, parsed: ParsedAccessibilityQuestion) -> str | None:
    if parsed.place_mentions:
        return "장소명이 여러 역 후보와 연결되어 어느 역 기준인지 확정하지 못했습니다."
    if reason == "missing_station" and parsed.station_mentions:
        # 역 하나는 찾았는데 나머지를 못 찾았다면 대개 역 목록 밖의 역이다.
        return f"질문의 역 중 일부를 찾지 못했습니다. {STATION_COVERAGE_TEXT}"
    if reason == "unsupported_intent":
        return SERVICE_SCOPE_TEXT
    if reason == "current_route_context":
        return "이전 대화의 경로는 이어받지 않아 출발역과 도착역을 다시 알려 주셔야 합니다."
    if reason == "missing_mobility_profile":
        return "이동 조건에 따라 확인할 동선이 달라집니다."
    if reason == "station_not_in_coverage":
        return STATION_COVERAGE_TEXT
    return None


def _facility_reason_text(reason: str, parsed: ParsedAccessibilityQuestion) -> str | None:
    if reason == "accessible_restroom_confirmation":
        return "일반 화장실과 장애인화장실 중 어느 시설인지 확인이 필요합니다."
    if reason == "ambiguous_station":
        return "환승역은 호선별 시설 위치가 달라 호선 확인이 필요합니다."
    if parsed.place_mentions:
        return "장소명이 여러 역 후보와 연결되어 어느 역 기준인지 확인이 필요합니다."
    if reason == "station_not_in_coverage":
        return STATION_COVERAGE_TEXT
    return None


def _with_topic(name: str) -> str:
    # 영문 장소명(DDP, KTX)은 한글로 읽을 때 받침이 없는 경우가 많아 "는"을 붙인다.
    last = name.strip()[-1:]
    has_final = "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0
    return f"{name}{'은' if has_final else '는'}"


def _ensure_message_sentence(value: str) -> str:
    normalized = value.strip()
    if not normalized or normalized.endswith((".", "!", "?")):
        return normalized
    return normalized + "."


def _is_facility_question(parsed: ParsedAccessibilityQuestion) -> bool:
    if parsed.alternative_request_kind is not None:
        return parsed.alternative_request_kind == AlternativeRequestKind.STATION_FACILITY
    return parsed.facility_question_kind is not None or bool(parsed.facility_types)


def _has_unverified_station(*contexts: StationLookupContext) -> bool:
    return any(
        context.needs_clarification and context.station_id is None and not context.candidate_lines
        for context in contexts
    )


def _place_candidate_questions(parsed: ParsedAccessibilityQuestion) -> list[str]:
    questions: list[str] = []
    for mention in parsed.place_mentions:
        if not mention.candidates:
            continue
        labels = _candidate_labels(mention)
        place = _with_topic(mention.place_name)
        if len(mention.candidates) == 1:
            questions.append(
                f"{place} {labels} 기준으로 확인할 수 있습니다. 이 역 기준으로 확인하면 될까요?"
            )
            continue
        questions.append(
            f"{place} {labels} 기준으로 확인할 수 있습니다. 어느 역을 기준으로 확인할까요?"
        )
    return questions


def _place_candidate_summaries(parsed: ParsedAccessibilityQuestion) -> list[str]:
    summaries: list[str] = []
    for mention in parsed.place_mentions:
        labels = _candidate_labels(mention)
        if labels:
            summaries.append(f"{mention.place_name} 후보: {labels}")
    return summaries


def _candidate_labels(mention: object) -> str:
    candidates = getattr(mention, "candidates", [])
    labels = [candidate.label for candidate in candidates]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return " 또는 ".join(labels)
