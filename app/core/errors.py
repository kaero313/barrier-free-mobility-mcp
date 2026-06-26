from __future__ import annotations


class BarrierFreeMobilityError(Exception):
    """Base application exception."""


class PublicApiError(BarrierFreeMobilityError):
    def __init__(self, source_name: str, reason: str, *, recoverable: bool = True) -> None:
        super().__init__(f"{source_name}: {reason}")
        self.source_name = source_name
        self.reason = reason
        self.recoverable = recoverable


class SourceNotConfiguredError(PublicApiError):
    def __init__(self, source_name: str) -> None:
        super().__init__(source_name, "endpoint_url_not_configured", recoverable=True)

