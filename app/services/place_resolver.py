from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.schemas.accessibility import PlaceMention, PlaceStationCandidate

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass(frozen=True)
class ResolvedPlaceMention:
    start: int
    end: int
    mention: PlaceMention


class PlaceResolver:
    def __init__(self, aliases_path: Path | None = None) -> None:
        self.aliases_path = aliases_path or DATA_DIR / "place_aliases.yaml"
        self.places = self._load_places()

    def resolve_mentions(self, question: str) -> list[ResolvedPlaceMention]:
        compact_question = compact_text(question)
        candidates: list[ResolvedPlaceMention] = []
        for place in self.places:
            for alias in place["aliases"]:
                compact_alias = compact_text(alias)
                if not compact_alias:
                    continue
                start = compact_question.find(compact_alias)
                while start >= 0:
                    candidates.append(
                        ResolvedPlaceMention(
                            start=start,
                            end=start + len(compact_alias),
                            mention=PlaceMention(
                                place_name=place["place_name"],
                                matched_text=alias,
                                candidates=[
                                    PlaceStationCandidate(**candidate)
                                    for candidate in place["candidates"]
                                ],
                            ),
                        )
                    )
                    start = compact_question.find(compact_alias, start + 1)

        selected: list[ResolvedPlaceMention] = []
        occupied: list[range] = []
        for candidate in sorted(
            candidates,
            key=lambda item: (item.start, -(item.end - item.start)),
        ):
            candidate_range = range(candidate.start, candidate.end)
            if any(overlaps(candidate_range, used) for used in occupied):
                continue
            if any(item.mention.place_name == candidate.mention.place_name for item in selected):
                continue
            selected.append(candidate)
            occupied.append(candidate_range)

        return sorted(selected, key=lambda item: item.start)

    def _load_places(self) -> list[dict[str, Any]]:
        data: dict[str, Any] = yaml.safe_load(self.aliases_path.read_text(encoding="utf-8"))
        return data.get("places", [])


def compact_text(value: str) -> str:
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"（[^）]*）", "", value)
    return re.sub(r"\s+", "", value).lower()


def overlaps(left: range, right: range) -> bool:
    return left.start < right.stop and right.start < left.stop


DEFAULT_PLACE_RESOLVER = PlaceResolver()


def resolve_place_mentions(question: str) -> list[ResolvedPlaceMention]:
    return DEFAULT_PLACE_RESOLVER.resolve_mentions(question)
