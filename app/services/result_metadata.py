from __future__ import annotations

from app.schemas.common import DataSourceMeta, FailedSource


def dedupe_failed_sources(failed_sources: list[FailedSource]) -> list[FailedSource]:
    seen: set[tuple[str, str]] = set()
    deduped: list[FailedSource] = []
    for source in failed_sources:
        identity = (source.source_name, source.reason)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(source)
    return deduped


def dedupe_data_sources(data_sources: list[DataSourceMeta]) -> list[DataSourceMeta]:
    seen: set[tuple[object, ...]] = set()
    deduped: list[DataSourceMeta] = []
    for source in data_sources:
        identity = (
            source.source_name,
            str(source.source_type),
            str(source.cache_status),
            source.success,
            source.error_message,
            source.coverage_status,
            source.coverage_note,
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(source)
    return deduped


def dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
