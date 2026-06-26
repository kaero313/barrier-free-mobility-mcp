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


class DataSourceMeta(BaseModel):
    source_name: str
    source_type: Literal["public_api", "cache", "fixture", "internal"] = "public_api"
    fetched_at: datetime
    cache_status: CacheStatus = CacheStatus.BYPASS
    staleness_seconds: int | None = None
    success: bool = True
    error_message: str | None = None


class FailedSource(BaseModel):
    source_name: str
    reason: str
    recoverable: bool = True


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
