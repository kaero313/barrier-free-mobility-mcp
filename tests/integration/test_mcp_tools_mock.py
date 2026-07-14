from __future__ import annotations

from app.core.config import AppMode, CacheBackend, Settings
from app.mcp import tools
from app.mcp.tools import TOOL_DESCRIPTIONS
from app.schemas.accessibility import AccessibilityEvidenceStatus, MobilityProfile
from app.schemas.common import CacheStatus, ResponseStatus
from app.schemas.lookup import LookupOutcome
from app.schemas.route import RouteCandidate
from app.services.accessibility_service import AccessibilityService
from app.services.types import ServiceResult


class _EmptyRouteService:
    async def get_route_candidates(self, origin: str, destination: str) -> ServiceResult[list]:
        return ServiceResult(value=[])


class _InvalidRouteService:
    async def get_route_candidates(
        self,
        origin: str,
        destination: str,
    ) -> ServiceResult[list[RouteCandidate]]:
        return ServiceResult(
            value=[
                RouteCandidate(
                    route_id="invalid-empty-segments",
                    origin=origin,
                    destination=destination,
                    segments=[],
                    stations=[origin, destination],
                )
            ]
        )


class _FailIfCalledFacilityService:
    async def get_station_facilities(self, station: str, line: str | None = None) -> None:
        raise AssertionError("facility lookup must not run without a valid route")

    async def get_elevator_status(self, station: str, line: str | None = None) -> None:
        raise AssertionError("elevator lookup must not run without a valid route")

    async def get_accessible_restroom(self, station: str, line: str | None = None) -> None:
        raise AssertionError("restroom lookup must not run without a valid route")


async def test_mock_mode_tools_return_structured_models() -> None:
    station = await tools.resolve_station("홍대역")
    facilities = await tools.get_station_facilities("홍대입구")
    elevators = await tools.get_elevator_status("홍대입구")
    restrooms = await tools.get_accessible_restroom("홍대입구")
    routes = await tools.get_route_candidates("홍대입구", "삼성")
    trip = await tools.check_accessible_trip(
        "홍대입구",
        "삼성",
        MobilityProfile(
            wheelchair=True,
            can_use_stairs=False,
            can_use_escalator=False,
            need_elevator_only=True,
        ),
    )
    brief = await tools.generate_accessibility_brief(
        "홍대입구",
        "삼성",
        MobilityProfile(stroller=True),
    )
    natural_answer = await tools.answer_accessibility_question(
        "휠체어로 홍대입구역에서 삼성역까지 갈 수 있어?"
    )

    assert station.matched_station is not None
    assert facilities.data
    assert elevators.data
    assert restrooms.data
    assert routes.data
    assert facilities.status == ResponseStatus.SUCCESS
    assert facilities.outcome == LookupOutcome.DATA
    assert elevators.outcome == LookupOutcome.DATA
    assert restrooms.outcome == LookupOutcome.DATA
    assert routes.outcome == LookupOutcome.DATA
    assert trip.status == ResponseStatus.SUCCESS
    assert trip.selected_route is not None
    assert len(trip.accessible_facilities) <= len(trip.selected_route.stations)
    source_keys = [
        (source.source_name, source.source_type, source.cache_status, source.success)
        for source in trip.data_sources
    ]
    assert len(source_keys) == len(set(source_keys))
    assert trip.confidence_level == "MEDIUM"
    assert trip.evidence_sources
    assert trip.last_checked_at is not None
    assert "출발 직전 재확인" in trip.safety_notice
    assert brief.confidence_level == "MEDIUM"
    assert brief.evidence_sources
    assert brief.origin == "홍대입구"
    assert natural_answer.status == ResponseStatus.SUCCESS
    assert natural_answer.result is not None
    assert natural_answer.user_message == natural_answer.result.user_message
    assert trip.user_message
    assert trip.user_message_summary.headline
    assert trip.accessibility_checks
    assert all(check.elevator_details for check in trip.accessibility_checks)
    assert any(check.role == "origin" for check in trip.accessibility_checks)
    assert any(check.role == "destination" for check in trip.accessibility_checks)
    assert all(
        check.station_has_elevator == AccessibilityEvidenceStatus.CONFIRMED
        for check in trip.accessibility_checks
    )
    assert all(
        check.platform_to_concourse_verified == AccessibilityEvidenceStatus.CONFIRMED
        for check in trip.accessibility_checks
    )
    assert trip.user_message.startswith("**출발 전에 확인이 필요합니다.**")
    assert "엘리베이터는 현재 운행 중" in trip.user_message
    assert "엘리베이터만으로 이어지는지는" in trip.user_message
    assert "역별 확인 결과" in trip.user_message
    assert "지금 할 일" in trip.user_message
    assert "### 이유" not in trip.user_message
    assert "### 출발 전 확인" not in trip.user_message
    assert "추천 경로" not in trip.user_message
    assert "사용자 조건 반영" not in trip.user_message
    assert "기준 시각" in trip.user_message
    assert "전체 조회 시각" in trip.user_message
    assert "최단경로 정보" in trip.user_message
    assert "엘리베이터 위치·운행상태" in trip.user_message
    assert "실제 이용 승강장과 맞는지 확인 필요" not in trip.user_message
    assert "출구까지 연결 확인 필요" in trip.user_message
    assert "주의사항" in trip.user_message
    assert "예상" not in trip.user_message
    assert "risk_level" not in trip.user_message
    assert "confidence_level" not in trip.user_message
    assert "출발 직전 재확인" in brief.user_message


