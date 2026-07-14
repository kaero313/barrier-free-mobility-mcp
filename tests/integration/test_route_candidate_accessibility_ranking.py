from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import AppMode, Settings
from app.schemas.accessibility import MobilityProfile
from app.schemas.common import DataSourceMeta, FailedSource, ResponseStatus
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.schemas.route import RouteCandidate, RouteSegment
from app.services.accessibility_service import AccessibilityService
from app.services.types import ServiceResult


class _CandidateRouteService:
    async def get_route_candidates(
        self,
        origin: str,
        destination: str,
    ) -> ServiceResult[list[RouteCandidate]]:
        return ServiceResult(
            value=[
                RouteCandidate(
                    route_id="fast-via-gyodae",
                    origin=origin,
                    destination=destination,
                    segments=[
                        RouteSegment(
                            from_station=origin,
                            to_station="교대",
                            line="2호선",
                        ),
                        RouteSegment(
                            from_station="교대",
                            to_station=destination,
                            line="3호선",
                        ),
                    ],
                    transfer_count=1,
                    estimated_minutes=10,
                    stations=[origin, "교대", destination],
                    raw_summary="교대 환승 빠른 경로",
                ),
                RouteCandidate(
                    route_id="slower-direct",
                    origin=origin,
                    destination=destination,
                    segments=[
                        RouteSegment(
                            from_station=origin,
                            to_station=destination,
                            line="2호선",
                        )
                    ],
                    transfer_count=0,
                    estimated_minutes=20,
                    stations=[origin, destination],
                    raw_summary="2호선 직행 경로",
                ),
            ],
            data_sources=[_source("shortest_route")],
        )


class _CandidateFacilityService:
    async def get_station_facilities(
        self,
        station: str,
        line: str | None = None,
    ) -> ServiceResult[list[AccessibleFacility]]:
        return ServiceResult(value=[], data_sources=[_source("facility_info")])

    async def get_elevator_status(
        self,
        station: str,
        line: str | None = None,
    ) -> ServiceResult[list[AccessibleFacility]]:
        if station == "교대":
            return ServiceResult(
                value=[],
                data_sources=[
                    _source("elevator_status").model_copy(
                        update={"success": False, "error_message": "request failed"}
                    )
                ],
                failed_sources=[
                    FailedSource(source_name="elevator_status", reason="request failed")
                ],
                limitations=["교대역 승강기 상태를 확인하지 못했습니다."],
            )
        return ServiceResult(
            value=[
                AccessibleFacility(
                    facility_id=f"{station}-EL-1",
                    station_name=station,
                    line=line or "2",
                    facility_type=FacilityType.ELEVATOR,
                    status=FacilityStatus.AVAILABLE,
                    location_description="출입구 연결 엘리베이터",
                    source_name="elevator_status",
                )
            ],
            data_sources=[_source("elevator_status")],
        )

    async def get_accessible_restroom(
        self,
        station: str,
        line: str | None = None,
    ) -> ServiceResult[list[AccessibleFacility]]:
        return ServiceResult(value=[], data_sources=[_source("restroom")])


async def test_service_ranks_candidates_after_scoped_accessibility_evaluation() -> None:
    service = AccessibilityService(
        settings=Settings(_env_file=None, app_mode=AppMode.MOCK),
        route_service=_CandidateRouteService(),  # type: ignore[arg-type]
        facility_service=_CandidateFacilityService(),  # type: ignore[arg-type]
    )

    result = await service.check_accessible_trip(
        "2호선 홍대입구",
        "2호선 삼성",
        MobilityProfile(
            wheelchair=True,
            can_use_stairs=False,
            can_use_escalator=False,
            need_elevator_only=True,
        ),
    )

    assert result.selected_route is not None
    assert result.selected_route.route_id == "slower-direct"
    assert result.route_candidates[0].route_id == "slower-direct"
    assert result.status == ResponseStatus.SUCCESS
    assert result.risk_level == "CAUTION"
    assert result.failed_sources == []
    assert all("교대" not in limitation for limitation in result.limitations)
    assert result.alternatives[0].route is not None
    assert result.alternatives[0].route.route_id == "fast-via-gyodae"
    assert result.alternatives[0].expected_risk_level == "UNKNOWN"
    assert result.user_message_summary.judgement == "주의 필요"
    assert "엘리베이터만으로 이어지는지는 확인되지 않았습니다" in result.user_message


def _source(source_name: str) -> DataSourceMeta:
    return DataSourceMeta(
        source_name=source_name,
        source_type="fixture",
        fetched_at=datetime(2026, 7, 13, tzinfo=UTC),
    )
