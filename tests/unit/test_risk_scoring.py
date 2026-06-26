from __future__ import annotations

from app.engine.risk_rules import DEFAULT_RISK_RULES
from app.engine.risk_scoring import calculate_risk_level, clamp_score, total_score
from app.schemas.common import FailedSource


def test_risk_score_clamps_and_levels() -> None:
    reasons = [
        DEFAULT_RISK_RULES.reason("elevator_unavailable"),
        DEFAULT_RISK_RULES.reason("elevator_unavailable"),
        DEFAULT_RISK_RULES.reason("too_many_transfers"),
    ]

    assert total_score(reasons) == 100
    assert clamp_score(-10) == 0
    assert calculate_risk_level(70) == "HIGH"
    assert calculate_risk_level(35) == "CAUTION"
    assert calculate_risk_level(10) == "LOW"


def test_critical_failed_source_forces_unknown() -> None:
    failed = [FailedSource(source_name="elevator_status", reason="timeout")]

    assert calculate_risk_level(10, failed_sources=failed) == "UNKNOWN"

