from __future__ import annotations

import asyncio
import re
from time import perf_counter
from typing import Any, Protocol
from urllib.parse import quote, unquote, urlparse, urlunparse
from xml.etree import ElementTree

import httpx

from app.core.config import Settings
from app.core.errors import PublicApiError, SourceNotConfiguredError
from app.core.metrics import metrics_registry


class PublicApiClient(Protocol):
    async def fetch(self, **params: Any) -> dict[str, Any]: ...


class HttpPublicApiClient:
    source_name: str
    endpoint_url: str
    api_key_field: str

    def __init__(
        self,
        *,
        source_name: str,
        endpoint_url: str,
        api_key: str,
        api_key_field: str,
        settings: Settings,
        param_aliases: dict[str, str] | None = None,
        default_params: dict[str, Any] | None = None,
    ) -> None:
        self.source_name = source_name
        self.endpoint_url = endpoint_url
        self.api_key = unquote(api_key)
        self.api_key_field = api_key_field
        self.settings = settings
        self.param_aliases = param_aliases or {}
        self.default_params = default_params or {}

    async def fetch(self, **params: Any) -> dict[str, Any]:
        started = perf_counter()
        try:
            result = await self._fetch_uncounted(**params)
        except Exception:
            metrics_registry.record_public_api_call(
                self.source_name,
                perf_counter() - started,
                success=False,
            )
            raise

        metrics_registry.record_public_api_call(
            self.source_name,
            perf_counter() - started,
            success=True,
        )
        return result

    async def _fetch_uncounted(self, **params: Any) -> dict[str, Any]:
        if not self.endpoint_url:
            raise SourceNotConfiguredError(self.source_name)

        query_params = self._query_params(params)
        if self.api_key:
            query_params[self.api_key_field] = self.api_key
        endpoint_url, query_params = self._format_endpoint_url(self.endpoint_url, query_params)

        last_error: Exception | None = None
        for attempt in range(self.settings.http_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
                    response = await client.get(endpoint_url, params=query_params)
                    response.raise_for_status()
                    data = self._parse_response(response)
                    if not isinstance(data, dict):
                        raise PublicApiError(self.source_name, "non_object_json_response")
                    self._raise_for_api_error(data)
                    return data
            except PublicApiError:
                raise
            except httpx.HTTPStatusError as exc:
                last_error = PublicApiError(
                    self.source_name,
                    f"http_status:{exc.response.status_code}",
                )
                if attempt < self.settings.http_max_retries:
                    await asyncio.sleep(self.settings.http_retry_backoff_seconds * (attempt + 1))
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < self.settings.http_max_retries:
                    await asyncio.sleep(self.settings.http_retry_backoff_seconds * (attempt + 1))

        if isinstance(last_error, PublicApiError):
            reason = last_error.reason
        else:
            reason = type(last_error).__name__ if last_error else "unknown_http_error"
        raise PublicApiError(self.source_name, reason)

    def _query_params(self, params: dict[str, Any]) -> dict[str, Any]:
        query_params = dict(self.default_params)
        for key, value in params.items():
            if value is None:
                continue
            query_params[self.param_aliases.get(key, key)] = value
        return query_params

    def _format_endpoint_url(
        self,
        endpoint_url: str,
        query_params: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        values = {
            **query_params,
            "api_key": self.api_key,
            "service_key": self.api_key,
            "serviceKey": self.api_key,
            "KEY": self.api_key,
            self.api_key_field: self.api_key,
        }
        used_placeholders = set(re.findall(r"{([^{}]+)}", endpoint_url))
        formatted_url = endpoint_url
        for placeholder in used_placeholders:
            value = values.get(placeholder)
            if value is None:
                raise PublicApiError(
                    self.source_name,
                    f"missing_url_placeholder:{placeholder}",
                )
            formatted_url = formatted_url.replace(
                f"{{{placeholder}}}",
                quote(str(value), safe=""),
            )

        remaining_params = {
            key: value for key, value in query_params.items() if key not in used_placeholders
        }
        api_key_placeholders = {"api_key", "service_key", "serviceKey", "KEY", self.api_key_field}
        if self.api_key and used_placeholders.intersection(api_key_placeholders):
            remaining_params.pop(self.api_key_field, None)
        formatted_url, remaining_params = self._format_seoul_open_data_url(
            formatted_url,
            remaining_params,
        )
        return formatted_url, remaining_params

    def _format_seoul_open_data_url(
        self,
        endpoint_url: str,
        query_params: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        parsed = urlparse(endpoint_url)
        if "openapi.seoul.go.kr" not in parsed.netloc or self.api_key_field != "KEY":
            return endpoint_url, query_params

        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) < 5:
            return endpoint_url, query_params

        remaining_params = dict(query_params)
        if self.api_key and segments[0] == "sample":
            segments[0] = quote(self.api_key, safe="")
            remaining_params.pop(self.api_key_field, None)

        start_value = remaining_params.pop(self.settings.api_start_index_param, None)
        end_value = remaining_params.pop(self.settings.api_end_index_param, None)
        if start_value is not None and segments[3].isdigit():
            segments[3] = str(start_value)
        if end_value is not None and segments[4].isdigit():
            segments[4] = str(end_value)

        return (
            urlunparse(parsed._replace(path="/" + "/".join(segments))),
            remaining_params,
        )

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "").lower()
        text = response.text.strip()
        if "json" in content_type or text.startswith("{") or text.startswith("["):
            return response.json()
        if "xml" in content_type or text.startswith("<"):
            return _xml_to_dict(text, self.source_name)
        raise PublicApiError(self.source_name, "unsupported_response_format")

    def _raise_for_api_error(self, data: dict[str, Any]) -> None:
        header = _find_header(data)
        if not header:
            return
        result_code = str(header.get("resultCode") or header.get("RESULT_CODE") or "").strip()
        result_msg = str(header.get("resultMsg") or header.get("RESULT_MSG") or "").strip()
        if result_code and result_code not in {"00", "0", "INFO-000"}:
            raise PublicApiError(
                self.source_name,
                f"api_result:{result_code}:{result_msg[:80]}",
            )


def _xml_to_dict(text: str, source_name: str) -> dict[str, Any]:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise PublicApiError(source_name, "malformed_xml_response") from exc
    return {root.tag: _element_to_value(root)}


def _element_to_value(element: ElementTree.Element) -> Any:
    children = list(element)
    if not children:
        return element.text.strip() if element.text else ""

    grouped: dict[str, Any] = {}
    for child in children:
        value = _element_to_value(child)
        if child.tag in grouped:
            existing = grouped[child.tag]
            if isinstance(existing, list):
                existing.append(value)
            else:
                grouped[child.tag] = [existing, value]
        else:
            grouped[child.tag] = value
    return grouped


def _find_header(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        for key in ("header", "HEADER"):
            header = value.get(key)
            if isinstance(header, dict):
                return header
        for item in value.values():
            found = _find_header(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_header(item)
            if found:
                return found
    return None
