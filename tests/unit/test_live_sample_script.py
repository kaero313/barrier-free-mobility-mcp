from __future__ import annotations

from types import SimpleNamespace

from app.schemas.route import RouteCandidate, RouteSegment
from scripts.check_route_accuracy import load_cases, redact_text, summarize_success
from scripts.collect_live_samples import endpoint_secret_candidates, redact_secrets


def test_collect_live_samples_redacts_known_secret_strings() -> None:
    payload = {
        "url": "https://example.test/path?serviceKey=SECRET",
        "nested": ["abcSECRETdef"],
    }

    assert redact_secrets(payload, {"SECRET"}) == {
        "url": "https://example.test/path?serviceKey=[REDACTED]",
        "nested": ["abc[REDACTED]def"],
    }


def test_endpoint_secret_candidates_detects_key_like_url_segments() -> None:
    settings = SimpleNamespace(
        facility_api_url="https://example.test/Abc123456789012345678/json/service",
        shortest_route_api_url="",
        elevator_status_api_url="",
        elevator_info_api_url="",
        restroom_api_url="https://example.test/path?KEY=Zyx123456789012345678",
    )

    assert endpoint_secret_candidates(settings) == {
        "Abc123456789012345678",
        "Zyx123456789012345678",
    }


def test_check_route_accuracy_script_loads_basic_cases() -> None:
    cases = load_cases("basic")

    assert {case["name"] for case in cases} >= {
        "hongdae_to_samsung_line2_direct",
        "seoul_to_cityhall_line1_direct",
    }


def test_check_route_accuracy_script_summarizes_without_raw_payload() -> None:
    case = load_cases("basic")[0]
    route = RouteCandidate(
        route_id="route",
        origin="홍대입구",
        destination="삼성",
        transfer_count=0,
        estimated_minutes=42,
        stations=["홍대입구", "삼성"],
        segments=[RouteSegment(from_station="홍대입구", to_station="삼성", line="2호선")],
    )

    summary = summarize_success(
        case=case,
        routes=[route],
        raw={"serviceKey": "SECRET", "document": {"body": {}}},
        checked_at="2026-06-10T09:30:00",
        search_scope="searchDt=2026-06-10 09:30:00",
        station_resolution={"origin": {}, "destination": {}},
    )

    assert summary["status"] == "OK"
    assert summary["route"]["lines"] == "2호선"
    assert "serviceKey" not in str(summary)
    assert "SECRET" not in str(summary)


def test_check_route_accuracy_script_redacts_error_text() -> None:
    assert redact_text("reason SECRET value", {"SECRET"}) == "reason [REDACTED] value"
