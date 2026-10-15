from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.accessibility import FacilityAnswerState, FacilityQuestionKind
from app.schemas.common import CacheStatus, DataSourceMeta, FailedSource, ResponseStatus
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.services.facility_question import build_facility_question_result
from app.services.types import ServiceResult

CHECKED_AT = datetime(2026, 7, 10, 5, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([FacilityStatus.AVAILABLE], FacilityAnswerState.AVAILABLE),
        ([FacilityStatus.MAINTENANCE], FacilityAnswerState.MAINTENANCE),
        ([FacilityStatus.UNAVAILABLE], FacilityAnswerState.UNAVAILABLE),
        ([FacilityStatus.UNKNOWN], FacilityAnswerState.UNKNOWN),
        (
            [FacilityStatus.AVAILABLE, FacilityStatus.MAINTENANCE],
            FacilityAnswerState.MIXED,
        ),
    ],
)
def test_facility_question_aggregates_statuses(
    statuses: list[FacilityStatus],
    expected: FacilityAnswerState,
) -> None:
    result = build_facility_question_result(
        station_name="강남",
        line="2",
        question_kind=FacilityQuestionKind.STATUS,
        service_results={
            FacilityType.ELEVATOR: _service_result(
                [_facility(index, status) for index, status in enumerate(statuses)]
            )
        },
    )

    assert result.items[0].answer_state == expected
    assert result.last_checked_at == CHECKED_AT
    assert result.evidence_sources
    assert "기준 시각" in result.user_message


def test_successful_empty_facility_query_is_not_found_not_failure() -> None:
    result = build_facility_question_result(
        station_name="강남",
        line="2",
        question_kind=FacilityQuestionKind.EXISTENCE,
        service_results={FacilityType.ELEVATOR: _service_result([])},
    )

    assert result.status == ResponseStatus.SUCCESS
    assert result.items[0].answer_state == FacilityAnswerState.NOT_FOUND
    assert "현재 공공데이터에서 시설을 확인하지 못했습니다" in result.user_message
    assert "시설이 없습니다" not in result.user_message


def test_failed_facility_query_is_unknown_and_structured_failure() -> None:
    service_result = ServiceResult[list[AccessibleFacility]](
        value=[],
        data_sources=[_source(success=False)],
        failed_sources=[FailedSource(source_name="elevator_status", reason="timeout")],
        limitations=["승강기 실시간 상태를 확인하지 못했습니다."],
    )

    result = build_facility_question_result(
        station_name="강남",
        line="2",
        question_kind=FacilityQuestionKind.STATUS,
        service_results={FacilityType.ELEVATOR: service_result},
    )

    assert result.status == ResponseStatus.FAILED
    assert result.items[0].answer_state == FacilityAnswerState.UNKNOWN
    assert result.failed_sources[0].source_name == "elevator_status"
    assert "공공데이터 조회 실패" in result.user_message


def test_combined_facility_query_preserves_partial_success() -> None:
    elevator_result = _service_result([_facility(1, FacilityStatus.AVAILABLE)])
    restroom_result = ServiceResult[list[AccessibleFacility]](
        value=[],
        data_sources=[_source(source_name="restroom", success=False)],
        failed_sources=[FailedSource(source_name="restroom", reason="timeout")],
    )

    result = build_facility_question_result(
        station_name="삼성",
        line="2",
        question_kind=FacilityQuestionKind.OVERVIEW,
        service_results={
            FacilityType.ELEVATOR: elevator_result,
            FacilityType.ACCESSIBLE_RESTROOM: restroom_result,
        },
    )

    assert result.status == ResponseStatus.PARTIAL
    assert [item.answer_state for item in result.items] == [
        FacilityAnswerState.AVAILABLE,
        FacilityAnswerState.UNKNOWN,
    ]
    assert "엘리베이터" in result.user_message
    assert "장애인화장실" in result.user_message


