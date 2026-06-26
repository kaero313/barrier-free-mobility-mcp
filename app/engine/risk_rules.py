from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from app.schemas.accessibility import RiskReason

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class RiskRule(BaseModel):
    score: int
    severity: Literal["LOW", "CAUTION", "HIGH", "UNKNOWN"]
    message: str


class RiskRuleSet:
    def __init__(self, rules: dict[str, RiskRule]) -> None:
        self.rules = rules

    @classmethod
    def from_yaml(cls, path: Path | None = None) -> RiskRuleSet:
        rule_path = path or DATA_DIR / "risk_rules.yaml"
        raw = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
        return cls(
            {
                code: RiskRule(**payload)
                for code, payload in raw.get("risk_rules", {}).items()
            }
        )

    def reason(self, code: str, *, station_name: str | None = None) -> RiskReason:
        rule = self.rules[code]
        return RiskReason(
            code=code,
            message=rule.message,
            score=rule.score,
            severity=rule.severity,
            station_name=station_name,
        )


DEFAULT_RISK_RULES = RiskRuleSet.from_yaml()

