from __future__ import annotations

from app.schemas.accessibility import RiskLevel, RiskReason
from app.schemas.common import DataSourceMeta, FailedSource

CRITICAL_SOURCES = {"shortest_route", "elevator_status"}


def clamp_score(score: int) -> int:
    return max(0, min(100, score))


def calculate_risk_level(
    score: int,
    *,
    failed_sources: list[FailedSource] | None = None,
) -> RiskLevel:
    failed = failed_sources or []
    if any(source.source_name in CRITICAL_SOURCES for source in failed):
        return "UNKNOWN"
    if score >= 70:
        return "HIGH"
    if score >= 35:
        return "CAUTION"
    return "LOW"


def total_score(reasons: list[RiskReason]) -> int:
    return clamp_score(sum(reason.score for reason in reasons))


def has_stale_data(data_sources: list[DataSourceMeta]) -> bool:
    return any(source.cache_status == "STALE" for source in data_sources)

