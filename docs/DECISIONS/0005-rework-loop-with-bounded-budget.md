# ADR-0005: Rework upstream stages, within a budget

Status: Accepted

## Context

When tests or policy review fail after retries, retrying the same stage cannot help: the defect is in the implementation. Unbounded loops between stages are a known failure mode of agent systems.

## Decision

Stages may declare a `rework_target` upstream. When their retries are exhausted, the engine rolls the workspace back to the target's checkpoint, resets the target and everything downstream, and passes the failure in as feedback. Each run has a rework budget (default 2); when it is spent, the run fails and nothing is released.

## Consequences

- Defects found late are fixed where they originate.
- Loops are impossible by construction.
- Rework currently always targets implementation; letting gates name the faulty stage is future work.
