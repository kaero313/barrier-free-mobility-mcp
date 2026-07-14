from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import AppMode
from app.schemas.common import SourceCoverageStatus
from app.services.station_context import StationLookupContext

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_COVERAGE_PATH = DATA_DIR / "source_coverage.yaml"


@dataclass(frozen=True)
class SourceCoverageDecision:
    source_name: str
    status: SourceCoverageStatus
    note: str | None = None


def evaluate_source_coverage(
    source_name: str,
    context: StationLookupContext,
    *,
    app_mode: AppMode,
) -> SourceCoverageDecision:
    if app_mode == AppMode.MOCK:
        return SourceCoverageDecision(
            source_name=source_name,
            status=SourceCoverageStatus.SUPPORTED,
            note="mock fixture 지원 범위",
        )

    registry = _load_coverage_registry()
    source = registry.get("sources", {}).get(source_name)
    if not isinstance(source, dict):
        return SourceCoverageDecision(
            source_name=source_name,
            status=SourceCoverageStatus.UNKNOWN,
            note="데이터 소스 지원 범위가 등록되지 않았습니다.",
        )
    if source.get("coverage_mode") == "query_driven":
        return SourceCoverageDecision(
            source_name=source_name,
            status=SourceCoverageStatus.UNKNOWN,
            note="요청 결과를 기준으로 지원 여부를 판단합니다.",
        )
    if context.operator is None:
        return SourceCoverageDecision(
            source_name=source_name,
            status=SourceCoverageStatus.UNKNOWN,
            note="역 운영기관을 확정하지 못해 데이터 제공 범위를 사전 판정하지 않았습니다.",
        )

    supported_operators = set(source.get("supported_operators", []))
    if context.operator in supported_operators:
        return SourceCoverageDecision(
            source_name=source_name,
            status=SourceCoverageStatus.SUPPORTED,
            note="등록된 데이터 제공 범위에 포함됩니다.",
        )

    station_label = (
        f"{context.line}호선 {context.station_name}역"
        if context.line
        else f"{context.station_name}역"
    )
    coverage_label = source.get("coverage_label", "현재 연결된 공공데이터")
    return SourceCoverageDecision(
        source_name=source_name,
        status=SourceCoverageStatus.UNSUPPORTED,
        note=f"{station_label}은 {coverage_label}의 제공 범위 밖입니다.",
    )


@lru_cache(maxsize=1)
def _load_coverage_registry(path: Path = DEFAULT_COVERAGE_PATH) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}
