from __future__ import annotations

import yaml

from scripts.collect_route_station_codes import (
    HarvestedStation,
    HarvestResult,
    build_new_alias_entries,
    extract_station_codes,
    merge_route_codes,
    render_alias_entries,
    render_route_code_yaml,
)


def _hop(
    from_name: str,
    from_code: str,
    to_name: str,
    to_code: str,
    line: str = "2호선",
) -> dict[str, object]:
    return {
        "dptreStn": {"stnCd": from_code, "stnNm": from_name, "lineNm": line},
        "arvlStn": {"stnCd": to_code, "stnNm": to_name, "lineNm": line},
        "tmnlStnNm": "성수",
        "tmnlStnCd": "0211",
        "trsitYn": "N",
    }


def _raw(rows: list[dict[str, object]]) -> dict[str, object]:
    return {"document": {"body": {"paths": {"path": rows}}}}


def test_extract_station_codes_collects_both_endpoints_and_ignores_terminal() -> None:
    result = HarvestResult()
    harvested = extract_station_codes(
        _raw(
            [
                _hop("시청", "0201", "을지로입구", "0202"),
                _hop("을지로입구", "0202", "을지로3가", "0203"),
            ]
        ),
        result,
    )

    keys = {station.key for station in harvested}
    assert ("시청", "2") in keys
    assert ("을지로입구", "2") in keys
    assert ("을지로3가", "2") in keys
    # tmnlStnCd has no line information and is not part of the requested path.
    assert all(station.code != "0211" for station in result.stations.values())


def test_extract_station_codes_keeps_lines_separate_for_transfer_rows() -> None:
    result = HarvestResult()
    extract_station_codes(
        _raw(
            [
                {
                    "dptreStn": {"stnCd": "0222", "stnNm": "강남", "lineNm": "2호선"},
                    "arvlStn": {"stnCd": "0223", "stnNm": "교대", "lineNm": "2호선"},
                    "trsitYn": "N",
                },
                {
                    "dptreStn": {"stnCd": "0223", "stnNm": "교대", "lineNm": "2호선"},
                    "arvlStn": {"stnCd": "0330", "stnNm": "교대", "lineNm": "3호선"},
                    "trsitYn": "Y",
                },
            ]
        ),
        result,
    )

    assert result.stations[("교대", "2")].code == "0223"
    assert result.stations[("교대", "3")].code == "0330"
    assert not result.conflicts


def test_extract_station_codes_records_conflicting_codes() -> None:
    result = HarvestResult()
    extract_station_codes(_raw([_hop("시청", "0201", "을지로입구", "0202")]), result)
    extract_station_codes(_raw([_hop("시청", "9999", "을지로입구", "0202")]), result)

    assert result.stations[("시청", "2")].code == "0201"
    assert any("시청" in conflict for conflict in result.conflicts)


def test_extract_station_codes_skips_rows_outside_line_1_to_9() -> None:
    result = HarvestResult()
    extract_station_codes(
        _raw(
            [
                {
                    "dptreStn": {"stnCd": "K101", "stnNm": "가좌", "lineNm": "경의중앙선"},
                    "arvlStn": {"stnCd": "0239", "stnNm": "홍대입구", "lineNm": "2호선"},
                }
            ]
        ),
        result,
    )

    assert list(result.stations) == [("홍대입구", "2")]


def test_korail_line1_ground_section_is_not_recorded() -> None:
    result = HarvestResult()
    result.add(HarvestedStation("영등포", "1", "1005"))
    result.add(HarvestedStation("종각", "1", "0152"))

    ordered, conflicts, new_count = merge_route_codes({}, result)
    entries = build_new_alias_entries(result, registered=set())

    assert not conflicts
    assert new_count == 1
    assert [station.station_name for station in ordered] == ["종각"]
    assert [entry.station_name for entry in entries] == ["종각"]


def test_merge_route_codes_prefers_existing_and_reports_conflicts() -> None:
    existing = {("시청", "2"): "0201", ("잠실", "2"): "0216"}
    result = HarvestResult()
    extract_station_codes(_raw([_hop("시청", "0201", "을지로입구", "0202")]), result)
    result.add(HarvestedStation("잠실", "2", "8888"))

    ordered, conflicts, new_count = merge_route_codes(existing, result)

    assert new_count == 1
    assert any("잠실" in conflict for conflict in conflicts)
    pairs = {(station.station_name, station.line): station.code for station in ordered}
    assert pairs[("잠실", "2")] == "0216"
    assert pairs[("을지로입구", "2")] == "0202"


def test_render_route_code_yaml_round_trips() -> None:
    stations = [
        HarvestedStation("서울역", "1", "0150"),
        HarvestedStation("을지로입구", "2", "0202"),
    ]

    text = render_route_code_yaml(stations, "2026-08-01")
    payload = yaml.safe_load(text)

    assert payload["verified_at"] == "2026-08-01"
    assert payload["stations"] == [
        {"station_name": "서울역", "line": "1", "route_station_code": "0150"},
        {"station_name": "을지로입구", "line": "2", "route_station_code": "0202"},
    ]


def test_build_new_alias_entries_skips_registered_pairs() -> None:
    result = HarvestResult()
    extract_station_codes(_raw([_hop("시청", "0201", "을지로입구", "0202")]), result)

    entries = build_new_alias_entries(result, registered={("시청", "2")})

    assert [entry.station_name for entry in entries] == ["을지로입구"]


def test_render_alias_entries_generates_line_scoped_aliases() -> None:
    entries = [HarvestedStation("을지로입구", "2", "0202")]

    text = render_alias_entries(entries, "2026-08-01")
    payload = yaml.safe_load(text)

    assert payload == [
        {
            "station_name": "을지로입구",
            "line": "2",
            "station_id": "0202",
            "aliases": ["을지로입구역", "2호선 을지로입구", "Line 2 을지로입구"],
        }
    ]


def test_render_alias_entries_handles_names_with_station_suffix() -> None:
    entries = [HarvestedStation("서울역", "1", "0150")]

    payload = yaml.safe_load(render_alias_entries(entries, "2026-08-01"))

    assert payload[0]["aliases"] == ["서울역", "1호선 서울", "Line 1 서울"]
