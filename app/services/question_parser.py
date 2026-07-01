from __future__ import annotations

import re
from dataclasses import dataclass

from app.normalizers.helpers import normalize_line_name
from app.normalizers.station_normalizer import DEFAULT_STATION_NORMALIZER
from app.schemas.accessibility import (
    AccessibleRestroomRequirement,
    MobilityProfile,
    ParsedAccessibilityQuestion,
    PlaceStationCandidate,
    QuestionIntent,
)
from app.services.place_resolver import (
    ResolvedPlaceMention,
    compact_text,
    overlaps,
    resolve_place_mentions,
)

LINE_PATTERN = re.compile(
    r"(?:(?:line)\s*(?P<line_after>\d+)|(?P<line_before>\d+)\s*호선)",
    re.IGNORECASE,
)
TRANSFER_ONE_PATTERN = re.compile(r"환승\s*1\s*회")


@dataclass(frozen=True)
class AccessibilityQuestionParse:
    intent: QuestionIntent
    parsed: ParsedAccessibilityQuestion


@dataclass(frozen=True)
class StationMention:
    start: int
    end: int
    station_name: str
    line: str | None = None

    @property
    def query(self) -> str:
        return f"{self.line}호선 {self.station_name}" if self.line else self.station_name


@dataclass(frozen=True)
class RouteMention:
    start: int
    end: int
    query: str | None


def parse_accessibility_question(question: str) -> AccessibilityQuestionParse:
    station_mentions = _extract_station_mentions(question)
    place_mentions = resolve_place_mentions(question)
    route_mentions = _route_mentions(station_mentions, place_mentions)
    profile, has_mobility_signal = _parse_mobility_profile(question)
    intent = _detect_intent(question, route_mentions)
    station_mention_texts = [
        mention.query for mention in route_mentions if mention.query is not None
    ]

    origin = route_mentions[0].query if len(route_mentions) == 2 else None
    destination = route_mentions[1].query if len(route_mentions) == 2 else None
    missing_fields = _missing_fields(
        intent,
        origin,
        destination,
        has_mobility_signal,
    )

    return AccessibilityQuestionParse(
        intent=intent,
        parsed=ParsedAccessibilityQuestion(
            origin=origin,
            destination=destination,
            mobility_profile=profile,
            station_mentions=station_mention_texts,
            place_mentions=[
                place.mention
                for place in _place_mentions_for_context(station_mentions, place_mentions)
            ],
            missing_fields=missing_fields,
        ),
    )


def _extract_station_mentions(question: str) -> list[StationMention]:
    compact_question = _compact(question)
    candidates: list[StationMention] = []
    for term, station_name in _station_terms():
        compact_term = _compact(term)
        if not compact_term:
            continue
        start = compact_question.find(compact_term)
        while start >= 0:
            end = start + len(compact_term)
            line = _line_from_term_or_context(term, compact_question[:start])
            candidates.append(
                StationMention(
                    start=start,
                    end=end,
                    station_name=station_name,
                    line=line,
                )
            )
            start = compact_question.find(compact_term, start + 1)

    selected: list[StationMention] = []
    occupied: list[range] = []
    for candidate in sorted(candidates, key=lambda item: (item.start, -(item.end - item.start))):
        candidate_range = range(candidate.start, candidate.end)
        if any(overlaps(candidate_range, used) for used in occupied):
            continue
        if any(existing.station_name == candidate.station_name for existing in selected):
            continue
        selected.append(candidate)
        occupied.append(candidate_range)

    return sorted(selected, key=lambda item: item.start)


def _station_terms() -> list[tuple[str, str]]:
    terms: set[tuple[str, str]] = set()
    for station in DEFAULT_STATION_NORMALIZER.stations:
        for term in {station.station_name, f"{station.station_name}역", *station.aliases}:
            if term:
                terms.add((term, station.station_name))
    return sorted(terms, key=lambda item: len(_compact(item[0])), reverse=True)


def _route_mentions(
    station_mentions: list[StationMention],
    place_mentions: list[ResolvedPlaceMention],
) -> list[RouteMention]:
    route_mentions = [
        RouteMention(
            start=mention.start,
            end=mention.end,
            query=mention.query,
        )
        for mention in station_mentions
    ]
    occupied = [range(mention.start, mention.end) for mention in station_mentions]

    for place in place_mentions:
        place_range = range(place.start, place.end)
        if any(overlaps(place_range, used) for used in occupied):
            continue
        candidates = place.mention.candidates
        route_mentions.append(
            RouteMention(
                start=place.start,
                end=place.end,
                query=_candidate_query(candidates[0]) if len(candidates) == 1 else None,
            )
        )
        occupied.append(place_range)

    return sorted(route_mentions, key=lambda item: item.start)


