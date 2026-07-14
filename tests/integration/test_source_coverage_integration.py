from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import AppMode, Settings
from app.schemas.accessibility import FacilityAnswerState, MobilityProfile
from app.schemas.common import DataSourceMeta, ResponseStatus, SourceCoverageStatus
from app.schemas.route import RouteCandidate, RouteSegment
from app.services.accessibility_service import AccessibilityService
from app.services.types import ServiceResult


class _LineNineRouteService:
    async def get_route_candidates(
        self,
        origin: str,
        destination: str,
    ) -> ServiceResult[list[RouteCandidate]]:
        return ServiceResult(
            value=[
                RouteCandidate(
                    route_id="line9-direct",
                    origin=origin,
                    destination=destination,
                    transfer_count=0,
                    stations=[origin, destination],
                    segments=[
                        RouteSegment(
                            from_station=origin,
                            to_station=destination,
                            line="9호선",
                        )
                    ],
                )
            ],
            data_sources=[
                DataSourceMeta(
                    source_name="shortest_route",
                    source_type="public_api",
                    fetched_at=datetime(2026, 7, 13, tzinfo=UTC),
                )
            ],
        )


async def test_natural_language_facility_answer_explains_unsupported_source() -> None:
    service = AccessibilityService(
        settings=Settings(_env_file=None, app_mode=AppMode.LIVE),
    )

    response = await service.answer_accessibility_question(
        "9호선 여의도역 엘리베이터 상태 알려줘"
    )

    assert response.status == ResponseStatus.PARTIAL
    assert response.facility_result is not None
    assert response.facility_result.items[0].answer_state == FacilityAnswerState.UNSUPPORTED
    assert all(
        source.coverage_status == SourceCoverageStatus.UNSUPPORTED
        for source in response.facility_result.evidence_sources
    )
    assert "제공 범위 밖" in response.user_message
    assert "시설이 없다는 뜻은 아닙니다" in response.user_message
    assert "조회 실패" not in response.user_message


async def test_trip_answer_does_not_describe_unsupported_source_as_no_elevator() -> None:
    settings = Settings(_env_file=None, app_mode=AppMode.LIVE)
    service = AccessibilityService(
        settings=settings,
        route_service=_LineNineRouteService(),  # type: ignore[arg-type]
    )

    result = await service.check_accessible_trip(
        "9호선 여의도",
        "9호선 고속터미널",
        MobilityProfile(
            wheelchair=True,
            can_use_stairs=False,
            can_use_escalator=False,
            need_elevator_only=True,
        ),
    )

    assert result.status == ResponseStatus.PARTIAL
    assert result.failed_sources == []
    assert {
        reason.code for reason in result.risk_reasons
    } == {"elevator_source_unsupported"}
    assert "제공 범위 밖" in result.user_message
    assert "엘리베이터 정보를 찾지 못했습니다" not in result.user_message
    assert all(check.operator == "seoul_metro_line9" for check in result.accessibility_checks)
    assert all(
        check.elevator_answer_state == FacilityAnswerState.UNSUPPORTED
        for check in result.accessibility_checks
    )
    assert "공공데이터 조회 결과 엘리베이터 미확인" not in result.user_message
    assert "엘리베이터 정보 확인 실패" not in result.user_message
