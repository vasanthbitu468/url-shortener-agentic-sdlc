# Changelog

## 1.0.0 - 2026-10-31

First complete release for the assessment.

### Added
- Documentation set: architecture overview, scenarios, testing approach, risks and limitations,
  setup guide, engineering summary, six architecture decision records.

## 0.3.0 - Scenarios (PR #3)

### Added
- Greenfield scenario: bulk link creation API.
- Brownfield scenario: click-limited links, additive schema migration, and a fix for the
  idempotent replay of deleted links returning 200.
- Ambiguous scenario: "make links more secure and faster" with ambiguity sign-off and re-planning.
- `scripts/run_scenario.py` to play scenarios with their human steps; recorded runs in
  `runs/samples/`.
- CI runs every scenario and applies each patch to a clean checkout.

### Fixed
- Windows: the API contract export wrote CRLF, so an unchanged contract looked changed and policy
  review blocked it. The export now writes LF, the change detector ignores line-ending-only
  differences, and all orchestrator outputs use LF.

## 0.2.0 - Orchestrator (PR #2)

### Added
- Agentic SDLC orchestrator: explicit DAG of nine stages; entry/exit gates; parallel tests and
  docs with a join; human approval checkpoints; bounded retries with backoff; fallback agent;
  rework with rollback; safe-stop and resume; re-planning on artifact change.
- Policy guardrails (secrets, PII, protected paths, dependencies, diff size, undeclared API or
  schema changes, tests required, lint).
- Sandbox workspace with scoped edits and checkpoints; patch output.
- Hash-chained audit log, decision lineage, reliability metrics; `sdlc` CLI.

## 0.1.0 - Service (PR #1)

### Added
- URL shortener: create (custom alias, expiry, idempotency), redirect, metadata, stats, soft
  delete, health and readiness.
- SSRF protection, privacy-preserving analytics, rate limiting, redirect cache, JSON logs.
- Committed OpenAPI contract with a contract test; Docker; CI.
