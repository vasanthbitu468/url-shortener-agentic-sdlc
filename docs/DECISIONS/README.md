# Architecture decision records

| ADR | Decision | Status |
| --- | --- | --- |
| [ADR-0001](0001-custom-orchestration-engine.md) | Build a custom orchestration engine | Accepted |
| [ADR-0002](0002-sandbox-workspace-and-patch-output.md) | Agents work in a sandbox; the only output is a patch | Accepted |
| [ADR-0003](0003-deterministic-mock-llm.md) | Deterministic mock LLM as a first-class mode | Accepted |
| [ADR-0004](0004-hash-chained-audit-log.md) | Hash-chained event log as the single source of truth | Accepted |
| [ADR-0005](0005-rework-loop-with-bounded-budget.md) | Rework upstream stages, within a budget | Accepted |
| [ADR-0006](0006-reproducible-builds.md) | Pinned dependencies and LF output for reproducibility | Accepted |

Feature-level ADRs produced by orchestrator runs (ADR-001 to ADR-004 in the scenario
designs) live in each run's `design` artifact and in `docs/changes/` once applied.
