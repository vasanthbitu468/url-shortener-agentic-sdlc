# Final engineering summary

**Assignment:** build an agentic software-engineering system that turns requirements into
reviewable engineering outcomes, demonstrated on a URL shortener, with controlled autonomy:
agents execute, humans own oversight, approvals and final quality.

**Result:** a governed orchestrator that drives requirements through nine SDLC stages to a
reviewed patch, plus the URL shortener it operates on, plus three scenarios (greenfield,
brownfield, ambiguous) recorded end to end. 106 automated tests, 99% coverage, CI on every
pull request, verified on Linux and Windows.

| Read next | For |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, orchestration model, control flow, key decisions |
| [SCENARIOS.md](SCENARIOS.md) | The three scenarios: decomposition, orchestration trace, validation |
| [TESTING.md](TESTING.md) | Testing approach, CI, gaps |
| [RISKS_AND_LIMITATIONS.md](RISKS_AND_LIMITATIONS.md) | Risk register, trade-offs, assumptions, limitations |
| [SETUP.md](SETUP.md) | Install and run |
| [DECISIONS/](DECISIONS/) | Architecture decision records |
| [runs/samples/](../runs/samples/) | Recorded runs: summaries, patches, audit logs, artifacts |

## 1. Plan and rationale

The work was delivered as four reviewed pull requests, each with green CI before merge:

| PR | Phase | Content | Why in this order |
| --- | --- | --- | --- |
| #1 | Service | URL shortener: API, security, analytics, reliability, 69 tests, contract, CI, Docker | The orchestrator needs a real, well-tested codebase to change; its test suite becomes the definition of "works" |
| #2 | Orchestrator | Engine, graph, gates, policies, sandbox, agents, audit, metrics, CLI, 30 tests | The core differentiator, built against a stable workload |
| #3 | Scenarios | Greenfield, brownfield, ambiguous (+ demo), recorded runs, scenario tests, CI runs all | Proves the orchestrator on the three required kinds of work |
| #4 | Docs and release | This document set, ADRs, v1.0.0 | Explains and defends the decisions |

Guiding principles:

1. **Governance is code.** Gates and policies are small pure functions with tests, not prompt text.
2. **Agents propose; the engine decides; humans approve.** No agent changes run state or the repository.
3. **Every failure has a bounded, logged response:** retry, fallback, rework, fail, never loop.
4. **One source of truth.** The audit log records everything; metrics and lineage derive from it.
5. **Deterministic by default.** Mock mode makes every path reproducible; live mode is the same code.

## 2. Requirements coverage

### Core requirements (assessment section 4)

| # | Requirement | How it is met | Evidence |
| --- | --- | --- | --- |
| 1 | Requirement understanding | Requirements agent produces a structured spec with testable criteria, assumptions, NFRs, out-of-scope items and ambiguities, each with a proposed default; a gate enforces that; ambiguities trigger human sign-off | Ambiguous scenario: three ambiguities, sign-off, later clarification |
| 2 | Task decomposition | Planning agent emits a task DAG with dependencies, estimates and risks; a gate rejects unknown dependencies and cycles; planning can skip optional stages | Brownfield plan B1-B8; greenfield skips impact analysis; `test_gates` |
| 3 | Codebase reasoning (brownfield) | Impact agent receives the file list and key source files, returns modules, APIs, data flows, affected tests and risk; a gate rejects files that do not exist | Brownfield impact: 6 modules, migration need and cache bypass found, risk medium |
| 4 | Workflow orchestration | Explicit validated DAG; entry/exit gates; parallel tests and docs with a join at review; persisted cross-stage context and decision lineage; human checkpoints; bounded retries, fallback, rework with rollback, safe-stop; policy guardrails; hash-chained audit log; metrics (success rate, retry and rollback frequency, MTTR, latency); re-planning on upstream change | [ARCHITECTURE.md](ARCHITECTURE.md); 13 engine tests, one per path; all four recorded runs |
| 5 | Engineering output | Agents produce code, the regenerated API contract, tests and docs in the sandbox; release produces a git-applicable patch and PR description; the service itself is production-style code with 69 tests | Patches in `runs/samples/*/changes.patch`, applied and tested in CI |
| 6 | Validation and risk control | Compile, contract, full-suite, policy and lint gates; 8 policy rules with block/approval/warn severities; risk register; risks recorded per plan and in every summary | [RISKS_AND_LIMITATIONS.md](RISKS_AND_LIMITATIONS.md); demo: leaked key blocked; brownfield: schema flagged |
| 7 | Controlled autonomy | Agents limited to their stage's paths and to the sandbox; protected paths; retry and rework budgets; humans approve ambiguous specs, API/schema changes and every release; humans can reject, edit artifacts and stop runs | Greenfield: out-of-scope edit refused; every run: approvals by named people in the audit log |
| 8 | Final engineering summary | This document; plus an auto-generated `summary.md` per run with plan, outcomes, approvals, validation, risks, assumptions and metrics | `runs/samples/*/summary.md` |

