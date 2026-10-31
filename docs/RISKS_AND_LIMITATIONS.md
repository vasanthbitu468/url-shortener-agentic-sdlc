# Risks, trade-offs, assumptions and limitations

## Risk register

| # | Risk | Likelihood | Impact | Mitigation in place | Residual |
| --- | --- | --- | --- | --- | --- |
| R1 | An agent produces wrong or harmful code | Medium | High | Sandbox workspace; agents cannot touch the repository; compile, test and policy gates; human approval of design and release; output is a patch reviewed in a normal PR | Defects that pass tests and review |
| R2 | An agent leaks a secret into code | Medium | High | `security.no_secrets` rule (API keys, AWS keys, GitHub tokens, private keys, hard-coded credentials) blocks review and triggers rework; demonstrated in the demo scenario | Secrets in formats the patterns miss |
| R3 | An agent edits outside its remit (CI config, the orchestrator, policies) | Low | High | Per-stage allowed paths enforced before any write; `change_control.protected_paths` blocks `.github/`, `orchestrator/`, `scenarios/`, `.env`; demonstrated in the greenfield scenario | - |
| R4 | Silent API or schema change | Medium | High | Contract test; API-contract and schema policies require the design to declare changes; such designs need human approval; schema changes need approval again at release | - |
| R5 | Endless retry or rework loop | Low | Medium | Bounded attempts per stage (3), bounded reworks per run (2), then the run fails safely with nothing released | - |
| R6 | Misinterpreted vague requirement | High | Medium | Requirements gate demands a default for every ambiguity; human sign-off when ambiguities exist; re-planning when the spec changes later | Ambiguities the agent does not notice |
| R7 | Tampered audit trail | Low | High | SHA-256 hash chain; `sdlc verify`; tests prove edits are detected | An attacker who rewrites the whole chain; mitigate by anchoring the last hash externally |
| R8 | Lost state on crash | Low | Medium | Atomic state writes after every transition; stages restart from their checkpoint on resume | An agent that crashes mid-write leaves a workspace the next attempt rolls back |
| R9 | Platform-specific behaviour | Medium | Medium | LF output everywhere, line-ending-insensitive diff, pinned dependencies, suite run on Linux (CI) and Windows | Untested platforms |
| R10 | Over-reliance on mock runs | Medium | Medium | Mock mode tests the orchestration, not the prompts; live mode uses the same code path; scenarios use code that was written and tested for real | Prompt quality in live mode is not regression-tested |

Service-level risks are listed in the README (in-process rate limiter and cache, DNS not
resolved in the SSRF check, no authentication).

## Trade-offs

| Chose | Over | Because | Cost |
| --- | --- | --- | --- |
| Custom engine | LangGraph, CrewAI or similar | Governance is the deliverable; every gate, transition and rollback must be explicit, testable and auditable | More code; fewer prebuilt integrations |
| Deterministic mock LLM as a primary mode | Live calls only | Reproducible tests, CI and demos; failures can be scripted precisely | Mock runs say nothing about prompt quality |
| Patch output + human merge | Agents committing to branches | The repository is never changed without a human; review uses familiar tools | One manual step per change |
| JSON file state + JSONL log | A database | Zero infrastructure; human-readable; easy to inspect and verify | One process per run; not built for many concurrent runs |
| Pattern-based policies | LLM-based review | Predictable, explainable, testable; no model judging a model | Misses semantic issues; complemented by human review |
| Rollback by directory scope | Git branches per stage | Simple, fast, platform-independent; parallel stages have disjoint scopes | Coarse: a scope is restored whole |
| Re-plan everything downstream of a changed input | Fine-grained diffing of what changed | Always correct; easy to reason about | Re-runs stages whose output might not have changed |
| Approximate click limit (brownfield) | Strict exactly-N | No transactional counter on the hot redirect path | Concurrent clicks can overshoot by the number in flight |
| Additive startup migration (brownfield) | Adopting Alembic now | Smallest safe step; refuses anything non-additive | Destructive changes still need a reviewed migration |

## Assumptions

- One operator drives a given run at a time. Several runs can exist side by side.
- Agents return JSON in the schema each prompt specifies; anything else is a failed attempt.
- The service's own test suite is the definition of "works". Agents must add tests, and the
  whole suite must pass.
- Humans approving a stage have read its artifacts (`runs/<id>/artifacts/`) or the summary.
- The repository layout (`service/`, `tests/`, `docs/`) is stable; the workspace copies those.
- Scenario mock responses stand in for an LLM. Their code was written and tested for real, but
  the agents did not generate it in these recordings.

## Limitations

| Limitation | Effect | Possible next step |
| --- | --- | --- |
| Agent timeout cannot kill the thread | A timed-out agent keeps running until it returns; its result is discarded | Run agents in subprocesses |
| State file is not locked | Two processes driving the same run could conflict | File lock or a small database |
| Workspace copies only `service/`, `tests/`, `scripts/`, `docs/` and two files | Changes elsewhere are impossible by design, but legitimate ones too (for example the Dockerfile) | Make the include list part of the pipeline config |
| Rework always targets `implementation` | A design flaw found in testing reworks code, not design | Let gates name the stage at fault |
| Policies are regex rules | Can miss secrets in unusual formats or semantic problems | Add `gitleaks`/`bandit`, keep human review |
| Live mode is not covered by automated tests | Prompt regressions would go unnoticed | Record live runs as fixtures; evaluate them in CI with a budget |
| Single pipeline shape | Every request goes through the same nine stages (optional skips aside) | Pipeline variants per request type |
| Metrics per run, not a time series | No dashboards or alerting | Export events to a metrics backend |
