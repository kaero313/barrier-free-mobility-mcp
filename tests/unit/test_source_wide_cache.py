from __future__ import annotations

import asyncio

from app.cache.memory_cache import MemoryTTLCache
from app.core.config import AppMode, Settings
from app.services import client_factory
from app.services.facility_service import FacilityService


class _CountingFacilityClient:
    def __init__(self) -> None:
        self.fetch_count = 0
        self.params: list[dict[str, object]] = []

    async def fetch(self, **params):
        self.fetch_count += 1
        self.params.append(params)
        await asyncio.sleep(0.01)
        return {
            "rows": [
                {
                    "station_name": "홍대입구",
                    "line": "2",
                    "facility_id": "HONG-EV-1",
                    "facility_type": "엘리베이터",
                    "status": "정상",
                },
                {
                    "station_name": "삼성",
                    "line": "2",
                    "facility_id": "SAMS-EV-1",
                    "facility_type": "엘리베이터",
                    "status": "정상",
                },
            ]
        }


async def test_facility_source_is_fetched_once_then_filtered_per_station(
    monkeypatch,
) -> None:
    settings = Settings(_env_file=None, app_mode=AppMode.LIVE)
    client = _CountingFacilityClient()
    monkeypatch.setattr(client_factory, "facility_client", lambda _settings: client)
    service = FacilityService(settings, MemoryTTLCache())

    hongdae, samsung = await asyncio.gather(
        service.get_station_facilities("홍대입구", line="2"),
        service.get_station_facilities("삼성", line="2"),
    )

    assert client.fetch_count == 1
    assert client.params == [{}]
    assert [item.station_name for item in hongdae.value] == ["홍대입구"]
    assert [item.station_name for item in samsung.value] == ["삼성"]
