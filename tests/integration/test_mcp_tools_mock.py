from __future__ import annotations

from app.core.config import AppMode, CacheBackend, Settings
from app.mcp import tools
from app.mcp.tools import TOOL_DESCRIPTIONS
from app.schemas.accessibility import MobilityProfile
from app.schemas.common import CacheStatus, ResponseStatus
from app.services.accessibility_service import AccessibilityService


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
    assert facilities
    assert elevators
    assert restrooms
    assert routes
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
    assert any(check.role == "origin" for check in trip.accessibility_checks)
    assert any(check.role == "destination" for check in trip.accessibility_checks)
    assert "판단: 가능" in trip.user_message
    assert "필요한 접근성 정보가 확인되었습니다" in trip.user_message
    assert "이유" in trip.user_message
    assert "추천 경로" in trip.user_message
    assert "접근성 체크" in trip.user_message
    assert "사용자 조건 반영" in trip.user_message
    assert "기준 시각" in trip.user_message
    assert "전체 조회 시각" in trip.user_message
    assert "최단경로 정보" in trip.user_message
    assert "엘리베이터 위치·운행상태" in trip.user_message
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
    assert "안내하기 어렵습니다" in result.user_message
    assert "출발 직전 재확인" in result.user_message


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
