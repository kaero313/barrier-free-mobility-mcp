from __future__ import annotations

from datetime import datetime

from app.adapters.base import HttpPublicApiClient
from app.core.config import Settings


class ShortestRouteClient(HttpPublicApiClient):
    def __init__(self, settings: Settings) -> None:
        endpoint_url = settings.shortest_route_api_url
        operation = settings.shortest_route_api_operation.strip()
        if operation and not endpoint_url.rstrip("/").endswith(f"/{operation}"):
            endpoint_url = f"{endpoint_url.rstrip('/')}/{operation}"
        default_params = {
            settings.api_start_index_param: settings.api_default_start_index,
            settings.api_end_index_param: settings.api_default_end_index,
        }
        if settings.route_search_date_param:
            default_params[settings.route_search_date_param] = (
                settings.route_default_search_date
                or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        super().__init__(
            source_name="shortest_route",
            endpoint_url=endpoint_url,
            api_key=settings.public_data_service_key,
            api_key_field="serviceKey",
            settings=settings,
            param_aliases={
                "origin": settings.route_origin_param,
                "destination": settings.route_destination_param,
            },
            default_params=default_params,
        )
