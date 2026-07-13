from __future__ import annotations

from typing import Any

from app.adapters.base import HttpPublicApiClient
from app.core.concurrency import gather_limited
from app.core.config import Settings
from app.normalizers.helpers import rows_from_raw


class FacilityClient(HttpPublicApiClient):
    def __init__(self, settings: Settings) -> None:
        self.operations = [
            operation.strip()
            for operation in settings.facility_api_operations.split(",")
            if operation.strip()
        ]
        super().__init__(
            source_name="facility_info",
            endpoint_url=settings.facility_api_url,
            api_key=settings.public_data_service_key,
            api_key_field="serviceKey",
            settings=settings,
            param_aliases={
                "station": settings.facility_station_param,
                "line": settings.facility_line_param,
            },
            default_params={
                settings.api_start_index_param: settings.api_default_start_index,
                settings.api_end_index_param: settings.api_default_end_index,
            },
        )

    async def fetch(self, **params: Any) -> dict[str, Any]:
        if not self.operations:
            return await super().fetch(**params)

        responses = await gather_limited(
            (
                lambda operation=operation: self.fetch_endpoint(
                    f"{self.endpoint_url.rstrip('/')}/{operation}",
                    **params,
                )
                for operation in self.operations
            ),
            limit=self.settings.public_api_page_concurrency,
        )
        rows: list[dict[str, Any]] = []
        for raw in responses:
            rows.extend(rows_from_raw(raw))
        return {"rows": rows}
