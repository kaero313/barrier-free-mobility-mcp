"""Collect verified shortest-route station codes from the live public API.

The 서울교통공사_최단경로이동정보 API returns, for every path hop, the station
code (`stnCd`), station name (`stnNm`), and line (`lineNm`) it actually uses.
This script requests end-to-end traversals of each 서울교통공사-operated line,
harvests those codes, and merges them into:

- `app/data/route_station_codes.yaml` (regenerated, sorted)
- `app/data/station_aliases.yaml` (new stations appended; existing lines kept)

Codes are only recorded when the API itself returned them, and each traversal
endpoint pair is re-requested by code (`stationValueType=code`) to confirm the
API also accepts them. API keys, endpoint URLs, and raw query parameters are
never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.normalizers.helpers import normalize_line_name, normalize_station_name  # noqa: E402

ROUTE_CODE_FILE = PROJECT_ROOT / "app" / "data" / "route_station_codes.yaml"
STATION_ALIAS_FILE = PROJECT_ROOT / "app" / "data" / "station_aliases.yaml"

# Each case traverses a 서울교통공사-operated section only. Termini outside the
# operator's jurisdiction (e.g. KORAIL sections of lines 1/3/4) are excluded on
# purpose: registering them would overstate facility-data coverage.
TRAVERSAL_CASES: list[dict[str, Any]] = [
    {"name": "line1", "line": "1", "origins": ["서울역"], "destinations": ["청량리"]},
    {"name": "line2_east", "line": "2", "origins": ["시청"], "destinations": ["왕십리"]},
    {"name": "line2_northeast", "line": "2", "origins": ["왕십리"], "destinations": ["잠실"]},
    {"name": "line2_southeast", "line": "2", "origins": ["잠실"], "destinations": ["교대"]},
    {"name": "line2_south", "line": "2", "origins": ["교대"], "destinations": ["사당"]},
    {"name": "line2_southwest", "line": "2", "origins": ["사당"], "destinations": ["신도림"]},
    # 신도림→시청 direct would ride line 1; two shorter hops force the line 2 western arc.
    {"name": "line2_west_a", "line": "2", "origins": ["신도림"], "destinations": ["합정"]},
    {"name": "line2_west_b", "line": "2", "origins": ["합정"], "destinations": ["시청"]},
    {"name": "line2_seongsu_branch", "line": "2", "origins": ["성수"], "destinations": ["신설동"]},
    {
        "name": "line2_sinjeong_branch",
        "line": "2",
        "origins": ["신도림"],
        "destinations": ["까치산"],
    },
    # 지축→오금 direct transfers to line 5 at 종로3가; split hops keep the path on line 3.
    {"name": "line3_north", "line": "3", "origins": ["지축"], "destinations": ["종로3가"]},
    {"name": "line3_mid", "line": "3", "origins": ["종로3가"], "destinations": ["고속터미널"]},
    {"name": "line3_south", "line": "3", "origins": ["고속터미널"], "destinations": ["수서"]},
    {"name": "line3_tail", "line": "3", "origins": ["수서"], "destinations": ["오금"]},
    {"name": "line4", "line": "4", "origins": ["불암산", "당고개"], "destinations": ["남태령"]},
    {
        "name": "line5_main",
        "line": "5",
        "origins": ["방화"],
        "destinations": ["하남검단산", "상일동"],
    },
    {"name": "line5_macheon_branch", "line": "5", "origins": ["강동"], "destinations": ["마천"]},
    {"name": "line6_main", "line": "6", "origins": ["신내"], "destinations": ["구산"]},
    {"name": "line6_eungam_loop", "line": "6", "origins": ["독바위"], "destinations": ["응암"]},
    # 신내→구산 direct cuts across lines 1/3; western hops keep the path on line 6.
    {"name": "line6_west_a", "line": "6", "origins": ["신당"], "destinations": ["공덕"]},
    {"name": "line6_west_b", "line": "6", "origins": ["공덕"], "destinations": ["응암"]},
    # The one-way 응암 loop only passes 역촌 in the 응암→불광 direction.
    {"name": "line6_loop_yeokchon", "line": "6", "origins": ["응암"], "destinations": ["불광"]},
    {"name": "line7", "line": "7", "origins": ["장암"], "destinations": ["온수"]},
    {"name": "line8", "line": "8", "origins": ["별내", "암사"], "destinations": ["모란"]},
    # 별내→모란 direct transfers to 분당선 at 복정; 산성 hops keep the path on line 8.
    {"name": "line8_south_a", "line": "8", "origins": ["장지"], "destinations": ["산성"]},
    {"name": "line8_south_b", "line": "8", "origins": ["산성"], "destinations": ["모란"]},
    {"name": "line9", "line": "9", "origins": ["개화"], "destinations": ["중앙보훈병원"]},
]


# Line 1 paths can detour through KORAIL-managed ground sections (영등포, 용산 등).
# Only the 서울교통공사-managed 서울역~청량리 section (codes 0150-0159) is recorded.
SEOUL_METRO_LINE1_CODES = frozenset(f"015{index}" for index in range(10))


def is_seoul_metro_station(station: HarvestedStation) -> bool:
    if station.line == "1":
        return station.code in SEOUL_METRO_LINE1_CODES
    return True


@dataclass(frozen=True)
class HarvestedStation:
    station_name: str
    line: str
    code: str

    @property
    def key(self) -> tuple[str, str]:
        return (
            normalize_station_name(self.station_name) or self.station_name,
            normalize_line_name(self.line) or self.line,
        )


@dataclass
class HarvestResult:
    stations: dict[tuple[str, str], HarvestedStation] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)

    def add(self, station: HarvestedStation) -> None:
        existing = self.stations.get(station.key)
        if existing is None:
            self.stations[station.key] = station
            return
        if existing.code != station.code:
            self.conflicts.append(
                f"{station.line}호선 {station.station_name}: "
                f"code {existing.code} != {station.code}"
            )


def _path_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    document = raw.get("document")
    if not isinstance(document, dict):
        return []
    body = document.get("body")
    if not isinstance(body, dict):
        return []
    container = body.get("paths")
    rows = container.get("path") if isinstance(container, dict) else container
    if isinstance(rows, dict):
        rows = [rows]
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _harvest_endpoint(value: Any) -> HarvestedStation | None:
    if not isinstance(value, dict):
        return None
    name = str(value.get("stnNm") or "").strip()
    code = str(value.get("stnCd") or "").strip()
    line = normalize_line_name(value.get("lineNm"))
    if not name or not code or line is None or not line.isdigit():
        return None
    if not (1 <= int(line) <= 9):
        return None
    return HarvestedStation(station_name=name, line=line, code=code)


def extract_station_codes(raw: dict[str, Any], result: HarvestResult) -> list[HarvestedStation]:
    """Harvest (station, line, code) from every path hop of one API response."""
    harvested: list[HarvestedStation] = []
    for row in _path_rows(raw):
        for endpoint_key in ("dptreStn", "arvlStn"):
            station = _harvest_endpoint(row.get(endpoint_key))
            if station is not None:
                result.add(station)
                harvested.append(station)
    return harvested


def load_existing_route_codes() -> dict[tuple[str, str], str]:
    payload = yaml.safe_load(ROUTE_CODE_FILE.read_text(encoding="utf-8")) or {}
    existing: dict[tuple[str, str], str] = {}
    for row in payload.get("stations", []):
        station = normalize_station_name(row.get("station_name"))
        line = normalize_line_name(row.get("line"))
        code = str(row.get("route_station_code") or "").strip()
        if station and line and code:
            existing[(station, line)] = code
    return existing


def load_registered_alias_pairs() -> set[tuple[str, str]]:
    payload = yaml.safe_load(STATION_ALIAS_FILE.read_text(encoding="utf-8")) or {}
    pairs: set[tuple[str, str]] = set()
    for row in payload.get("stations", []):
        station = normalize_station_name(row.get("station_name"))
        line = normalize_line_name(row.get("line"))
        if station and line:
            pairs.add((station, line))
    return pairs


def merge_route_codes(
    existing: dict[tuple[str, str], str],
    result: HarvestResult,
) -> tuple[list[HarvestedStation], list[str], int]:
    """Merge harvested codes over existing ones; existing entries always win."""
    conflicts = list(result.conflicts)
    merged: dict[tuple[str, str], HarvestedStation] = {}
    for station in result.stations.values():
        if not is_seoul_metro_station(station):
            continue
        known = existing.get(station.key)
        if known is not None and known != station.code:
            conflicts.append(
                f"{station.line}호선 {station.station_name}: "
                f"existing {known} != harvested {station.code}"
            )
            continue
        merged[station.key] = station

    new_count = sum(1 for key in merged if key not in existing)
    for (name, line), code in existing.items():
        merged.setdefault((name, line), HarvestedStation(name, line, code))
    ordered = sorted(merged.values(), key=lambda item: (int(item.line), item.code))
    return ordered, conflicts, new_count


def render_route_code_yaml(stations: list[HarvestedStation], verified_at: str) -> str:
    lines = [
        "version: 1",
        'source_name: "서울교통공사_최단경로이동정보"',
        f'verified_at: "{verified_at}"',
        "",
        "# Codes returned and accepted by 서울교통공사_최단경로이동정보.",
        "# These are intentionally separate from station_aliases.yaml station_id values.",
        "stations:",
    ]
    lines.extend(
        f'  - {{station_name: "{station.station_name}", line: "{station.line}", '
        f'route_station_code: "{station.code}"}}'
        for station in stations
    )
    return "\n".join(lines) + "\n"


def build_new_alias_entries(
    result: HarvestResult,
    registered: set[tuple[str, str]],
) -> list[HarvestedStation]:
    new_entries = [
        station
        for station in result.stations.values()
        if station.key not in registered and is_seoul_metro_station(station)
    ]
    return sorted(new_entries, key=lambda item: (int(item.line), item.code))


def render_alias_entries(entries: list[HarvestedStation], verified_at: str) -> str:
    if not entries:
        return ""
    lines = [
        f"  # {verified_at}: 최단경로 API 응답으로 검증한 역 등록.",
        "  # 아래 station_id는 해당 API의 stnCd 값을 사용한다.",
    ]
    for station in entries:
        name = station.station_name
        display = name[:-1] if name.endswith("역") else name
        lines.extend(
            [
                f'  - station_name: "{name}"',
                f'    line: "{station.line}"',
                f'    station_id: "{station.code}"',
                f'    aliases: ["{display}역", "{station.line}호선 {display}", '
                f'"Line {station.line} {display}"]',
            ]
        )
    return "\n".join(lines) + "\n"


async def _fetch_first_success(
    client: Any,
    case: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    from app.core.errors import PublicApiError

    last_reason: str | None = None
    for origin in case["origins"]:
        for destination in case["destinations"]:
            try:
                raw = await client.fetch(origin=origin, destination=destination)
            except PublicApiError as exc:
                last_reason = f"{origin}→{destination}: {exc.reason}"
                continue
            if _path_rows(raw):
                return raw, None
            last_reason = f"{origin}→{destination}: empty_path"
    return None, last_reason


async def _verify_code_acceptance(
    client: Any,
    harvested: list[HarvestedStation],
) -> str:
    from app.core.errors import PublicApiError

    if len(harvested) < 2:
        return "SKIPPED"
    origin, destination = harvested[0], harvested[-1]
    if origin.code == destination.code:
        return "SKIPPED"
    try:
        raw = await client.fetch(
            origin=origin.code,
            destination=destination.code,
            station_value_type="code",
        )
    except PublicApiError as exc:
        return f"FAILED:{exc.reason}"
    return "ACCEPTED" if _path_rows(raw) else "FAILED:empty_path"


async def run_collection(args: argparse.Namespace) -> int:
    from app.core.config import AppMode, Settings

    settings_kwargs: dict[str, Any] = {"app_mode": AppMode.LIVE}
    if args.search_date:
        settings_kwargs["route_default_search_date"] = args.search_date
    settings = Settings(**settings_kwargs)

    from app.adapters.shortest_route_client import ShortestRouteClient

    client = ShortestRouteClient(settings)
    result = HarvestResult()
    case_reports: list[dict[str, Any]] = []

    for case in TRAVERSAL_CASES:
        raw, failure = await _fetch_first_success(client, case)
        if raw is None:
            case_reports.append({"name": case["name"], "status": "FAILED", "detail": failure})
            continue
        harvested = extract_station_codes(raw, result)
        acceptance = await _verify_code_acceptance(client, harvested)
        case_reports.append(
            {
                "name": case["name"],
                "status": "OK",
                "hop_stations": len({station.key for station in harvested}),
                "code_request": acceptance,
            }
        )

    existing = load_existing_route_codes()
    ordered, conflicts, new_code_count = merge_route_codes(existing, result)
    registered = load_registered_alias_pairs()
    new_alias_entries = build_new_alias_entries(result, registered)

    report = {
        "cases": case_reports,
        "harvested_pairs": len(result.stations),
        "existing_route_codes": len(existing),
        "new_route_codes": new_code_count,
        "new_alias_entries": len(new_alias_entries),
        "conflicts": conflicts,
        "per_line": {
            line: sorted(
                station.station_name
                for station in result.stations.values()
                if station.line == line
            )
            for line in sorted({station.line for station in result.stations.values()}, key=int)
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if conflicts:
        print("code conflicts detected; files were not modified.", file=sys.stderr)
        return 1
    failed_cases = [case for case in case_reports if case["status"] != "OK"]
    rejected = [case for case in case_reports if case.get("code_request", "").startswith("FAILED")]

    if not args.write:
        return 1 if failed_cases else 0

    if rejected:
        print("code acceptance check failed; files were not modified.", file=sys.stderr)
        return 1

    verified_at = args.verified_at or date.today().isoformat()
    ROUTE_CODE_FILE.write_text(render_route_code_yaml(ordered, verified_at), encoding="utf-8")
    alias_block = render_alias_entries(new_alias_entries, verified_at)
    if alias_block:
        current = STATION_ALIAS_FILE.read_text(encoding="utf-8")
        if not current.endswith("\n"):
            current += "\n"
        STATION_ALIAS_FILE.write_text(current + alias_block, encoding="utf-8")
    print(
        f"wrote {len(ordered)} route codes and {len(new_alias_entries)} new station entries.",
    )
    return 1 if failed_cases else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect verified shortest-route station codes from the live API."
    )
    parser.add_argument("--write", action="store_true", help="Update the data files.")
    parser.add_argument("--search-date", default=None, help="Override route searchDt value.")
    parser.add_argument(
        "--verified-at",
        default=None,
        help="Override the verified_at date written to route_station_codes.yaml.",
    )
    return parser.parse_args()


def main() -> int:
    return asyncio.run(run_collection(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
