from __future__ import annotations

from typing import Any

from app.core.metrics import metrics_registry


def metrics() -> dict[str, Any]:
    return metrics_registry.snapshot()
