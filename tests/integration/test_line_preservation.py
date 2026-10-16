from __future__ import annotations

from app.normalizers.helpers import normalize_line_name
from app.schemas.accessibility import MobilityProfile
from app.schemas.common import ResponseStatus
from app.schemas.route import RouteCandidate, RouteSegment
from app.services.accessibility_service import AccessibilityService
from app.services.facility_service import FacilityService
from app.services.types import ServiceResult


class _WrongOriginLineRouteService:
    async def get_route_candidates(
        self,
        origin: str,
        destination: str,
        *,
        origin_station_code: str | None = None,
        destination_station_code: str | None = None,
    ) -> ServiceResult[list[RouteCandidate]]:
        return ServiceResult(
            value=[
                RouteCandidate(
                    route_id="wrong-origin-line",
                    origin=origin,
                    destination=destination,
                    transfer_count=1,
                    stations=[origin, "공덕", destination],
                    segments=[
                        RouteSegment(
                            from_station=origin,
                            to_station="공덕",
                            line="경의선",
                        ),
                        RouteSegment(
                            from_station="공덕",
                            to_station=destination,
                            line="2호선",
                        ),
                    ],
                )
            ]
        )


async def test_facility_service_resolves_embedded_line_in_station_query() -> None:
    service = FacilityService()

    result = await service.get_station_facilities("9호선 고속터미널")

    assert result.value
    assert {facility.facility_id for facility in result.value} == {"EXPRESS-EV-1"}
    assert all(normalize_line_name(facility.line) == "9" for facility in result.value)


async def test_facility_service_explicit_line_filters_transfer_station() -> None:
    service = FacilityService()

    result = await service.get_elevator_status("서울역", line="1")

    assert result.value
    assert all(facility.station_name == "서울역" for facility in result.value)
    assert all(normalize_line_name(facility.line) == "1" for facility in result.value)


async def test_facility_service_broad_lookup_still_works_for_ambiguous_station() -> None:
    service = FacilityService()

    result = await service.get_station_facilities("고속터미널")

    assert result.value
    assert any(facility.station_name == "고속터미널" for facility in result.value)


async def test_accessible_trip_preserves_line_for_line_aware_endpoints() -> None:
    service = AccessibilityService()
    profile = MobilityProfile(
        wheelchair=True,
        can_use_stairs=False,
        can_use_escalator=False,
        need_elevator_only=True,
    )

    result = await service.check_accessible_trip(
        "9호선 고속터미널",
        "9호선 여의도",
        profile,
    )

    assert result.status == ResponseStatus.SUCCESS
    checks = {check.station: check for check in result.accessibility_checks}
    assert checks["고속터미널"].line == "9"
    assert checks["고속터미널"].station_id == "0923"
    assert checks["여의도"].line == "9"
    assert checks["여의도"].station_id == "0915"
    assert all(
        normalize_line_name(facility.line) == "9"
        for facility in result.accessible_facilities
    )


async def test_accessible_trip_preserves_line_one_for_seoul_to_cityhall() -> None:
    service = AccessibilityService()
    profile = MobilityProfile(
        wheelchair=True,
        can_use_stairs=False,
        can_use_escalator=False,
        need_elevator_only=True,
    )

    result = await service.check_accessible_trip(
        "1호선 서울역",
        "1호선 시청",
        profile,
    )

    assert result.status == ResponseStatus.SUCCESS
    checks = {check.station: check for check in result.accessibility_checks}
    assert checks["서울역"].line == "1"
    assert checks["서울역"].station_id == "0150"
    assert checks["시청"].line == "1"
    assert checks["시청"].station_id == "0132"


async def test_accessible_trip_keeps_ambiguous_transfer_station_clarification() -> None:
    service = AccessibilityService()

    result = await service.check_accessible_trip(
        "고속터미널",
        "여의도",
        MobilityProfile(wheelchair=True, can_use_stairs=False, need_elevator_only=True),
    )

    assert result.status == ResponseStatus.NEEDS_CLARIFICATION
    assert result.clarification_needed is True


async def test_accessible_trip_rejects_route_with_mismatched_endpoint_line() -> None:
    service = AccessibilityService(route_service=_WrongOriginLineRouteService())

    result = await service.check_accessible_trip(
        "2호선 홍대입구",
        "2호선 삼성",
        MobilityProfile(wheelchair=True, can_use_stairs=False, need_elevator_only=True),
    )

    assert result.status == ResponseStatus.FAILED
    assert result.selected_route is None
    # 남은 경로가 없으면 호선 불일치 안내가 제외 이유를 말하므로 제외 건수 안내를 따로 두지 않는다.
    assert not any("일치하지 않은 경로 후보" in item for item in result.limitations)
    assert result.available_partial_info[0] == (
        "홍대입구역은 경로 데이터에서 경의선으로 연결되어 입력한 2호선과 다릅니다."
    )
    assert result.user_message.startswith(
        "**입력한 역·호선과 맞는 지하철 경로를 찾지 못했습니다.**"
    )
    assert "호선을 빼고 다시 조회하거나" in result.user_message
    assert "역별 엘리베이터 정보는 조회하지 않았습니다" in result.user_message
    assert "잠시 후 다시 조회" not in result.user_message
    assert "점검 또는 이용 제한으로 확인된 엘리베이터는 없습니다" not in result.user_message


async def test_unstated_endpoint_line_follows_the_route_line() -> None:
    service = AccessibilityService(route_service=_WrongOriginLineRouteService())

    result = await service.check_accessible_trip(
        "홍대입구",
        "2호선 삼성",
        MobilityProfile(wheelchair=True, can_use_stairs=False, need_elevator_only=True),
    )

    # 역 이름만으로 정한 2호선은 사용자가 고른 호선이 아니다. 경로가 경의선으로 출발해도
    # 경로를 버리지 않고, 출발역은 실제로 타는 경의선 기준으로 본다.
    assert result.status != ResponseStatus.FAILED
    assert result.selected_route is not None
    assert not any("입력한 2호선과 다릅니다" in info for info in result.available_partial_info)
    origin_check = next(check for check in result.accessibility_checks if check.role == "origin")
    assert origin_check.line != "2"
    assert "입력한" not in result.user_message
