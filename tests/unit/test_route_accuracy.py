from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from app.core.config import Settings
from app.normalizers.route_normalizer import normalize_route_candidates
from app.schemas.route import RouteCandidate, RouteSegment
from app.services.route_accuracy import (
    check_route_accuracy,
    route_line_summary,
    route_station_summary,
)
from app.services.route_service import (
    build_route_request_params,
    route_cache_key,
    route_search_cache_scope,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
MOCK_ROUTE_FIXTURE = Path(__file__).resolve().parents[2] / "app" / "data" / "mock_responses"


def _route_accuracy_cases() -> dict[str, Any]:
    return yaml.safe_load((FIXTURE_DIR / "route_accuracy_cases.yaml").read_text(encoding="utf-8"))


def _best_route_for_case(case: dict[str, Any]) -> RouteCandidate:
    raw = json.loads((MOCK_ROUTE_FIXTURE / "shortest_route.json").read_text(encoding="utf-8"))
    routes = normalize_route_candidates(
        raw,
        origin=case["origin"],
        destination=case["destination"],
    )
    assert routes
    return min(
        routes,
        key=lambda route: (
            route.transfer_count,
            route.estimated_minutes if route.estimated_minutes is not None else 9999,
        ),
    )


def test_mock_route_accuracy_strict_cases_pass() -> None:
    for case in _route_accuracy_cases()["strict_cases"]:
        route = _best_route_for_case(case)

        assert check_route_accuracy(route, case) == []


def test_saved_live_hongdae_samsung_sample_stays_line2_direct_when_present() -> None:
    path = FIXTURE_DIR / "live_samples" / "shortest_route_sample.json"
    if not path.exists():
        return
    raw = json.loads(path.read_text(encoding="utf-8"))
    case = _route_accuracy_cases()["strict_cases"][0]

    routes = normalize_route_candidates(raw, origin=case["origin"], destination=case["destination"])

    assert len(routes) == 1
    assert check_route_accuracy(routes[0], case) == []
    assert route_line_summary(routes[0]) == "2호선"


def test_route_accuracy_flags_unexpected_transfer_route() -> None:
    case = _route_accuracy_cases()["strict_cases"][0]
    bad_route = RouteCandidate(
        route_id="bad-live-route",
        origin="홍대입구",
        destination="삼성",
        transfer_count=2,
        estimated_minutes=42,
        stations=["홍대입구", "이촌", "사당", "삼성"],
        segments=[
            RouteSegment(from_station="홍대입구", to_station="이촌", line="2호선"),
            RouteSegment(from_station="이촌", to_station="사당", line="4호선", transfer=True),
            RouteSegment(from_station="사당", to_station="삼성", line="2호선", transfer=True),
        ],
    )

    issue_codes = {issue.code for issue in check_route_accuracy(bad_route, case)}

    assert "unexpected_transfer_count" in issue_codes
    assert "unexpected_line" in issue_codes
    assert "forbidden_station_present" in issue_codes


def test_route_summary_helpers_are_compact() -> None:
    route = RouteCandidate(
        route_id="long",
        origin="A",
        destination="J",
        transfer_count=0,
        stations=list("ABCDEFGHIJ"),
        segments=[RouteSegment(from_station="A", to_station="B", line="2호선")],
    )

    assert route_station_summary(route, max_stations=5) == "A → B → … → I → J"
    assert route_line_summary(route) == "2호선"


def test_route_cache_scope_includes_configured_search_date() -> None:
    morning = Settings(route_default_search_date="2026-06-10 09:30:00")
    evening = Settings(route_default_search_date="2026-06-10 18:30:00")

    assert route_cache_key("홍대입구", "삼성", morning) != route_cache_key(
        "홍대입구",
        "삼성",
        evening,
    )
    assert route_search_cache_scope(morning) == "searchDt=2026-06-10 09:30:00"


def test_route_cache_scope_uses_hour_bucket_without_fixed_search_date() -> None:
    settings = Settings(route_default_search_date="")

    assert (
        route_search_cache_scope(settings, now=datetime(2026, 6, 10, 9, 42, 12))
        == "searchDt=2026-06-10 09:00:00"
    )


def test_route_cache_scope_handles_disabled_search_date_param() -> None:
    settings = Settings(route_search_date_param="")

    assert route_search_cache_scope(settings) == "no-search-date"


def test_route_request_uses_station_codes_when_both_are_available() -> None:
    settings = Settings(_env_file=None)

    params = build_route_request_params(
        "홍대입구",
        "삼성",
        settings,
        origin_station_code="0239",
        destination_station_code="0219",
    )

    assert params == {
        "origin": "0239",
        "destination": "0219",
        "station_value_type": "code",
    }


def test_route_request_falls_back_to_names_when_a_station_code_is_missing() -> None:
    settings = Settings(_env_file=None)

    params = build_route_request_params(
        "홍대입구",
        "삼성",
        settings,
        origin_station_code="0239",
    )

    assert params == {"origin": "홍대입구", "destination": "삼성"}


def test_route_cache_key_separates_code_and_name_queries() -> None:
    settings = Settings(route_default_search_date="2026-07-14 09:00:00")

    name_key = route_cache_key("홍대입구", "삼성", settings)
    code_key = route_cache_key(
        "홍대입구",
        "삼성",
        settings,
        origin_station_code="0239",
        destination_station_code="0219",
    )

    assert name_key != code_key
    assert "route:name:홍대입구:삼성" in name_key
    assert "route:code:0239:0219" in code_key
