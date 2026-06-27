from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_OUTPUT_DIR = Path("tests/fixtures/live_samples")


async def main() -> None:
    from app.adapters.elevator_info_client import ElevatorInfoClient
    from app.adapters.elevator_status_client import ElevatorStatusClient
    from app.adapters.facility_client import FacilityClient
    from app.adapters.restroom_client import RestroomClient
    from app.adapters.shortest_route_client import ShortestRouteClient
    from app.core.config import AppMode, Settings
    from app.core.errors import PublicApiError

    parser = argparse.ArgumentParser(description="Collect redacted live public API samples.")
    parser.add_argument("--station", default="\ud64d\ub300\uc785\uad6c")
    parser.add_argument("--origin", default="\ud64d\ub300\uc785\uad6c")
    parser.add_argument("--destination", default="\uc0bc\uc131")
    parser.add_argument("--line", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    settings = Settings(app_mode=AppMode.LIVE)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    samples = {
        "facilities_sample.json": (
            FacilityClient(settings),
            {"station": args.station, "line": args.line},
        ),
        "shortest_route_sample.json": (
            ShortestRouteClient(settings),
            {"origin": args.origin, "destination": args.destination},
        ),
        "elevator_status_sample.json": (
            ElevatorStatusClient(settings),
            {"station": args.station, "line": args.line},
        ),
        "elevator_info_sample.json": (
            ElevatorInfoClient(settings),
            {"station": args.station, "line": args.line},
        ),
        "restroom_sample.json": (
            RestroomClient(settings),
            {"station": args.station, "line": args.line},
        ),
    }

    secrets = {
        settings.public_data_service_key,
        settings.seoul_open_api_key,
        settings.elevator_status_api_key,
        settings.elevator_info_api_key,
        settings.restroom_api_key,
        settings.mcp_api_key,
    }
    secrets.update(endpoint_secret_candidates(settings))
    secrets.discard("")

    for filename, (client, params) in samples.items():
        try:
            raw = await client.fetch(**params)
        except PublicApiError as exc:
            print(f"{filename}: skipped ({exc.source_name}:{exc.reason})")
            continue

        output_path = args.output_dir / filename
        redacted = redact_secrets(raw, secrets)
        output_path.write_text(
            json.dumps(redacted, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"{filename}: saved")


def redact_secrets(value: Any, secrets: set[str]) -> Any:
    if isinstance(value, dict):
        return {key: redact_secrets(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item, secrets) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    return value


def endpoint_secret_candidates(settings: Any) -> set[str]:
    candidates: set[str] = set()
    for endpoint in (
        settings.facility_api_url,
        settings.shortest_route_api_url,
        settings.elevator_status_api_url,
        settings.elevator_info_api_url,
        settings.restroom_api_url,
    ):
        parsed = urlparse(endpoint)
        path_segments = [segment for segment in parsed.path.split("/") if segment]
        query_values = [value for _, value in parse_qsl(parsed.query)]
        for value in [*path_segments, *query_values]:
            if _looks_like_secret(value):
                candidates.add(value)
    return candidates


def _looks_like_secret(value: str) -> bool:
    if "{" in value or "}" in value:
        return False
    if len(value) < 20:
        return False
    return any(character.isdigit() for character in value) and any(
        character.isalpha() for character in value
    )


if __name__ == "__main__":
    asyncio.run(main())
