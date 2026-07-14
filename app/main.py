from __future__ import annotations

import inspect

from app.core.config import get_settings
from app.core.http_security import build_http_security_middleware
from app.core.logging import configure_logging
from app.mcp.server import create_mcp_server


def main() -> None:
    settings = get_settings()
    configure_logging(
        settings.log_level,
        settings.log_format,
        sensitive_values=settings.logging_sensitive_values,
    )
    mcp = create_mcp_server(settings)

    run_kwargs = {
        "transport": settings.fastmcp_transport,
        "host": settings.mcp_host,
        "port": settings.mcp_port,
    }
    signature = inspect.signature(mcp.run)
    if "path" in signature.parameters:
        run_kwargs["path"] = settings.mcp_path
    if "mcp_path" in signature.parameters:
        run_kwargs["mcp_path"] = settings.mcp_path
    if "middleware" in signature.parameters or "transport_kwargs" in signature.parameters:
        run_kwargs["middleware"] = build_http_security_middleware(settings)
    mcp.run(**run_kwargs)


if __name__ == "__main__":
    main()
