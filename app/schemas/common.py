from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ResponseStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class CacheStatus(StrEnum):
    HIT = "HIT"
    MISS = "MISS"
    STALE = "STALE"
    BYPASS = "BYPASS"


class SourceCoverageStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class DataSourceMeta(BaseModel):
    source_name: str
    source_type: Literal["public_api", "cache", "fixture", "internal"] = "public_api"
    fetched_at: datetime
    cache_status: CacheStatus = CacheStatus.BYPASS
    staleness_seconds: int | None = None
    success: bool = True
    error_message: str | None = None
    coverage_status: SourceCoverageStatus = Field(
        default=SourceCoverageStatus.UNKNOWN,
        description=(
            "Whether the requested station/operator is inside this source's registered "
            "coverage. UNSUPPORTED is distinct from an empty successful result."
        ),
    )
    coverage_note: str | None = Field(
        default=None,
        description="User-safe coverage explanation without endpoint or credential data.",
    )


class FailedSource(BaseModel):
    source_name: str
    reason: str
    recoverable: bool = True


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
