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
) -> AccessibilityQuestionResult:
    questions = _question_clarification_questions(reason, parsed)[:1]
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
            available_partial_info=available_partial_info,
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


def _question_clarification_questions(
    reason: str,
    parsed: ParsedAccessibilityQuestion,
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
    if reason == "station_line_mismatch":
        return [
            "입력한 역과 호선 조합이 역 데이터와 일치하지 않습니다. "
            "역명 또는 호선을 다시 확인해 주세요."
        ]
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
        partial_info.append("MCP 서버는 이전 대화의 경로를 저장하지 않습니다.")
    if reason == "missing_alternative_route":
        partial_info.append("출발역과 도착역이 확인되면 경로 후보를 비교할 수 있습니다.")
    if reason == "ambiguous_station":
        partial_info.append("호선이 확정되면 역별 엘리베이터 정보를 확인할 수 있습니다.")
    if reason == "station_line_mismatch":
        partial_info.append("역명과 호선 조합이 확정되면 접근성 정보를 조회할 수 있습니다.")
    if not partial_info:
        partial_info.append("역명과 이동 조건이 확정되면 접근성 체크를 제공할 수 있습니다.")
    return partial_info


def _question_clarification_message(
    *,
    reason: str,
    parsed: ParsedAccessibilityQuestion,
    questions: list[str],
    available_partial_info: list[str],
) -> str:
    if _is_facility_question(parsed):
        return _facility_question_clarification_message(
            reason=reason,
            parsed=parsed,
            questions=questions,
            available_partial_info=available_partial_info,
        )
    reason_text = _question_reason_text(reason, parsed)
    partial_lines = "\n".join(f"- {info}" for info in available_partial_info)
    primary_question = questions[0] if questions else "출발역과 도착역을 알려 주세요."
    return "\n".join(
        [
            "**한 가지만 더 알려주세요.**",
            f"**확인할 내용:** {_ensure_message_sentence(primary_question)}",
            reason_text,
            "",
            "### 확인 결과",
            partial_lines,
            "",
            "### 기준 시각",
            "- 공공 API 조회 전입니다. 질문 정보가 확정되면 기준 시각을 포함해 다시 안내합니다.",
            "",
            "### 주의사항",
            "> 역명과 이동 조건을 확인한 뒤 다시 조회하는 것을 권장합니다.",
            "- 엘리베이터와 역사 상태는 바뀔 수 있으니 출발 직전 재확인하세요.",
        ]
    )


def _question_reason_text(reason: str, parsed: ParsedAccessibilityQuestion) -> str:
    if parsed.place_mentions:
        return "장소명이 여러 역 후보와 연결되어 어느 역 기준인지 확정하지 못했습니다."
    if reason == "unsupported_intent":
        return "현재 질문에서 지원 가능한 접근성 조회 유형을 확정하지 못했습니다."
    if reason == "current_route_context":
        return "MCP 서버가 이전 대화의 경로를 저장하지 않아 출발역과 도착역을 다시 확인해야 합니다."
    if reason == "missing_alternative_route":
        return "대안 경로를 비교할 출발역 또는 도착역이 확인되지 않았습니다."
    if reason == "missing_mobility_profile":
        return "이동 조건이 없어 필요한 접근성 기준을 확정하지 못했습니다."
    if reason == "ambiguous_station":
        return "호선이 여러 개인 역이 있어 어느 호선 기준인지 확정하지 못했습니다."
    return "출발역 또는 도착역을 확정하지 못했습니다."


def _facility_question_clarification_message(
    *,
    reason: str,
    parsed: ParsedAccessibilityQuestion,
    questions: list[str],
    available_partial_info: list[str],
) -> str:
    if reason == "accessible_restroom_confirmation":
        reason_text = "일반 화장실과 장애인화장실 중 어느 시설인지 확인이 필요합니다."
    elif reason == "missing_facility_type":
        reason_text = "확인할 접근성 시설 종류가 지정되지 않았습니다."
    elif reason == "missing_facility_station":
        reason_text = "시설을 확인할 지하철역을 찾지 못했습니다."
    elif reason == "ambiguous_station":
        reason_text = "환승역은 호선별 시설 위치가 달라 호선 확인이 필요합니다."
    elif parsed.place_mentions:
        reason_text = "장소명이 여러 역 후보와 연결되어 어느 역 기준인지 확인이 필요합니다."
    else:
        reason_text = "시설 조회에 필요한 정보를 확정하지 못했습니다."
    partial_lines = [f"- {info}" for info in available_partial_info]
    primary_question = questions[0] if questions else "확인할 역과 시설을 알려 주세요."
    return "\n".join(
        [
            "**한 가지만 더 알려주세요.**",
            f"**확인할 내용:** {_ensure_message_sentence(primary_question)}",
            reason_text,
            "",
            "### 현재 확인된 정보",
            *(partial_lines or ["- 확인된 역 또는 시설 정보 없음."]),
            "",
            "### 주의사항",
            "> 역과 호선이 확정되면 공공데이터 조회 시각과 함께 안내합니다.",
            "- 엘리베이터와 역사 상태는 바뀔 수 있으니 출발 직전에 재확인하세요.",
        ]
    )


def _ensure_message_sentence(value: str) -> str:
    normalized = value.strip()
    if not normalized or normalized.endswith((".", "!", "?")):
        return normalized
    return normalized + "."


def _is_facility_question(parsed: ParsedAccessibilityQuestion) -> bool:
    if parsed.alternative_request_kind is not None:
        return parsed.alternative_request_kind == AlternativeRequestKind.STATION_FACILITY
    return parsed.facility_question_kind is not None or bool(parsed.facility_types)


def _place_candidate_questions(parsed: ParsedAccessibilityQuestion) -> list[str]:
    questions: list[str] = []
    for mention in parsed.place_mentions:
        if not mention.candidates:
            continue
        labels = _candidate_labels(mention)
        if len(mention.candidates) == 1:
            questions.append(
                f"{mention.place_name}은 {labels} 기준으로 확인할 수 있습니다. "
                "이 역 기준으로 확인하면 될까요?"
            )
            continue
        questions.append(
            f"{mention.place_name}은 {labels} 기준으로 확인할 수 있습니다. "
            "어느 역을 기준으로 확인할까요?"
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
