from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter, RedactingTextFormatter, configure_logging


def test_json_formatter_redacts_configured_secrets_and_encoded_variants() -> None:
    public_key = "public/key+with=specials"
    seoul_key = "seoul-path-secret-value"
    mcp_token = "mcp-token-with-at-least-32-characters"
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=(
            "GET https://openapi.seoul.go.kr:8088/"
            f"{seoul_key}/json/data/1/5?"
            + "service"
            + "Key=public%2Fkey%2Bwith%3Dspecials "
            f"Authorization: Bearer {mcp_token}"
        ),
        args=(),
        exc_info=None,
    )

    rendered = JsonFormatter(
        sensitive_values=(public_key, seoul_key, mcp_token)
    ).format(record)
    payload = json.loads(rendered)

    assert public_key not in rendered
    assert "public%2Fkey%2Bwith%3Dspecials" not in rendered
    assert seoul_key not in rendered
    assert mcp_token not in rendered
    assert "[REDACTED]" in payload["message"]


def test_text_formatter_redacts_exception_text() -> None:
    secret = "secret-value-embedded-in-exception"
    try:
        raise RuntimeError(f"request failed for {secret}")
    except RuntimeError:
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="upstream request failed",
            args=(),
            exc_info=__import__("sys").exc_info(),
        )

    rendered = RedactingTextFormatter(sensitive_values=(secret,)).format(record)

    assert secret not in rendered
    assert "[REDACTED]" in rendered


def test_configure_logging_suppresses_http_client_request_logs() -> None:
    configure_logging(sensitive_values=("secret",))

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
