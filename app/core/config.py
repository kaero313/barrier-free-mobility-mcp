from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Self
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(StrEnum):
    MOCK = "mock"
    LIVE = "live"


class CacheBackend(StrEnum):
    MEMORY = "memory"
    REDIS = "redis"


class McpAuthMode(StrEnum):
    NONE = "none"
    STATIC = "static"
    OIDC = "oidc"


MIN_STATIC_MCP_TOKEN_LENGTH = 32
UNSAFE_MCP_API_KEYS = {
    "",
    "change-me",
    "<long-random-token>",
    "<replace-with-at-least-32-random-characters>",
    "replace-me",
    "replace-with-at-least-32-random-characters",
}


class Settings(BaseSettings):
    app_env: str = "local"
    app_mode: AppMode = AppMode.MOCK

    mcp_server_name: str = "Barrier-Free Mobility MCP"
    mcp_transport: str = "streamable-http"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000
    mcp_path: str = "/mcp"
    mcp_auth_mode: McpAuthMode | None = None
    mcp_auth_enabled: bool = False
    mcp_api_key: str = "change-me"
    mcp_public_base_url: str = ""
    mcp_oidc_issuer_url: str = ""
    mcp_oidc_jwks_url: str = ""
    mcp_oidc_audience: str = ""
    mcp_oidc_algorithm: str = "RS256"
    mcp_oidc_required_scopes: str = "mcp:read"
    mcp_oidc_jwks_ssrf_safe: bool = True
    mcp_request_body_limit_enabled: bool = True
    mcp_max_request_body_bytes: int = 1_048_576
    mcp_tool_input_max_chars: int = 120
    mcp_rate_limit_enabled: bool = False
    mcp_rate_limit_per_minute: int = 60
    mcp_rate_limit_window_seconds: int = 60

    public_data_service_key: str = ""
    seoul_open_api_key: str = ""
    elevator_status_api_key: str = ""
    elevator_info_api_key: str = ""
    restroom_api_key: str = ""

    facility_api_url: str = ""
    facility_api_operations: str = "getFcElvtr,getFcEsctr"
    shortest_route_api_url: str = ""
    shortest_route_api_operation: str = "getShtrmPath2"
    elevator_status_api_url: str = ""
    elevator_info_api_url: str = ""
    restroom_api_url: str = ""

    facility_station_param: str = "station"
    facility_line_param: str = "line"
    route_origin_param: str = "dptreStn"
    route_destination_param: str = "arvlStn"
    route_station_value_type_param: str = "stationValueType"
    route_search_date_param: str = "searchDt"
    route_default_search_date: str = ""
    elevator_status_station_param: str = "station"
    elevator_status_line_param: str = "line"
    restroom_station_param: str = "station"
    restroom_line_param: str = "line"
    elevator_info_station_param: str = "station"
    elevator_info_line_param: str = "line"
    api_start_index_param: str = "start_index"
    api_end_index_param: str = "end_index"
    api_default_start_index: int = 1
    api_default_end_index: int = 1000

    http_timeout_seconds: float = 10
    http_max_retries: int = 2
    http_retry_backoff_seconds: float = 0.5
    http_max_connections: int = 20
    http_max_keepalive_connections: int = 10
    http_keepalive_expiry_seconds: float = 30.0
    public_api_page_concurrency: int = 4
    facility_query_concurrency: int = 4

    cache_backend: CacheBackend = CacheBackend.MEMORY
    redis_url: str = "redis://localhost:6379/0"
    cache_stale_ttl_seconds: int = 86400
    redis_socket_timeout_seconds: float = 2.0
    redis_socket_connect_timeout_seconds: float = 2.0
    elevator_status_ttl_seconds: int = 180
    facility_info_ttl_seconds: int = 86400
    route_ttl_seconds: int = 3600
    api_failure_ttl_seconds: int = 60

    log_level: str = "INFO"
    log_format: str = "json"

    mock_failure_sources: set[str] = Field(default_factory=set)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def fastmcp_transport(self) -> str:
        if self.mcp_transport in {"streamable-http", "http"}:
            return "http"
        return self.mcp_transport

    @property
    def effective_mcp_auth_mode(self) -> McpAuthMode:
        if self.mcp_auth_mode is not None:
            return self.mcp_auth_mode
        if self.mcp_auth_enabled:
            return McpAuthMode.STATIC
        return McpAuthMode.NONE

    @property
    def is_mcp_auth_enabled(self) -> bool:
        return self.effective_mcp_auth_mode != McpAuthMode.NONE

    @property
    def mcp_oidc_scope_list(self) -> list[str]:
        raw_scopes = self.mcp_oidc_required_scopes.replace(",", " ")
        return list(dict.fromkeys(scope for scope in raw_scopes.split() if scope))

    @property
    def logging_sensitive_values(self) -> tuple[str, ...]:
        values = (
            self.mcp_api_key,
            self.public_data_service_key,
            self.seoul_open_api_key,
            self.elevator_status_api_key,
            self.elevator_info_api_key,
            self.restroom_api_key,
            self.redis_url,
        )
        return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_mcp_security(self) -> Self:
        auth_mode = self.effective_mcp_auth_mode
        if auth_mode == McpAuthMode.STATIC:
            static_key = self.mcp_api_key.strip()
            if static_key in UNSAFE_MCP_API_KEYS:
                raise ValueError(
                    "MCP_AUTH_MODE=static requires MCP_API_KEY to be set to a non-default value."
                )
            if len(static_key) < MIN_STATIC_MCP_TOKEN_LENGTH:
                raise ValueError(
                    "MCP_AUTH_MODE=static requires MCP_API_KEY to contain at least "
                    f"{MIN_STATIC_MCP_TOKEN_LENGTH} characters."
                )
        if auth_mode == McpAuthMode.OIDC:
            required_values = {
                "MCP_PUBLIC_BASE_URL": self.mcp_public_base_url,
                "MCP_OIDC_ISSUER_URL": self.mcp_oidc_issuer_url,
                "MCP_OIDC_JWKS_URL": self.mcp_oidc_jwks_url,
                "MCP_OIDC_AUDIENCE": self.mcp_oidc_audience,
            }
            missing = [name for name, value in required_values.items() if not value.strip()]
            if missing:
                raise ValueError(
                    "MCP_AUTH_MODE=oidc requires configuration for: "
                    + ", ".join(sorted(missing))
                )
            for name in (
                "mcp_public_base_url",
                "mcp_oidc_issuer_url",
                "mcp_oidc_jwks_url",
            ):
                _validate_auth_url(name, getattr(self, name))
            if self.mcp_oidc_algorithm not in {
                "RS256",
                "RS384",
                "RS512",
                "ES256",
                "ES384",
                "ES512",
                "PS256",
                "PS384",
                "PS512",
            }:
                raise ValueError(
                    "MCP_OIDC_ALGORITHM must be an asymmetric RS*, ES*, or PS* algorithm."
                )
            if not self.mcp_oidc_scope_list:
                raise ValueError("MCP_OIDC_REQUIRED_SCOPES must contain at least one scope.")
        if self.mcp_request_body_limit_enabled and self.mcp_max_request_body_bytes <= 0:
            raise ValueError("MCP_MAX_REQUEST_BODY_BYTES must be greater than 0.")
        if self.mcp_tool_input_max_chars <= 0:
            raise ValueError("MCP_TOOL_INPUT_MAX_CHARS must be greater than 0.")
        if self.mcp_rate_limit_enabled:
            if self.mcp_rate_limit_per_minute <= 0:
                raise ValueError("MCP_RATE_LIMIT_PER_MINUTE must be greater than 0.")
            if self.mcp_rate_limit_window_seconds <= 0:
                raise ValueError("MCP_RATE_LIMIT_WINDOW_SECONDS must be greater than 0.")
        if self.cache_stale_ttl_seconds < 0:
            raise ValueError("CACHE_STALE_TTL_SECONDS must be greater than or equal to 0.")
        if self.redis_socket_timeout_seconds <= 0:
            raise ValueError("REDIS_SOCKET_TIMEOUT_SECONDS must be greater than 0.")
        if self.redis_socket_connect_timeout_seconds <= 0:
            raise ValueError("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS must be greater than 0.")
        if self.http_max_connections <= 0:
            raise ValueError("HTTP_MAX_CONNECTIONS must be greater than 0.")
        if self.http_max_keepalive_connections < 0:
            raise ValueError("HTTP_MAX_KEEPALIVE_CONNECTIONS must be greater than or equal to 0.")
        if self.http_max_keepalive_connections > self.http_max_connections:
            raise ValueError(
                "HTTP_MAX_KEEPALIVE_CONNECTIONS must not exceed HTTP_MAX_CONNECTIONS."
            )
        if self.http_keepalive_expiry_seconds <= 0:
            raise ValueError("HTTP_KEEPALIVE_EXPIRY_SECONDS must be greater than 0.")
        if self.public_api_page_concurrency <= 0:
            raise ValueError("PUBLIC_API_PAGE_CONCURRENCY must be greater than 0.")
        if self.facility_query_concurrency <= 0:
            raise ValueError("FACILITY_QUERY_CONCURRENCY must be greater than 0.")
        return self


def _validate_auth_url(name: str, value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name.upper()} must be an absolute HTTP(S) URL.")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(f"{name.upper()} must use HTTPS outside localhost.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