def _place_mentions_for_context(
    station_mentions: list[StationMention],
    place_mentions: list[ResolvedPlaceMention],
) -> list[ResolvedPlaceMention]:
    station_ranges = [range(mention.start, mention.end) for mention in station_mentions]
    contextual: list[ResolvedPlaceMention] = []
    for place in place_mentions:
        place_range = range(place.start, place.end)
        overlapping = [
            station_range
            for station_range in station_ranges
            if overlaps(place_range, station_range)
        ]
        if not overlapping:
            contextual.append(place)
            continue
        if any((place.end - place.start) > (item.stop - item.start) for item in overlapping):
            contextual.append(place)
    return contextual


def _candidate_query(candidate: PlaceStationCandidate) -> str:
    return (
        f"{candidate.line}호선 {candidate.station_name}"
        if candidate.line
        else candidate.station_name
    )


def _line_from_term_or_context(term: str, compact_prefix: str) -> str | None:
    term_line = _extract_line(term)
    if term_line:
        return term_line
    match = re.search(r"(?:(?:line)(\d+)|(\d+)호선)$", compact_prefix, re.IGNORECASE)
    if not match:
        return None
    return normalize_line_name(match.group(1) or match.group(2))


def _extract_line(value: str) -> str | None:
    match = LINE_PATTERN.search(value)
    if not match:
        return None
    return normalize_line_name(match.group("line_after") or match.group("line_before"))


def _parse_mobility_profile(question: str) -> tuple[MobilityProfile, bool]:
    profile = MobilityProfile()
    has_signal = False

    if _contains_any(question, "휠체어", "전동휠체어"):
        profile.wheelchair = True
        profile.can_use_stairs = False
        profile.can_use_escalator = False
        profile.need_elevator_only = True
        has_signal = True
    if "유모차" in question:
        profile.stroller = True
        profile.can_use_stairs = False
        profile.can_use_escalator = False
        has_signal = True
    if _contains_any(question, "지팡이", "보행기", "목발", "보행약자"):
        profile.cane_or_walker = True
        profile.can_use_stairs = False
        has_signal = True
    if _contains_any(question, "계단 못", "계단 불가", "계단 안", "계단 없이"):
        profile.can_use_stairs = False
        profile.need_elevator_only = True
        has_signal = True
    if _contains_any(
        question,
        "에스컬레이터 못",
        "에스컬레이터 불가",
        "에스컬레이터 안",
    ):
        profile.can_use_escalator = False
        profile.need_elevator_only = True
        has_signal = True
    if _contains_any(question, "엘리베이터만", "엘베만", "승강기만"):
        profile.need_elevator_only = True
        profile.can_use_stairs = False
        profile.can_use_escalator = False
        has_signal = True
    if _contains_any(question, "장애인화장실", "휠체어 화장실"):
        profile.need_accessible_restroom = True
        profile.accessible_restroom_requirement = _restroom_requirement(question)
        has_signal = True

    if "환승 없이" in question:
        profile.max_transfer_count = 0
        has_signal = True
    elif _contains_any(question, "환승 적게", "환승 적은") or TRANSFER_ONE_PATTERN.search(question):
        profile.max_transfer_count = 1
        has_signal = True

    return profile, has_signal


def _restroom_requirement(question: str) -> AccessibleRestroomRequirement:
    if _contains_any(question, "도착역", "도착", "목적지"):
        return AccessibleRestroomRequirement.DESTINATION
    if _contains_any(question, "출발역", "출발"):
        return AccessibleRestroomRequirement.ORIGIN
    if "환승역" in question:
        return AccessibleRestroomRequirement.TRANSFER
    if _contains_any(question, "한 곳", "아무 역", "경로 중"):
        return AccessibleRestroomRequirement.ANY_ROUTE_STATION
    return AccessibleRestroomRequirement.ALL_KEY_STATIONS


def _detect_intent(question: str, mentions: list[RouteMention]) -> QuestionIntent:
    if len(mentions) >= 2:
        return "trip_accessibility"
    if _contains_any(question, "대안", "피해서", "다른 경로", "환승 적은"):
        return "alternative_request"
    if _contains_any(question, "엘베", "엘리베이터", "승강기", "장애인화장실", "화장실", "고장"):
        return "facility_status"
    if _contains_any(question, "갈 수", "가도", "갈만", "가는 길", "까지"):
        return "trip_accessibility"
    return "unknown"


def _missing_fields(
    intent: QuestionIntent,
    origin: str | None,
    destination: str | None,
    has_mobility_signal: bool,
) -> list[str]:
    missing: list[str] = []
    if intent == "trip_accessibility":
        if origin is None:
            missing.append("origin")
        if destination is None:
            missing.append("destination")
        if not has_mobility_signal:
            missing.append("mobility_profile")
    elif intent in {"facility_status", "alternative_request"}:
        missing.append("supported_intent")
    else:
        missing.extend(["origin", "destination", "mobility_profile"])
    return _dedupe(missing)


def _compact(value: str) -> str:
    return compact_text(value)


def _contains_any(value: str, *needles: str) -> bool:
    return any(needle in value for needle in needles)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
