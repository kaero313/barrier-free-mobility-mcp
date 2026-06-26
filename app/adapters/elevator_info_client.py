from __future__ import annotations

from app.adapters.base import HttpPublicApiClient
from app.core.config import Settings


class ElevatorInfoClient(HttpPublicApiClient):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            source_name="elevator_info",
            endpoint_url=settings.elevator_info_api_url,
            api_key=settings.elevator_info_api_key or settings.seoul_open_api_key,
            api_key_field="KEY",
            settings=settings,
            param_aliases={
                "station": settings.elevator_info_station_param,
                "line": settings.elevator_info_line_param,
            },
            default_params={
                settings.api_start_index_param: settings.api_default_start_index,
                settings.api_end_index_param: settings.api_default_end_index,
            },
        )
