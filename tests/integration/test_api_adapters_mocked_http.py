from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters.base import HttpPublicApiClient
from app.adapters.elevator_status_client import ElevatorStatusClient
from app.adapters.facility_client import FacilityClient
from app.core.config import AppMode, Settings
from app.core.errors import PublicApiError, SourceNotConfiguredError


@respx.mock
async def test_http_adapter_returns_raw_response_without_transforming() -> None:
    settings = Settings(_env_file=None, app_mode=AppMode.LIVE, http_max_retries=0)
    route = respx.get("https://example.test/facility").mock(
        return_value=httpx.Response(200, json={"rows": [{"raw": "value"}]})
    )
    client = HttpPublicApiClient(
        source_name="facility_info",
        endpoint_url="https://example.test/facility",
        api_key="SECRET-SERVICE-KEY",
        api_key_field="serviceKey",
        settings=settings,
    )

    response = await client.fetch(station="홍대입구")

    assert response == {"rows": [{"raw": "value"}]}
    assert route.called
    assert "SECRET-SERVICE-KEY" in str(route.calls[0].request.url)


@respx.mock
async def test_http_adapter_wraps_timeout_without_key_in_exception() -> None:
    settings = Settings(_env_file=None, app_mode=AppMode.LIVE, http_max_retries=0)
    respx.get("https://example.test/status").mock(side_effect=httpx.ConnectTimeout("timeout"))
    client = HttpPublicApiClient(
        source_name="elevator_status",
        endpoint_url="https://example.test/status",
        api_key="SECRET-SERVICE-KEY",
        api_key_field="serviceKey",
        settings=settings,
    )

    with pytest.raises(PublicApiError) as exc_info:
        await client.fetch(station="홍대입구")

    assert "SECRET-SERVICE-KEY" not in str(exc_info.value)
    assert exc_info.value.source_name == "elevator_status"


@respx.mock
async def test_http_adapter_reports_status_code_without_key() -> None:
    settings = Settings(_env_file=None, app_mode=AppMode.LIVE, http_max_retries=0)
    respx.get("https://example.test/fail").mock(return_value=httpx.Response(404))
    client = HttpPublicApiClient(
        source_name="facility_info",
        endpoint_url="https://example.test/fail",
        api_key="SECRET-SERVICE-KEY",
        api_key_field="serviceKey",
        settings=settings,
    )

    with pytest.raises(PublicApiError) as exc_info:
        await client.fetch()

    assert exc_info.value.reason == "http_status:404"
    assert "SECRET-SERVICE-KEY" not in str(exc_info.value)


def test_http_adapter_decodes_url_encoded_api_key_before_request() -> None:
    settings = Settings(_env_file=None, app_mode=AppMode.LIVE, http_max_retries=0)
    client = HttpPublicApiClient(
        source_name="facility_info",
        endpoint_url="https://example.test/facility",
        api_key="ABC%2F123",
        api_key_field="serviceKey",
        settings=settings,
    )

    assert client.api_key == "ABC/123"


@respx.mock
async def test_facility_client_fetches_configured_operations() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        public_data_service_key="SECRET",
        facility_api_url="https://example.test/facility",
        facility_api_operations="getFcElvtr,getFcEsctr",
        api_start_index_param="pageNo",
        api_end_index_param="numOfRows",
        http_max_retries=0,
    )
    respx.get("https://example.test/facility/getFcElvtr").mock(
        return_value=httpx.Response(200, json={"rows": [{"facility_type": "엘리베이터"}]})
    )
    respx.get("https://example.test/facility/getFcEsctr").mock(
        return_value=httpx.Response(200, json={"rows": [{"facility_type": "에스컬레이터"}]})
    )

    response = await FacilityClient(settings).fetch(station="홍대입구")

    assert response == {
        "rows": [
            {"facility_type": "엘리베이터"},
            {"facility_type": "에스컬레이터"},
        ]
    }


async def test_http_adapter_requires_configured_endpoint() -> None:
    settings = Settings(_env_file=None, app_mode=AppMode.LIVE)
    client = HttpPublicApiClient(
        source_name="restroom",
        endpoint_url="",
        api_key="SECRET",
        api_key_field="KEY",
        settings=settings,
    )

    with pytest.raises(SourceNotConfiguredError):
        await client.fetch()


@respx.mock
async def test_http_adapter_supports_url_templates() -> None:
    settings = Settings(_env_file=None, app_mode=AppMode.LIVE, http_max_retries=0)
    route = respx.get("https://example.test/SECRET/json/facility/1/5/Hongdae").mock(
        return_value=httpx.Response(200, json={"rows": []})
    )
    client = HttpPublicApiClient(
        source_name="facility_info",
        endpoint_url="https://example.test/{service_key}/json/facility/{start}/{end}/{station}",
        api_key="SECRET",
        api_key_field="serviceKey",
        settings=settings,
        default_params={"start": 1, "end": 5},
    )

    response = await client.fetch(station="Hongdae")

    assert response == {"rows": []}
    assert route.called
    assert route.calls[0].request.url.query == b""


