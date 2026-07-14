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


def test_facility_user_message_has_fixed_sections_and_caps_visible_facilities() -> None:
    facilities = [_facility(index, FacilityStatus.AVAILABLE) for index in range(7)]

    result = build_facility_question_result(
        station_name="삼성",
        line="2",
        question_kind=FacilityQuestionKind.LOCATION,
        service_results={FacilityType.ELEVATOR: _service_result(facilities)},
    )

    sections = [
        "확인 결과:",
        "### 역·호선",
        "### 시설 정보",
        "### 기준 시각",
        "### 주의사항",
    ]
    indexes = [result.user_message.index(section) for section in sections]
    assert indexes == sorted(indexes)
    assert "| 시설 | 위치 | 상태 |" in result.user_message
    assert result.user_message.count("| 엘리베이터 | 출구") == 5
    assert "그 외 2건" in result.user_message
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
    assert "확인 결과: 확인 불가" in result.user_message
    assert "위치 정보는 확인됐지만 현재 운행 또는 이용 상태" in result.user_message
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
    assert "확인 결과: 주의 필요" in result.user_message
    assert "이용 가능한 시설과 점검 또는 이용 불가 시설" in result.user_message
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
