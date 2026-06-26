from __future__ import annotations

from typing import Any

from app.adapters.base import HttpPublicApiClient
from app.core.config import Settings
from app.normalizers.helpers import as_int, rows_from_raw


class ElevatorStatusClient(HttpPublicApiClient):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            source_name="elevator_status",
            endpoint_url=settings.elevator_status_api_url,
            api_key=settings.elevator_status_api_key or settings.seoul_open_api_key,
            api_key_field="KEY",
            settings=settings,
            param_aliases={
                "station": settings.elevator_status_station_param,
                "line": settings.elevator_status_line_param,
            },
            default_params={
                settings.api_start_index_param: settings.api_default_start_index,
                settings.api_end_index_param: settings.api_default_end_index,
            },
        )

    async def fetch(self, **params: Any) -> dict[str, Any]:
        first_page = await super().fetch(**params)
        total_count = _seoul_open_data_total_count(first_page)
        if total_count is None:
            return first_page

        start_key = self.settings.api_start_index_param
        end_key = self.settings.api_end_index_param
        start_index = as_int(params.get(start_key) or self.default_params.get(start_key)) or 1
        end_index = as_int(params.get(end_key) or self.default_params.get(end_key)) or start_index
        if end_index >= total_count:
            return first_page

        page_size = max(1, end_index - start_index + 1)
        pages = [first_page]
        next_start = end_index + 1
        while next_start <= total_count:
            next_end = min(next_start + page_size - 1, total_count)
            pages.append(
                await super().fetch(
                    **{
                        **params,
                        start_key: next_start,
                        end_key: next_end,
                    }
                )
            )
            next_start = next_end + 1

        return _merge_seoul_open_data_pages(pages)


def _seoul_open_data_total_count(raw: dict[str, Any]) -> int | None:
    payload = _seoul_open_data_payload(raw)
    if payload is None:
        return None
    return as_int(payload.get("list_total_count"))


def _merge_seoul_open_data_pages(pages: list[dict[str, Any]]) -> dict[str, Any]:
    if not pages:
        return {}

    merged = pages[0].copy()
    payload = _seoul_open_data_payload(merged)
    if payload is None:
        return merged

    rows: list[dict[str, Any]] = []
    for page in pages:
        rows.extend(rows_from_raw(page))
    payload["row"] = rows
    return merged


def _seoul_open_data_payload(raw: dict[str, Any]) -> dict[str, Any] | None:
    for value in raw.values():
        if isinstance(value, dict) and "list_total_count" in value:
            return value
    return None
