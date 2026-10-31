# ADR-0006: Pinned dependencies and LF output for reproducibility

Status: Accepted

## Context

The API contract is generated from the code and compared byte for byte. Different library versions produced different contracts, and Windows wrote CRLF, which made an unchanged contract look changed and caused a false policy block.

## Decision

Pin all runtime and development dependencies. Write the contract and every orchestrator output with LF. Treat line-ending-only differences as no change in the workspace diff.

## Consequences

- Identical results on Linux and Windows, verified on both.
- Dependency upgrades are deliberate, reviewed changes.
- Regression tests reproduce the Windows condition on any OS.
