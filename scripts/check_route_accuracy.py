from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.route_accuracy import (  # noqa: E402
    check_route_accuracy,
    route_line_summary,
    route_station_summary,
)

CASE_FILE = PROJECT_ROOT / "tests" / "fixtures" / "route_accuracy_cases.yaml"


async def main() -> None:
    from app.adapters.shortest_route_client import ShortestRouteClient
    from app.core.config import AppMode, Settings
    from app.core.errors import PublicApiError
    from app.normalizers.route_normalizer import normalize_route_candidates
    from app.normalizers.station_normalizer import resolve_station
    from app.services.route_service import route_search_cache_scope

    parser = argparse.ArgumentParser(description="Check live shortest-route API accuracy.")
    parser.add_argument("--case-set", choices=["basic", "coverage"], default="basic")
    parser.add_argument("--search-date", default=None, help="Override route searchDt value.")
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional PUBLIC_DATA_SERVICE_KEY override. Prefer .env for regular use.",
    )
    parser.add_argument("--origin", default=None, help="Run one ad hoc origin station.")
    parser.add_argument("--destination", default=None, help="Run one ad hoc destination station.")
    args = parser.parse_args()

    if (args.origin is None) != (args.destination is None):
        parser.error("--origin and --destination must be provided together.")

    settings_kwargs: dict[str, Any] = {"app_mode": AppMode.LIVE}
    if args.search_date:
        settings_kwargs["route_default_search_date"] = args.search_date
    if args.api_key:
        settings_kwargs["public_data_service_key"] = args.api_key
    settings = Settings(**settings_kwargs)

    if args.origin and args.destination:
        cases = [
            {
                "name": "ad_hoc",
                "origin": args.origin,
                "destination": args.destination,
                "required_stations": [args.origin, args.destination],
            }
        ]
    else:
        cases = load_cases(args.case_set)

    client = ShortestRouteClient(settings)
    summaries: list[dict[str, Any]] = []
    secrets = {settings.public_data_service_key, args.api_key or ""}
    secrets.discard("")

    for case in cases:
        checked_at = datetime.now().isoformat(timespec="seconds")
        try:
            raw = await client.fetch(origin=case["origin"], destination=case["destination"])
            routes = normalize_route_candidates(
                raw,
                origin=case["origin"],
                destination=case["destination"],
            )
            summaries.append(
                summarize_success(
                    case=case,
                    routes=routes,
                    raw=raw,
                    checked_at=checked_at,
                    search_scope=route_search_cache_scope(settings),
                    station_resolution={
                        "origin": summarize_station_resolution(resolve_station(case["origin"])),
                        "destination": summarize_station_resolution(
                            resolve_station(case["destination"])
                        ),
                    },
                )
            )
        except PublicApiError as exc:
            summaries.append(
                {
                    "name": case["name"],
                    "origin": case["origin"],
                    "destination": case["destination"],
                    "status": "ERROR",
                    "checked_at": checked_at,
                    "search_scope": route_search_cache_scope(settings),
                    "error": redact_text(f"{exc.source_name}:{exc.reason}", secrets),
                }
            )

    print(json.dumps(summaries, ensure_ascii=False, indent=2))


def load_cases(case_set: str) -> list[dict[str, Any]]:
    data = yaml.safe_load(CASE_FILE.read_text(encoding="utf-8"))
    strict_cases = list(data.get("strict_cases", []))
    if case_set == "basic":
        return strict_cases
    return [*strict_cases, *data.get("smoke_cases", [])]


def summarize_success(
    *,
    case: dict[str, Any],
    routes: list[Any],
    raw: dict[str, Any],
    checked_at: str,
    search_scope: str,
    station_resolution: dict[str, Any],
) -> dict[str, Any]:
    if not routes:
        return {
            "name": case["name"],
            "origin": case["origin"],
            "destination": case["destination"],
            "status": "NO_ROUTE",
            "checked_at": checked_at,
            "search_scope": search_scope,
            "station_resolution": station_resolution,
            "payload_chars": len(json.dumps(raw, ensure_ascii=False)),
        }

    route = min(
        routes,
        key=lambda candidate: (
            candidate.transfer_count,
            candidate.estimated_minutes if candidate.estimated_minutes is not None else 9999,
        ),
    )
    issues = check_route_accuracy(route, case)
    return {
        "name": case["name"],
        "origin": case["origin"],
        "destination": case["destination"],
        "status": "ISSUES" if issues else "OK",
        "checked_at": checked_at,
        "search_scope": search_scope,
        "station_resolution": station_resolution,
        "route": {
            "transfer_count": route.transfer_count,
            "estimated_minutes": route.estimated_minutes,
            "distance_meters": route.distance_meters,
            "lines": route_line_summary(route),
            "stations": route_station_summary(route),
        },
        "issues": [{"code": issue.code, "message": issue.message} for issue in issues],
        "candidate_count": len(routes),
        "payload_chars": len(json.dumps(raw, ensure_ascii=False)),
    }


def summarize_station_resolution(result: Any) -> dict[str, Any]:
    matched = result.matched_station
    return {
        "matched_station": matched.station_name if matched else None,
        "line": matched.line if matched else None,
        "station_id": matched.station_id if matched else None,
        "needs_clarification": result.needs_clarification,
        "candidate_count": len(result.candidates),
    }


def redact_text(value: str, secrets: set[str]) -> str:
    redacted = value
    for secret in secrets:
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


if __name__ == "__main__":
    asyncio.run(main())
