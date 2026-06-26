from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.common import DataSourceMeta, FailedSource


@dataclass
class ServiceResult[T]:
    value: T
    data_sources: list[DataSourceMeta] = field(default_factory=list)
    failed_sources: list[FailedSource] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
