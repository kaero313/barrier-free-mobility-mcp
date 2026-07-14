from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import AppMode, Settings
from app.schemas.accessibility import FacilityAnswerState, FacilityQuestionKind
from app.schemas.common import (
    CacheStatus,
    DataSourceMeta,
    ResponseStatus,
    SourceCoverageStatus,
)
from app.schemas.facility import AccessibleFacility, FacilityType
from app.services import client_factory
from app.services.facility_question import build_facility_question_result
from app.services.facility_service import FacilityService
from app.services.source_coverage import evaluate_source_coverage
from app.services.station_context import resolve_station_context
from app.services.station_service import StationService
from app.services.types import ServiceResult


def test_source_coverage_distinguishes_line_nine_operating_segments() -> None:
    station_service = StationService()
    yeouido = resolve_station_context(station_service, "9호선 여의도")
    bongeunsa = resolve_station_context(station_service, "9호선 봉은사")

    unsupported = evaluate_source_coverage(
        "elevator_status",
        yeouido,
        app_mode=AppMode.LIVE,
    )
    supported = evaluate_source_coverage(
        "elevator_status",
        bongeunsa,
        app_mode=AppMode.LIVE,
    )

    assert yeouido.operator == "seoul_metro_line9"
    assert bongeunsa.operator == "seoul_metro"
    assert unsupported.status == SourceCoverageStatus.UNSUPPORTED
    assert "9호선 여의도역" in (unsupported.note or "")
    assert supported.status == SourceCoverageStatus.SUPPORTED


def test_mock_mode_keeps_fixture_coverage_available() -> None:
    context = resolve_station_context(StationService(), "9호선 여의도")

    decision = evaluate_source_coverage(
        "elevator_status",
        context,
        app_mode=AppMode.MOCK,
    )

    assert decision.status == SourceCoverageStatus.SUPPORTED


async def test_live_unsupported_source_is_not_called(monkeypatch) -> None:
    def unexpected_client(_settings):
        raise AssertionError("unsupported source must not create an API client")

    monkeypatch.setattr(client_factory, "elevator_status_client", unexpected_client)
    monkeypatch.setattr(client_factory, "elevator_info_client", unexpected_client)
    service = FacilityService(
        settings=Settings(_env_file=None, app_mode=AppMode.LIVE),
    )

    result = await service.get_elevator_status("9호선 여의도")

    assert result.value == []
    assert result.failed_sources == []
    assert {source.source_name for source in result.data_sources} == {
        "elevator_status",
        "elevator_info",
    }
    assert all(
        source.coverage_status == SourceCoverageStatus.UNSUPPORTED
        for source in result.data_sources
    )


def test_unsupported_facility_answer_is_not_not_found_or_failure() -> None:
    checked_at = datetime(2026, 7, 13, tzinfo=UTC)
    source = DataSourceMeta(
        source_name="elevator_status",
        source_type="public_api",
        fetched_at=checked_at,
        cache_status=CacheStatus.BYPASS,
        success=False,
        coverage_status=SourceCoverageStatus.UNSUPPORTED,
        coverage_note=(
            "9호선 여의도역은 서울교통공사 승강기 가동현황의 제공 범위 밖입니다."
        ),
    )

    result = build_facility_question_result(
        station_name="여의도",
        line="9",
        question_kind=FacilityQuestionKind.STATUS,
        service_results={
            FacilityType.ELEVATOR: ServiceResult[list[AccessibleFacility]](
                value=[],
                data_sources=[source],
                limitations=[source.coverage_note or ""],
            )
        },
    )

    assert result.status == ResponseStatus.PARTIAL
    assert result.items[0].answer_state == FacilityAnswerState.UNSUPPORTED
    assert result.last_checked_at is None
    assert "데이터 소스 미지원" in result.user_message
    assert "시설이 없다는 뜻은 아닙니다" in result.user_message
    assert "공공데이터 미확인" not in result.user_message
