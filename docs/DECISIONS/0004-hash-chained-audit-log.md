# ADR-0004: Hash-chained event log as the single source of truth

Status: Accepted

## Context

The orchestrator needs audit-grade traceability and reliability metrics. Keeping counters separate from the log lets them drift, and a plain log can be edited silently.

## Decision

Append every transition to `events.jsonl`. Each event includes the SHA-256 of the previous one. Metrics (`telemetry.py`) and lineage reports are computed only from this log. `sdlc verify` checks the chain.

## Consequences

- Tampering (edit, delete, reorder) is detectable; tested.
- Metrics cannot disagree with the record of what happened.
- Not a database. Fine for one run per process; a production deployment would also anchor the latest hash externally.