### Deliverables (assessment section 5)

| Deliverable | Where |
| --- | --- |
| Working prototype, runnable end to end | `service/`, `orchestrator/`, `sdlc` CLI, `scripts/run_scenario.py`; CI runs it on every PR |
| Architecture overview | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Three scenarios with decomposition, orchestration, validation | [SCENARIOS.md](SCENARIOS.md), `scenarios/`, `runs/samples/` |
| Setup instructions | [SETUP.md](SETUP.md), README |
| Testing approach, limitations, trade-offs | [TESTING.md](TESTING.md), [RISKS_AND_LIMITATIONS.md](RISKS_AND_LIMITATIONS.md) |

### Scope (assessment section 3)

| Scope item | Covered by |
| --- | --- |
| Greenfield | Bulk create scenario |
| Brownfield: enhancement, refactor, bug fix | Click-limits scenario: enhancement, schema migration, and a real bug found in the shipped code |
| Test and documentation improvements | Every run adds tests and docs; this PR improves project documentation |
| Well-defined and ambiguous requirements | Greenfield/brownfield (well-defined), secure-and-faster (ambiguous) |

## 3. Artifacts

| Artifact | Location |
| --- | --- |
| Service code, API contract, Dockerfile | `service/`, `service/openapi.json`, `Dockerfile`, `docker-compose.yml` |
| Orchestrator | `orchestrator/` (engine, graph, pipeline, gates, policies, workspace, state, events, telemetry, reporting, CLI, agents) |
| Scenarios | `scenarios/*/scenario.yaml`, `mock/`, `human_edits/` |
| Recorded runs | `runs/samples/*/` (summary, PR text, patch, audit log, state, artifacts) |
| Tests | `tests/` (service), `tests_orchestrator/` (engine, CLI, scenarios) |
| CI | `.github/workflows/ci.yml` |
| Documentation | `README.md`, `docs/` |

## 4. Risks, trade-offs and validation (summary)

- **Main risks:** wrong or harmful agent code (sandbox, gates, human release approval), secret
  leakage (blocking policy), silent API or schema change (contract test, declared-change
  policies, approval), loops (budgets), misread requirements (ambiguity gate, sign-off,
  re-plan). Full register: R1-R10.
- **Key trade-offs:** custom engine over a framework; mock LLM as a primary mode; patch output
  over agent commits; file-based state and log over a database; pattern-based policies over
  model-based review.
- **Validation evidence:** 106 tests; every scenario's patch applied to a clean checkout and
  passing in CI; audit chains verified; the same suite passing on Windows and Linux.

### Engineering judgment in practice

- **Found and fixed a real bug** in the shipped service (idempotent replay of a deleted link
  returned 200 with a dead URL), reproduced before fixing, and used as the brownfield bug fix.
- **Cross-platform defect caught by the tests.** On Windows the contract export wrote CRLF, so an
  unchanged contract looked changed, and the policy engine blocked it. The guardrail was right to
  block what it was shown. The fix went to the root (LF output) and added a second layer (a
  line-ending-insensitive diff), plus regression tests that reproduce the condition on any OS.
- **Deferred "faster"** in the ambiguous scenario: there was no baseline measurement, and hot
  redirects are already cached. The decision is recorded rather than optimising blind.
- **Documented approximate semantics** (click limit under concurrency) instead of adding a
  transactional counter to the hot path.

## 5. Assumptions

One operator per run; agents answer in the requested JSON; the service test suite defines
correctness; approvers read the artifacts; scenario mock responses stand in for an LLM, with
code that was written and tested for real. Details in
[RISKS_AND_LIMITATIONS.md](RISKS_AND_LIMITATIONS.md#assumptions).

## 6. Limitations and next steps

| Limitation | Next step |
| --- | --- |
| Live LLM mode not regression-tested | Record live runs as fixtures; evaluate in CI within a budget |
| Agent timeouts cannot kill threads | Run agents in subprocesses |
| Single-process state, no locking | File lock or small database for concurrent operators |
| Rework always targets implementation | Let gates identify the faulty upstream stage |
| Regex policies | Add gitleaks and bandit; keep human review |
| Service: in-process rate limiter and cache, no auth, DNS not resolved for SSRF | Redis, API keys and ownership, resolve-and-check or egress proxy |
| Metrics per run only | Export events to a metrics backend for trends and alerts |
