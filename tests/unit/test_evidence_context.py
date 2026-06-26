from __future__ import annotations

from app.core.time import utc_now
from app.schemas.accessibility import AccessibilityResult, EvidenceSource, MobilityProfile
from app.schemas.common import CacheStatus, DataSourceMeta, FailedSource, ResponseStatus
from app.services.evidence import build_evidence_context, display_name_for_source


def test_accessibility_result_trust_fields_have_safe_defaults() -> None:
    result = AccessibilityResult(
        origin="홍대입구",
        destination="삼성",
        mobility_profile=MobilityProfile(),
        risk_level="LOW",
        risk_score=0,
        route_summary="테스트 경로",
    )

    assert result.confidence_level == "LOW"
    assert result.confidence_reasons == []
    assert result.evidence_sources == []
    assert result.unverified_parts == []
    assert "출발 직전 재확인" in result.safety_notice


def test_evidence_source_schema_does_not_require_raw_url_or_secret() -> None:
    source = EvidenceSource(
        source_name="shortest_route",
        display_name=display_name_for_source("shortest_route"),
        source_type="public_api",
        checked_at=utc_now(),
        cache_status=CacheStatus.MISS,
    )

    assert source.display_name == "서울교통공사_최단경로이동정보"
    assert "SECRET" not in source.model_dump_json()


def test_public_api_success_metadata_produces_high_confidence() -> None:
    context = build_evidence_context(
        status=ResponseStatus.SUCCESS,
        risk_level="LOW",
        data_sources=[
            _source("shortest_route", "public_api"),
            _source("facility_info", "public_api"),
            _source("elevator_status", "public_api"),
        ],
        failed_sources=[],
        limitations=[],
    )

    assert context["confidence_level"] == "HIGH"
    assert context["last_checked_at"] is not None
    assert {source.source_name for source in context["evidence_sources"]} == {
        "shortest_route",
        "facility_info",
        "elevator_status",
    }
    assert context["unverified_parts"] == []


def test_critical_failure_or_unknown_risk_produces_low_confidence() -> None:
    context = build_evidence_context(
        status=ResponseStatus.PARTIAL,
        risk_level="UNKNOWN",
        data_sources=[
            _source("shortest_route", "public_api"),
            _source("facility_info", "public_api"),
            _source(
                "elevator_status",
                "public_api",
                success=False,
                error_message="timeout",
            ),
        ],
        failed_sources=[FailedSource(source_name="elevator_status", reason="timeout")],
        limitations=["엘리베이터 상태를 확인하지 못했습니다."],
    )

    assert context["confidence_level"] == "LOW"
    assert any("UNKNOWN" in reason for reason in context["confidence_reasons"])
    assert any("승강기_가동현황 확인 실패" in part for part in context["unverified_parts"])


def test_fixture_or_cache_sources_produce_medium_confidence() -> None:
    fixture_context = build_evidence_context(
        status=ResponseStatus.SUCCESS,
        risk_level="LOW",
        data_sources=[
            _source("shortest_route", "fixture"),
            _source("facility_info", "fixture"),
            _source("elevator_status", "fixture"),
        ],
        failed_sources=[],
        limitations=[],
    )
    cache_context = build_evidence_context(
        status=ResponseStatus.SUCCESS,
        risk_level="LOW",
        data_sources=[
            _source("shortest_route", "public_api"),
            _source("facility_info", "public_api", cache_status=CacheStatus.HIT),
            _source("elevator_status", "public_api"),
        ],
        failed_sources=[],
        limitations=[],
    )

    assert fixture_context["confidence_level"] == "MEDIUM"
    assert cache_context["confidence_level"] == "MEDIUM"
    assert any("mock fixture" in part for part in fixture_context["unverified_parts"])
    assert any("캐시 응답" in part for part in cache_context["unverified_parts"])


def test_source_display_names_are_safe_and_user_facing() -> None:
    assert display_name_for_source("restroom") == (
        "서울시 교통공사 지하철역 교통약자이용정보 장애인화장실 현황"
    )
    assert display_name_for_source("unknown_source") == "unknown_source"


def _source(
    source_name: str,
    source_type: str,
    *,
    success: bool = True,
    cache_status: CacheStatus = CacheStatus.MISS,
    error_message: str | None = None,
) -> DataSourceMeta:
    return DataSourceMeta(
        source_name=source_name,
        source_type=source_type,
        fetched_at=utc_now(),
        cache_status=cache_status,
        success=success,
        error_message=error_message,
    )