async def test_partial_failure_includes_failed_sources_and_limitations() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.MOCK,
        mock_failure_sources={"elevator_status"},
    )
    service = AccessibilityService(settings=settings)

    result = await service.check_accessible_trip(
        "홍대입구",
        "삼성",
        MobilityProfile(wheelchair=True, can_use_stairs=False, need_elevator_only=True),
    )

    assert result.status == ResponseStatus.PARTIAL
    assert result.risk_level == "UNKNOWN"
    assert any(source.source_name == "elevator_status" for source in result.failed_sources)
    assert result.limitations
    assert result.confidence_level == "LOW"
    assert result.evidence_sources
    assert any("승강기_가동현황" in part for part in result.unverified_parts)
    assert result.user_message
    assert "이용 여부를 판단할 수 없습니다" in result.user_message
    assert "출발 직전 재확인" in result.user_message


async def test_trip_with_no_valid_route_returns_failed_unknown() -> None:
    service = AccessibilityService(
        route_service=_EmptyRouteService(),
        facility_service=_FailIfCalledFacilityService(),
    )

    result = await service.check_accessible_trip(
        "1호선 서울역",
        "2호선 삼성",
        MobilityProfile(wheelchair=True, can_use_stairs=False, need_elevator_only=True),
    )

    assert result.status == ResponseStatus.FAILED
    assert result.risk_level == "UNKNOWN"
    assert result.selected_route is None
    assert result.user_message_summary.judgement == "확인 불가"
    assert "이용 여부를 판단할 수 없습니다" in result.user_message
    assert "현재 확인된 정보에서는 이동을 막는 문제가 없습니다" not in result.user_message


async def test_trip_rejects_route_candidate_without_segments() -> None:
    service = AccessibilityService(
        route_service=_InvalidRouteService(),
        facility_service=_FailIfCalledFacilityService(),
    )

    result = await service.check_accessible_trip(
        "1호선 서울역",
        "2호선 삼성",
        MobilityProfile(wheelchair=True),
    )

    assert result.status == ResponseStatus.FAILED
    assert result.risk_level == "UNKNOWN"
    assert result.selected_route is None


async def test_trip_with_wrong_explicit_line_requests_clarification() -> None:
    service = AccessibilityService(
        route_service=_EmptyRouteService(),
        facility_service=_FailIfCalledFacilityService(),
    )

    result = await service.check_accessible_trip(
        "9호선 삼성",
        "2호선 강남",
        MobilityProfile(wheelchair=True),
    )

    assert result.status == ResponseStatus.NEEDS_CLARIFICATION
    assert result.risk_level == "UNKNOWN"
    assert result.selected_route is None
    assert any("삼성" in question and "2호선" in question for question in result.questions)


async def test_natural_question_with_wrong_line_explains_station_line_mismatch() -> None:
    response = await AccessibilityService().answer_accessibility_question(
        "휠체어로 9호선 삼성역에서 2호선 강남역까지 갈 수 있어?"
    )

    assert response.status == ResponseStatus.NEEDS_CLARIFICATION
    assert response.clarification_needed is True
    assert response.result is None
    assert "입력한 역과 호선 조합" in response.user_message


async def test_cache_hit_metadata_is_reported() -> None:
    await tools.get_station_facilities("홍대입구")
    service = tools._get_facility_service()
    result = await service.get_station_facilities("홍대입구")

    assert result.data_sources[0].cache_status == CacheStatus.HIT


async def test_mock_trip_with_unavailable_redis_cache_still_succeeds() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.MOCK,
        cache_backend=CacheBackend.REDIS,
        redis_url="redis://localhost:1/0",
        redis_socket_timeout_seconds=0.01,
        redis_socket_connect_timeout_seconds=0.01,
    )
    service = AccessibilityService(settings=settings)

    result = await service.check_accessible_trip(
        "\ud64d\ub300\uc785\uad6c",
        "\uc0bc\uc131",
        MobilityProfile(
            wheelchair=True,
            can_use_stairs=False,
            can_use_escalator=False,
            need_elevator_only=True,
        ),
    )

    assert result.status == ResponseStatus.SUCCESS
    assert result.selected_route is not None


def test_register_tools_registers_required_names() -> None:
    class FakeMcp:
        def __init__(self) -> None:
            self.names: list[str] = []
            self.descriptions: dict[str, str | None] = {}

        def tool(self, **kwargs):
            def register(function):
                self.names.append(function.__name__)
                self.descriptions[function.__name__] = kwargs.get("description")
                return function

            return register

    fake = FakeMcp()
    tools.register_tools(fake)

    assert set(fake.names) == {
        "resolve_station",
        "get_station_facilities",
        "get_elevator_status",
        "get_accessible_restroom",
        "get_route_candidates",
        "check_accessible_trip",
        "generate_accessibility_brief",
        "answer_accessibility_question",
    }
    assert fake.descriptions == TOOL_DESCRIPTIONS
    assert "user_message" in fake.descriptions["generate_accessibility_brief"]
    assert "verbatim" in fake.descriptions["generate_accessibility_brief"]
