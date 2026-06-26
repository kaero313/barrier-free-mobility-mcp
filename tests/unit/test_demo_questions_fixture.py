from __future__ import annotations

from pathlib import Path

import yaml

DEMO_QUESTIONS = Path(__file__).resolve().parents[1] / "fixtures" / "demo_questions.yaml"


def test_demo_questions_cover_expected_user_patterns() -> None:
    questions = yaml.safe_load(DEMO_QUESTIONS.read_text(encoding="utf-8"))

    assert "강남역 엘베 고장났어?" in questions["facility_status"]
    assert "홍대에서 코엑스 가는데 문제 없을까?" in questions["trip_accessibility"]
    assert "엘리베이터 고장난 역 피해서 갈 수 있어?" in questions["alternatives"]
    assert "강남역 괜찮아?" in questions["ambiguous"]