def test_facility_user_message_answers_in_the_title_and_lists_every_facility() -> None:
    facilities = [_facility(index, FacilityStatus.AVAILABLE) for index in range(7)]

    result = build_facility_question_result(
        station_name="삼성",
        line="2",
        question_kind=FacilityQuestionKind.LOCATION,
        service_results={FacilityType.ELEVATOR: _service_result(facilities)},
    )

    # 첫 줄이 묻는 말에 답하고, 질문을 되풀이하는 역·호선 구역은 두지 않는다.
    assert result.user_message.startswith("**2호선 삼성역 엘리베이터는 모두 운행 중입니다.**\n\n")
    assert "확인 결과:" not in result.user_message
    assert "### 역·호선" not in result.user_message
    sections = ["### 시설 정보", "### 기준 시각", "### 주의사항"]
    indexes = [result.user_message.index(section) for section in sections]
    assert indexes == sorted(indexes)
    assert "| 시설 | 위치 | 상태 |" in result.user_message
    # 시설 질문은 시설 목록이 곧 답이라 일곱 대를 모두 싣는다.
    assert result.user_message.count("| 엘리베이터 | 출구") == 7
    assert "그 외" not in result.user_message
    # 출처 시각이 하나면 조회 시각 한 줄만 쓴다.
    assert "- 조회 시각: 2026년 7월 10일 14:30." in result.user_message
    assert "전체 조회 시각" not in result.user_message
    assert len(result.items[0].facilities) == 7
    assert "risk_level" not in result.user_message
    assert "confidence_level" not in result.user_message


def test_static_elevator_location_does_not_claim_operational_availability() -> None:
    result = build_facility_question_result(
        station_name="강남",
        line="2",
        question_kind=FacilityQuestionKind.STATUS,
        service_results={
            FacilityType.ELEVATOR: _service_result(
                [
                    _facility(
                        1,
                        FacilityStatus.AVAILABLE,
                        source_name="elevator_info",
                    )
                ]
            )
        },
    )

    assert result.items[0].answer_state == FacilityAnswerState.UNKNOWN
    assert result.user_message.startswith(
        "**2호선 강남역 엘리베이터 위치는 확인했지만 지금 운행 상태는 확인하지 못했습니다.**"
    )
    assert "운행 상태 미확인" in result.user_message
    assert "| 엘리베이터 | 출구 1 | 이용 가능 |" not in result.user_message


def test_mixed_elevator_status_is_explained_and_cross_source_row_is_hidden() -> None:
    result = build_facility_question_result(
        station_name="강남",
        line="2",
        question_kind=FacilityQuestionKind.STATUS,
        service_results={
            FacilityType.ELEVATOR: _service_result(
                [
                    _facility(1, FacilityStatus.AVAILABLE, location="1번 출구"),
                    _facility(2, FacilityStatus.MAINTENANCE, location="8번 출구"),
                    _facility(
                        3,
                        FacilityStatus.AVAILABLE,
                        source_name="elevator_info",
                        location="1번 출구",
                    ),
                ]
            )
        },
    )

    assert result.items[0].answer_state == FacilityAnswerState.MIXED
    assert result.user_message.startswith(
        "**2호선 강남역 엘리베이터 중 점검 중이거나 이용할 수 없는 곳이 있습니다.**"
    )
    assert result.user_message.count("1번 출구") == 1
    assert "8번 출구" in result.user_message
    assert "점검 중" in result.user_message


def _facility(
    index: int,
    status: FacilityStatus,
    *,
    source_name: str = "elevator_status",
    location: str | None = None,
) -> AccessibleFacility:
    return AccessibleFacility(
        facility_id=f"EL-{index}",
        facility_name="엘리베이터",
        station_name="강남",
        line="2",
        facility_type=FacilityType.ELEVATOR,
        status=status,
        location_description=location or f"출구 {index}",
        source_name=source_name,
    )


