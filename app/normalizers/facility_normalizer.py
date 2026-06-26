from __future__ import annotations

from typing import Any

from app.normalizers.helpers import (
    as_bool,
    as_str,
    line_matches,
    pick,
    rows_from_raw,
    station_matches,
)
from app.normalizers.status_normalizer import normalize_status
from app.schemas.facility import AccessibleFacility, FacilityType


def normalize_facility_type(value: object) -> FacilityType:
    text = str(value or "").strip().lower().replace(" ", "").replace("_", "")
    if text in {"es", "e/s", "esc", "escalator"} or "에스컬레이터" in text:
        return FacilityType.ESCALATOR
    if text in {"ev", "e/v", "el", "e/l", "elv", "elevator"} or "엘리베이터" in text:
        return FacilityType.ELEVATOR
    if ("장애인" in text or "교통약자" in text) and "화장실" in text:
        return FacilityType.ACCESSIBLE_RESTROOM
    if "승강기" in text:
        return FacilityType.ELEVATOR
    if "화장실" in text:
        return FacilityType.RESTROOM
    if "휠체어" in text and "충전" in text:
        return FacilityType.WHEELCHAIR_CHARGER
    return FacilityType.UNKNOWN


def normalize_facilities(
    raw: dict[str, Any] | list[dict[str, Any]],
    *,
    station: str | None = None,
    line: str | None = None,
    facility_type: FacilityType | None = None,
) -> list[AccessibleFacility]:
    facilities: list[AccessibleFacility] = []
    for row in rows_from_raw(raw):
        row_station = as_str(
            pick(
                row,
                (
                    "station_name",
                    "station",
                    "stn_nm",
                    "STN_NM",
                    "stnNm",
                    "STATION_NM",
                    "SBWY_STNS_NM",
                    "SUBWAY_STATION_NM",
                    "역명",
                    "전철역명",
                    "지하철역",
                ),
            )
        )
        if not row_station:
            continue
        row_line = as_str(
            pick(
                row,
                (
                    "line",
                    "line_name",
                    "line_num",
                    "LINE_NUM",
                    "LINE_NM",
                    "lineNm",
                    "호선",
                    "노선",
                    "LN_NM",
                    "ROUTE",
                ),
            )
        )
        parsed_type = normalize_facility_type(
            pick(
                row,
                (
                    "facility_type",
                    "type",
                    "ELVTR_SE",
                    "elvtrSe",
                    "시설명",
                    "시설종류",
                    "설비종류",
                    "FCLT_NM",
                    "fcltNm",
                    "FCLT_KIND",
                    "ELVTR_NM",
                    "elvtrNm",
                    "ELVTR_KIND",
                ),
            )
        )
        if facility_type and parsed_type == FacilityType.UNKNOWN:
            parsed_type = facility_type
        if (
            facility_type == FacilityType.ACCESSIBLE_RESTROOM
            and parsed_type == FacilityType.RESTROOM
        ):
            parsed_type = FacilityType.ACCESSIBLE_RESTROOM
        if not station_matches(row_station, station):
            continue
        if not line_matches(row_line, line):
            continue
        if facility_type and parsed_type != facility_type:
            continue

        raw_status = as_str(
            pick(
                row,
                (
                    "status",
                    "state",
                    "운영상태",
                    "상태",
                    "OPR_STTS",
                    "oprtngSitu",
                    "OPERATION",
                    "USE_YN",
                    "useYn",
                    "WORK_YN",
                    "whlchrAcsPsbltyYn",
                    "BD_STATN_NM",
                ),
            )
        )
        facilities.append(
            AccessibleFacility(
                facility_id=as_str(
                    pick(
                        row,
                        (
                            "facility_id",
                            "id",
                            "시설id",
                            "설비번호",
                            "FCLT_ID",
                            "fcltNo",
                            "ELVTR_ID",
                            "elvtrSn",
                            "ESCL_ID",
                        ),
                    )
                ),
                station_name=row_station,
                line=row_line,
                facility_type=parsed_type,
                status=normalize_status(raw_status),
                location_description=as_str(
                    pick(
                        row,
                        (
                            "location",
                            "location_description",
                            "위치",
                            "상세위치",
                            "LOC",
                            "DTL_LOC",
                            "dtlPstn",
                            "INSTL_LOC",
                            "INSTL_PSTN",
                            "FCLT_LOC",
                        ),
                    )
                ),
                inside_gate=as_bool(
                    pick(row, ("inside_gate", "개찰구내부", "게이트내부", "gateInoutSe"))
                ),
                open_time=as_str(pick(row, ("open_time", "운영시간", "OPEN_TIME"))),
                has_emergency_bell=as_bool(
                    pick(row, ("has_emergency_bell", "비상벨", "emergency_bell"))
                ),
                raw_status_text=raw_status,
            )
        )
    return facilities
