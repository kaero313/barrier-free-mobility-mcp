# AGENTS.md — Barrier-Free Mobility MCP

이 파일은 Codex가 repository에서 작업할 때 자동으로 참고해야 하는 개발 지침이다.

## Project Summary

Barrier-Free Mobility MCP is a FastMCP-based server for Seoul subway accessibility checks.
It exposes MCP tools for LLM agents to evaluate route accessibility risks for wheelchair users,
stroller users, and passengers who cannot use stairs or escalators.

This is not a simple public API wrapper. The core feature is `check_accessible_trip`.

## Product Direction

- The server helps users decide what is confirmed, what remains unverified, and what
  they should check before departure. It is not a general subway route planner.
- Prefer improving data accuracy, actionability, and clarity over adding tools, data
  sources, infrastructure, or response fields.
- Do not add a public feature only because it demonstrates a technology. Add it when a
  user scenario, data-quality problem, or operating requirement justifies it.
- Keep the default local deployment small. Memory cache is the default; Redis, OIDC,
  and distributed rate limiting remain optional until the deployment model requires them.

## Non-Negotiable Rules

- Do not build only thin API wrapper tools.
- Do not call an LLM inside the MCP server.
- Do not let an LLM invent risk scores.
- Risk scoring must be deterministic and implemented in `app/engine`.
- All MCP tool outputs must use Pydantic v2 schemas.
- External public API failures must return partial structured responses when possible.
- Never log or return public API service keys.
- Never claim that a route is safe or fully accessible when end-to-end path evidence is
  incomplete.
- Distinguish `confirmed`, `unverified`, `not found`, `unsupported`, and upstream failure.

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
- `answer_accessibility_question(question: str)`

## User-Facing Answer Rules

- `user_message` is the canonical answer for an end user.
- Put the current conclusion and the next required action in the first few lines.
- Prioritize elevator location/status, transfer-path evidence, exit-path evidence, and
  accessible-restroom requirements over travel time or a repeated origin/destination pair.
- Do not repeat the mobility profile unless it changes the decision.
- Use plain Korean headings and short bullets. Use a compact table only when it improves
  scanning, and keep the same information understandable to a screen reader.
- Keep source and checked-at information near the end without hiding missing evidence.
- Ask one concrete clarification at a time when a station, line, or place is ambiguous.

## Scope Control

- Before adding a new tool, API, or infrastructure component, record the user problem,
  expected behavior, failure behavior, and tests that justify it.
- Prefer extending an existing service or structured result over adding another public tool.
- Keep optional operations work out of the critical path for local mock/live use.
- Treat usability feedback as evidence only after it is reproduced in a fixture or test.

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
- canonical `user_message` behavior for representative user questions
- confirmed/unverified evidence separation

## Development Workflow

For complex changes, plan before coding. Split work into small, reviewable diffs.
Use mock mode and fixtures before relying on live public APIs.
Freeze feature expansion while answer quality, data accuracy, or repository reproducibility
has unresolved work.

## Definition of Done

- FastMCP server starts.
- Mock mode works without external API calls.
- `check_accessible_trip` returns `AccessibilityResult`.
- Partial failures include `failed_sources` and `limitations`.
- API keys are never exposed.
- README explains local run, env vars, mock/live mode, and sample tool calls.
- User-facing answers state what is confirmed, what is unverified, and what to do next.
- New behavior has a representative question fixture and regression test.
