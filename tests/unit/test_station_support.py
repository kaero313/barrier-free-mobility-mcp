from __future__ import annotations

from collections import Counter

from app.core.config import AppMode
from app.normalizers.station_normalizer import DEFAULT_STATION_NORMALIZER
from app.services.source_coverage import station_support_required_sources
from app.services.station_context import StationLookupContext, resolve_station_context
from app.services.station_service import StationService
from app.services.station_support import (
    StationSupportStatus,
    evaluate_station_support,
    station_support_limitations,
)


def test_station_support_contract_lists_required_accessibility_sources() -> None:
    assert station_support_required_sources() == (
        "facility_info",
        "elevator_status",
        "elevator_info",
        "restroom",
    )


def test_live_station_support_inventory_has_explicit_supported_and_partial_counts() -> None:
    decisions = [
        evaluate_station_support(
            StationLookupContext(
                station_name=station.station_name,
                line=station.line,
                station_id=station.station_id,
                operator=station.operator,
            ),
            app_mode=AppMode.LIVE,
        )
        for station in DEFAULT_STATION_NORMALIZER.stations
    ]

    counts = Counter(decision.status for decision in decisions)

    # 296 SUPPORTED: 서울교통공사-operated combos with verified route codes.
    # 25 PARTIAL: 9호선 개화~신논현 (서울시메트로9호선 운영 구간, 시설 데이터 미제공).
    assert len(decisions) == 321
    assert counts == {
        StationSupportStatus.SUPPORTED: 296,
        StationSupportStatus.PARTIAL: 25,
    }


def test_registered_station_with_route_code_and_sources_is_supported() -> None:
    context = resolve_station_context(StationService(), "2호선 삼성")

    decision = evaluate_station_support(context, app_mode=AppMode.LIVE)

    assert decision.status == StationSupportStatus.SUPPORTED
    assert decision.route_code_verified is True
    assert decision.notes == ()


def test_registered_station_without_route_code_is_partial() -> None:
    # Every registered station currently has a verified route code, so this
    # contract is exercised with a synthetic registered-but-unverified context.
    context = StationLookupContext(
        station_name="코드미검증",
        line="2",
        station_id="9999",
        operator="seoul_metro",
    )

    decision = evaluate_station_support(context, app_mode=AppMode.LIVE)

    assert decision.status == StationSupportStatus.PARTIAL
    assert decision.route_code_verified is False
    assert decision.unsupported_sources == ()
    assert "역 코드가 아직 검증되지 않아" in decision.notes[0]


def test_station_outside_facility_source_coverage_is_partial() -> None:
    context = resolve_station_context(StationService(), "9호선 여의도")

    decision = evaluate_station_support(context, app_mode=AppMode.LIVE)

    assert decision.status == StationSupportStatus.PARTIAL
    assert decision.route_code_verified is True
    assert set(decision.unsupported_sources) == {
        "facility_info",
        "elevator_status",
        "elevator_info",
        "restroom",
    }
    assert "접근성 시설 데이터의 제공 범위" in decision.notes[0]


def test_unregistered_station_context_is_unverified() -> None:
    context = StationLookupContext(
        station_name="을지로입구",
        line="2",
        query="2호선 을지로입구",
        needs_clarification=True,
    )

    decision = evaluate_station_support(context, app_mode=AppMode.LIVE)

    assert decision.status == StationSupportStatus.UNVERIFIED
    assert decision.route_code_verified is False
    assert "검증된 역·호선 목록" in decision.notes[0]


def test_station_support_note_does_not_repeat_station_suffix() -> None:
    context = resolve_station_context(StationService(), "9호선 서울역")

    decision = evaluate_station_support(context, app_mode=AppMode.LIVE)

    assert decision.status == StationSupportStatus.UNVERIFIED
    assert decision.notes[0].startswith("9호선 서울역은 ")


def test_mock_mode_does_not_apply_live_station_coverage_limits() -> None:
    context = resolve_station_context(StationService(), "9호선 언주")

    assert station_support_limitations(context, app_mode=AppMode.MOCK) == []
