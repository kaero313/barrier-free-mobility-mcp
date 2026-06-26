# AGENTS.md — Barrier-Free Mobility MCP

이 파일은 Codex가 repository에서 작업할 때 자동으로 참고해야 하는 개발 지침이다.

## Project Summary

Barrier-Free Mobility MCP is a FastMCP-based server for Seoul subway accessibility checks.
It exposes MCP tools for LLM agents to evaluate route accessibility risks for wheelchair users,
stroller users, and passengers who cannot use stairs or escalators.

This is not a simple public API wrapper. The core feature is `check_accessible_trip`.

## Non-Negotiable Rules

- Do not build only thin API wrapper tools.
- Do not call an LLM inside the MCP server.
- Do not let an LLM invent risk scores.
- Risk scoring must be deterministic and implemented in `app/engine`.
- All MCP tool outputs must use Pydantic v2 schemas.
- External public API failures must return partial structured responses when possible.
- Never log or return public API service keys.

## Architecture

Keep responsibilities separated:

- `app/mcp`: MCP tools/resources/prompts only.
- `app/adapters`: external public API HTTP calls only.
- `app/normalizers`: convert raw API responses into internal schemas.
- `app/services`: coordinate adapters and normalizers.
- `app/engine`: mobility profile rules, risk scoring, decision engine.
- `app/schemas`: Pydantic input/output schemas.
- `app/cache`: memory/Redis cache abstractions.

## Required MCP Tools

Implement and preserve these tools:

- `resolve_station(query: str)`
- `get_station_facilities(station: str, line: str | None = None)`
- `get_elevator_status(station: str, line: str | None = None)`
- `get_accessible_restroom(station: str, line: str | None = None)`
- `get_route_candidates(origin: str, destination: str)`
- `check_accessible_trip(origin: str, destination: str, mobility_profile: MobilityProfile)`
- `generate_accessibility_brief(origin: str, destination: str, mobility_profile: MobilityProfile)`

## Testing Requirements

Before claiming completion, run:

```bash
uv run pytest
uv run ruff check .
```

Add or update tests for:

- station normalization
- status normalization
- risk scoring
- decision engine
- MCP tools in mock mode
- partial API failure behavior

## Development Workflow

For complex changes, plan before coding. Split work into small, reviewable diffs.
Use mock mode and fixtures before relying on live public APIs.

## Definition of Done

- FastMCP server starts.
- Mock mode works without external API calls.
- `check_accessible_trip` returns `AccessibilityResult`.
- Partial failures include `failed_sources` and `limitations`.
- API keys are never exposed.
- README explains local run, env vars, mock/live mode, and sample tool calls.