def _source(
    *,
    source_name: str = "elevator_status",
    success: bool = True,
) -> DataSourceMeta:
    return DataSourceMeta(
        source_name=source_name,
        source_type="fixture",
        fetched_at=CHECKED_AT,
        cache_status=CacheStatus.MISS,
        success=success,
        error_message=None if success else "request_failed",
    )


def _service_result(
    facilities: list[AccessibleFacility],
) -> ServiceResult[list[AccessibleFacility]]:
    return ServiceResult(value=facilities, data_sources=[_source()])


def test_restroom_answer_has_no_elevator_notice_and_tidy_location() -> None:
    restroom = AccessibleFacility(
        facility_id="WC-1",
        station_name="강남",
        line="2",
        facility_type=FacilityType.ACCESSIBLE_RESTROOM,
        status=FacilityStatus.AVAILABLE,
        location_description="B1 대합실,1번 출구 방향",
        inside_gate=True,
        open_time="05:30-24:00",
        source_name="restroom",
    )

    result = build_facility_question_result(
        station_name="강남",
        line="2",
        question_kind=FacilityQuestionKind.EXISTENCE,
        service_results={
            FacilityType.ACCESSIBLE_RESTROOM: ServiceResult(
                value=[restroom],
                data_sources=[_source(source_name="restroom")],
            )
        },
    )

    assert result.user_message.startswith("**2호선 강남역 장애인화장실을 이용할 수 있습니다.**")
    assert "| 장애인화장실 | B1 대합실, 1번 출구 방향 (개찰구 안) · 운영 05:30-24:00 |" in (
        result.user_message
    )
    assert "엘리베이터" not in result.user_message
    assert "엘리베이터" not in result.safety_notice


def test_title_names_the_facility_that_needs_attention_first() -> None:
    result = build_facility_question_result(
        station_name="강남",
        line="2",
        question_kind=FacilityQuestionKind.OVERVIEW,
        service_results={
            FacilityType.ELEVATOR: _service_result([_facility(1, FacilityStatus.AVAILABLE)]),
            FacilityType.ACCESSIBLE_RESTROOM: ServiceResult(
                value=[],
                data_sources=[_source(source_name="restroom")],
            ),
        },
    )

    assert result.user_message.startswith(
        "**2호선 강남역 장애인화장실은 현재 공공데이터에서 확인되지 않습니다.**"
    )
    assert "| 엘리베이터 | 출구 1 | 이용 가능 |" in result.user_message


def test_cached_elevator_location_time_does_not_split_the_checked_time() -> None:
    from datetime import timedelta

    status = _source()
    location = _source(source_name="elevator_info").model_copy(
        update={"fetched_at": CHECKED_AT - timedelta(minutes=12)}
    )
    result = build_facility_question_result(
        station_name="강남",
        line="2",
        question_kind=FacilityQuestionKind.STATUS,
        service_results={
            FacilityType.ELEVATOR: ServiceResult(
                value=[_facility(1, FacilityStatus.AVAILABLE)],
                data_sources=[status, location],
            )
        },
    )

    # 위치는 자주 바뀌지 않으니 캐시 시각이 조금 일러도 조회 시각 한 줄로 쓴다.
    assert "- 조회 시각: 2026년 7월 10일 14:30." in result.user_message
    assert "엘리베이터 위치 정보:" not in result.user_message


def test_platform_position_is_labelled_in_the_facility_table() -> None:
    result = build_facility_question_result(
        station_name="강남",
        line="2",
        question_kind=FacilityQuestionKind.STATUS,
        service_results={
            FacilityType.ELEVATOR: _service_result(
                [_facility(1, FacilityStatus.AVAILABLE, location="교대 방면3-4")]
            )
        },
    )

    # 경로 답변 표와 같이 방면·칸 번호 위치는 승강장 엘리베이터라고 밝힌다.
    assert "| 엘리베이터 | 승강장 교대 방면3-4 | 이용 가능 |" in result.user_message