@respx.mock
async def test_http_adapter_converts_seoul_sample_url_to_keyed_path() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        api_start_index_param="pageNo",
        api_end_index_param="numOfRows",
        api_default_start_index=1,
        api_default_end_index=100,
        http_max_retries=0,
    )
    route = respx.get("http://openapi.seoul.go.kr:8088/SECRET/xml/getWksnElvtr/1/100").mock(
        return_value=httpx.Response(200, content="<root />", headers={"content-type": "text/xml"})
    )
    client = HttpPublicApiClient(
        source_name="elevator_info",
        endpoint_url="http://openapi.seoul.go.kr:8088/sample/xml/getWksnElvtr/1/5",
        api_key="SECRET",
        api_key_field="KEY",
        settings=settings,
        default_params={
            settings.api_start_index_param: settings.api_default_start_index,
            settings.api_end_index_param: settings.api_default_end_index,
        },
    )

    response = await client.fetch()

    assert response == {"root": ""}
    assert route.called
    assert route.calls[0].request.url.query == b""


@respx.mock
async def test_elevator_status_client_fetches_all_seoul_open_data_pages() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        elevator_status_api_key="SECRET",
        elevator_status_api_url="http://openapi.seoul.go.kr:8088/sample/json/SeoulMetroFaciInfo/1/5",
        api_start_index_param="pageNo",
        api_end_index_param="numOfRows",
        api_default_start_index=1,
        api_default_end_index=2,
        http_max_retries=0,
    )
    respx.get("http://openapi.seoul.go.kr:8088/SECRET/json/SeoulMetroFaciInfo/1/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "SeoulMetroFaciInfo": {
                    "list_total_count": "5",
                    "RESULT": {"CODE": "INFO-000", "MESSAGE": "OK"},
                    "row": [{"STN_NM": "A"}, {"STN_NM": "B"}],
                }
            },
        )
    )
    respx.get("http://openapi.seoul.go.kr:8088/SECRET/json/SeoulMetroFaciInfo/3/4").mock(
        return_value=httpx.Response(
            200,
            json={
                "SeoulMetroFaciInfo": {
                    "list_total_count": "5",
                    "RESULT": {"CODE": "INFO-000", "MESSAGE": "OK"},
                    "row": [{"STN_NM": "C"}, {"STN_NM": "D"}],
                }
            },
        )
    )
    respx.get("http://openapi.seoul.go.kr:8088/SECRET/json/SeoulMetroFaciInfo/5/5").mock(
        return_value=httpx.Response(
            200,
            json={
                "SeoulMetroFaciInfo": {
                    "list_total_count": "5",
                    "RESULT": {"CODE": "INFO-000", "MESSAGE": "OK"},
                    "row": [{"STN_NM": "E"}],
                }
            },
        )
    )

    response = await ElevatorStatusClient(settings).fetch()

    assert response["SeoulMetroFaciInfo"]["row"] == [
        {"STN_NM": "A"},
        {"STN_NM": "B"},
        {"STN_NM": "C"},
        {"STN_NM": "D"},
        {"STN_NM": "E"},
    ]


@respx.mock
async def test_elevator_status_client_reports_later_page_failure_without_key() -> None:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.LIVE,
        elevator_status_api_key="SECRET",
        elevator_status_api_url="http://openapi.seoul.go.kr:8088/sample/json/SeoulMetroFaciInfo/1/5",
        api_start_index_param="pageNo",
        api_end_index_param="numOfRows",
        api_default_start_index=1,
        api_default_end_index=2,
        http_max_retries=0,
    )
    respx.get("http://openapi.seoul.go.kr:8088/SECRET/json/SeoulMetroFaciInfo/1/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "SeoulMetroFaciInfo": {
                    "list_total_count": "3",
                    "RESULT": {"CODE": "INFO-000", "MESSAGE": "OK"},
                    "row": [{"STN_NM": "A"}, {"STN_NM": "B"}],
                }
            },
        )
    )
    respx.get("http://openapi.seoul.go.kr:8088/SECRET/json/SeoulMetroFaciInfo/3/3").mock(
        return_value=httpx.Response(500)
    )

    with pytest.raises(PublicApiError) as exc_info:
        await ElevatorStatusClient(settings).fetch()

    assert exc_info.value.source_name == "elevator_status"
    assert exc_info.value.reason == "http_status:500"
    assert "SECRET" not in str(exc_info.value)


@respx.mock
async def test_http_adapter_parses_xml_response() -> None:
    settings = Settings(_env_file=None, app_mode=AppMode.LIVE, http_max_retries=0)
    xml = """
    <response>
      <body>
        <items>
          <item>
            <STN_NM>홍대입구</STN_NM>
            <OPR_STTS>정상</OPR_STTS>
          </item>
        </items>
      </body>
    </response>
    """
    respx.get("https://example.test/xml").mock(
        return_value=httpx.Response(200, content=xml, headers={"content-type": "text/xml"})
    )
    client = HttpPublicApiClient(
        source_name="elevator_status",
        endpoint_url="https://example.test/xml",
        api_key="",
        api_key_field="serviceKey",
        settings=settings,
    )

    response = await client.fetch()

    assert response["response"]["body"]["items"]["item"]["STN_NM"] == "홍대입구"
