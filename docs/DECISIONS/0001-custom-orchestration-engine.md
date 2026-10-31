# ADR-0001: Build a custom orchestration engine

Status: Accepted

## Context

The assessment's differentiator is governed, non-linear orchestration: an explicit dependency graph, entry and exit gates, approvals, bounded retries, fallback, rollback, safe-stop, re-planning and an audit trail. Agent frameworks provide graphs and tool calling, but the governance would still have to be written, and would sit behind framework abstractions that are harder to test and to explain.

## Decision

Write a small engine (`orchestrator/engine.py`, about 600 lines) over an explicit, validated graph (`graph.py`). Agents are plain classes with one method. Gates and policies are pure functions.

## Consequences

- Every control path is visible in one file and covered by an integration test.
- No framework lock-in; the LLM is behind a two-method interface.
- More code to own, and no prebuilt connectors. Acceptable for this scope.
