from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.errors import PublicApiError

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "mock_responses"


class FixtureClient:
    def __init__(
        self,
        source_name: str,
        filename: str,
        *,
        failure_sources: set[str] | None = None,
    ) -> None:
        self.source_name = source_name
        self.filename = filename
        self.failure_sources = failure_sources or set()

    async def fetch(self, **params: Any) -> dict[str, Any]:
        if self.source_name in self.failure_sources:
            raise PublicApiError(self.source_name, "mock_failure")
        path = DATA_DIR / self.filename
        return json.loads(path.read_text(encoding="utf-8"))

