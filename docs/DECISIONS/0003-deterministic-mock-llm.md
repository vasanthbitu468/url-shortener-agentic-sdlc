# ADR-0003: Deterministic mock LLM as a first-class mode

Status: Accepted

## Context

Tests, CI and demos must be reproducible, free and offline, and must be able to reach failure paths (bad output, policy violations, failing tests) on demand. Live model output is non-deterministic.

## Decision

`MockLLM` returns scripted JSON from `scenarios/<name>/mock/`, choosing `<stage>.<n>.json` for the n-th call to a stage. `ClaudeLLM` implements the same interface for live runs. Everything after the model call (applying edits, compiling, testing, policies, gates) is identical in both modes.

## Consequences

- Every control path has a deterministic test.
- Scenarios run identically on any machine and in CI.
- Mock runs do not evaluate prompt quality; live mode exists for that and is documented as untested in CI.
