from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import perf_counter
from typing import Any


@dataclass
class _LatencyBucket:
    count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0

    def record(self, latency_seconds: float, *, success: bool) -> None:
        self.count += 1
        self.total_latency_ms += latency_seconds * 1000
        if not success:
            self.error_count += 1

    def snapshot(self) -> dict[str, int | float]:
        average = self.total_latency_ms / self.count if self.count else 0.0
        return {
            "count": self.count,
            "error_count": self.error_count,
            "avg_latency_ms": round(average, 2),
        }


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._started_at = datetime.now(UTC)
            self._started_perf = perf_counter()
            self._tool_calls: dict[str, _LatencyBucket] = {}
            self._public_api_calls: dict[str, _LatencyBucket] = {}
            self._cache_events = {"HIT": 0, "MISS": 0, "STALE": 0, "BYPASS": 0}
            self._fallback_response_count = 0
            self._response_status_counts: dict[str, int] = {}

    def record_tool_call(
        self,
        tool_name: str,
        latency_seconds: float,
        *,
        success: bool,
        response_status: str | None = None,
    ) -> None:
        with self._lock:
            bucket = self._tool_calls.setdefault(tool_name, _LatencyBucket())
            bucket.record(latency_seconds, success=success)
            if response_status:
                self._response_status_counts[response_status] = (
                    self._response_status_counts.get(response_status, 0) + 1
                )

    def record_public_api_call(
        self,
        source_name: str,
        latency_seconds: float,
        *,
        success: bool,
    ) -> None:
        with self._lock:
            bucket = self._public_api_calls.setdefault(source_name, _LatencyBucket())
            bucket.record(latency_seconds, success=success)

    def record_cache_event(self, cache_status: str) -> None:
        status = cache_status.upper()
        with self._lock:
            self._cache_events[status] = self._cache_events.get(status, 0) + 1

    def record_fallback_response(self) -> None:
        with self._lock:
            self._fallback_response_count += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            tool_calls = {
                name: bucket.snapshot() for name, bucket in sorted(self._tool_calls.items())
            }
            public_api_calls = {
                name: bucket.snapshot() for name, bucket in sorted(self._public_api_calls.items())
            }
            tool_call_count = sum(bucket.count for bucket in self._tool_calls.values())
            tool_error_count = sum(bucket.error_count for bucket in self._tool_calls.values())
            public_api_call_count = sum(bucket.count for bucket in self._public_api_calls.values())
            public_api_error_count = sum(
                bucket.error_count for bucket in self._public_api_calls.values()
            )
            return {
                "started_at": self._started_at.isoformat(),
                "uptime_seconds": round(perf_counter() - self._started_perf, 2),
                "mcp_tool_call_count": tool_call_count,
                "mcp_tool_error_count": tool_error_count,
                "public_api_call_count": public_api_call_count,
                "public_api_error_count": public_api_error_count,
                "fallback_response_count": self._fallback_response_count,
                "tool_calls": tool_calls,
                "public_api_calls": public_api_calls,
                "cache": dict(self._cache_events),
                "response_status": dict(sorted(self._response_status_counts.items())),
            }


metrics_registry = MetricsRegistry()
