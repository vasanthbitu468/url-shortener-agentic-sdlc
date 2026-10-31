# Scenarios

Three scenarios cover the assessment's scope: a **greenfield** feature, a **brownfield**
enhancement with a bug fix, and an **ambiguous** request. A fourth, smaller demo exercises the
remaining recovery paths. Each one shows decomposition, orchestration and validation, and
produces a real, tested change to the service.

How they run: each scenario is a `scenario.yaml` (the requirement as a stakeholder would write
it, plus the scripted human steps) and a `mock/` folder of agent responses. The responses are
the outputs an LLM would give, scripted so that runs are deterministic and so that specific
failures can be injected. The code inside them was written and tested for real. Everything the
engine does with those responses (gates, policies, tests, rollbacks, approvals) is live.

```cmd
python scripts/run_scenario.py scenarios/greenfield-bulk-create
python scripts/run_scenario.py --all
```

Recorded results are in [runs/samples](../runs/samples/): each folder has the engineering
summary, PR description, patch, audit log, final state and every artifact version.

| | Greenfield | Brownfield | Ambiguous | Demo |
| --- | --- | --- | --- | --- |
| Run | [bulk create](../runs/samples/greenfield-bulk-create/summary.md) | [click limits](../runs/samples/brownfield-click-limits/summary.md) | [secure + faster](../runs/samples/ambiguous-secure-faster/summary.md) | [version endpoint](../runs/samples/demo-version-endpoint/summary.md) |
| Audit events | 48 | 50 | 84 | 68 |
| Agent attempts | 9 | 10 | 17 | 14 |
| Retries / rollbacks | 1 / 1 | 1 / 1 | 0 / 1 | 1 / 2 |
| Reworks / re-plans | 0 / 0 | 0 / 0 | 0 / 1 | 1 / 0 |
| Autonomy violations blocked | 1 | 0 | 0 | 0 |
| Human approvals | 2 | 2 | 2 (+1 spec edit) | 2 |
| First-pass success rate | 0.875 | 0.889 | 1.0 | 0.917 |
| Files in patch / tests after | 5 / 73 | 8 / 76 | 8 / 77 | 5 / 71 |

---

## 1. Greenfield: bulk link creation

**Request.** "Marketing imports campaign links from spreadsheets and has to create them one at a
time. Build a way to shorten many URLs in a single request, up to 100 at once. Bad rows must not
block the good ones, and the bulk path must not become a way around our abuse protection."

### Decomposition

| Stage | Output |
| --- | --- |
| Requirements | 6 testable criteria: 1-100 items; independent per-item processing; results in request order; created/failed counts; every item counts against the rate limit; 422 for empty, oversized or unknown-field batches. 0 ambiguities. |
| Planning | Tasks G1-G5 (design, implement, tests, docs, review) with dependencies. **Skips impact analysis**: a new, self-contained module that only registers a router. Risks: bulk multiplies abuse capacity; partial failures are easy to miss. |
| Design | `service/api/bulk.py`, reusing `LinkService.create` per item (one implementation of validation and SSRF protection). ADR-002: partial success with HTTP 200 and per-item results (207 Multi-Status rejected as WebDAV-specific). API change: yes. |

### Orchestration (from the audit log)

```
10 stages_skipped   planning        skipped impact_analysis
15 approval_requested design        API contract changes
17 approval_granted   design        Vasanth (tech lead)
21 policy_violation   implementation edit to tests/integration/test_bulk.py is outside this
                                     stage's allowed paths ['service']
22 rollback           service/
24 retry_scheduled    implementation (feedback: the refusal reason)
27 stage_completed    implementation attempt 2: bulk.py + main.py + contract only
28 parallel_batch     tests || docs
40 stage_completed    review         0 findings
46 approval_granted   release
```

### Validation

- The autonomy boundary held: the implementation agent's attempt to write tests was refused
  before anything was written, rolled back, and corrected on retry. Tests came from the tests
  agent, as the pipeline requires.
- 4 new integration tests (all-success, mixed failures including SSRF and duplicate alias, size
  limits, per-item rate limiting); the full suite passed at 73 tests.
- The contract test confirmed `service/openapi.json` was regenerated, and the design had declared
  the API change, so the API-contract policy passed.

---

## 2. Brownfield: click-limited links, plus a real bug fix

**Request.** "(1) Sales wants one-time and limited-use links: a link should stop working after a
set number of clicks. Existing links and existing databases must keep working. (2) Bug report: if
a client retries a create request with the same Idempotency-Key after the link was deleted, it
gets 200 and a short URL that is already dead."

The bug is real. It existed in the Phase 1 code and was reproduced before the scenario was
written: create with a key, delete, replay with the same key, and the response was `200` with a
short URL that answered `410 Gone`.

### Decomposition

| Stage | Output |
| --- | --- |
| Requirements | 6 criteria including "v1 databases migrate automatically" and the bug fix; assumption recorded that the limit is approximate under concurrent clicks. |
| Planning | Tasks B1-B8, with the bug fix (B5) parallel to the schema work (B3-B4). |
| Impact analysis | 6 modules (`models.py`, `session.py`, `links.py`, `schemas.py`, `routes.py`, contract); data flows for create and redirect; risk **medium**. Found that `create_all` does not alter existing tables (a migration is needed) and that the redirect cache would bypass the limit. |
| Design | Nullable `urls.max_clicks`; enforced in `LinkService.ensure_active`; click-limited links are never cached; additive startup migration; replay of a deleted link returns 410. ADR-003: additive migration now, migration framework later. API change: yes. **Schema change: yes.** |

### Orchestration (from the audit log)

```
14 stage_completed    impact_analysis risk medium, 6 modules
18 approval_requested design          API and schema change
20 approval_granted   design          "additive and nullable; migration approach accepted"
25 stage_completed    implementation  6 files
26 parallel_batch     tests || docs
33 rollback           tests/
34 attempt_failed     tests           suite failed: expected 404 for an exhausted link,
                                       service returned 410
35 retry_scheduled    tests           (feedback: the real pytest output)
38 stage_completed    tests           attempt 2: asserts 410, matching the spec; 76 passed
42 stage_completed    review          1 finding: change_control.schema (approval)
46 approval_requested release         PR text lists "Needs approval: database schema change"
```

### Validation

- The first test suite asserted the wrong status code. The exit gate ran the whole suite,
  rejected it, rolled back only `tests/`, and the retry was grounded in the actual failure output.
- Migration tested against a hand-built v1 database: old rows keep redirecting and gain
  `max_clicks = NULL`; the migration is idempotent and refuses NOT NULL columns.
- Regression: the 69 existing tests pass unchanged, plus 7 new ones.
- The policy engine classified the schema change as `approval`, and the release record shows the
  explicit sign-off.

---

## 3. Ambiguous: "make the links more secure and faster"

**Request.** "Customers say our short links feel unsafe and slow. Make the links more secure and
faster."

### Requirement understanding

The requirements agent did not guess. It listed three ambiguities, each with a proposed default,
and the gate requires every ambiguity to have one:

| Question | Proposed default |
| --- | --- |
| Secure against what: abuse by link creators, account takeover, data exposure? | Abuse: block phishing/malware destinations with an operator-managed domain denylist |
| Should blocking disable links that already exist? | No: block at creation only |
| Faster for which operation, against what target? | No change now: hot redirects are already cached; measure p95/p99 first |

Because ambiguities exist, the requirements stage needs human sign-off before any work starts.

### Orchestration (from the audit log)

```
 6 approval_requested requirements   3 ambiguities
 8 approval_granted   requirements   "Defaults accepted: abuse denylist now, performance later"
13-38                 planning ... review   v1 built: create-time denylist, 75 tests pass
42 approval_requested release        v1 ready
44 artifact_edited    spec           Priya (product owner): "Reported phishing links already
                                     exist; blocking must disable existing links too"
46 rollback           docs/ service/ tests/ to the checkpoint before planning
47 replan             planning       changed input: spec; reset planning, impact, design,
                                     implementation, tests, docs, review, release
51-76                 planning ... review   v2 built: + redirect-time enforcement, 77 tests pass
82 approval_granted   release        v2
```

### Validation

- Dynamic re-planning: the engine noticed that `planning` had consumed spec v1 while spec v2 now
  existed. It reset everything downstream, rolled the workspace back so no v1 code leaked into v2,
  and rebuilt. Planning v2 added task A3b; impact v2 raised risk to medium and added the redirect
  path.
- The shipped patch contains the v2 behaviour (`destination has been blocked` on redirect,
  including cached links) and `test_denylist_redirect.py`; nothing from the discarded v1 build.
- The scope decision is recorded in the spec, the ADR (ADR-004), the docs and the audit log, so
  anyone can see why "faster" was deferred and why existing links are blocked.

---

## 4. Demo: version endpoint

A small brownfield change scripted to exercise the remaining paths:

- **Injected fault**: the docs agent fails once, is rolled back and retried with backoff.
- **Policy block and rework**: the first implementation contains a hard-coded key. Review blocks
  it (`security.no_secrets`). The engine rolls back to the implementation checkpoint and redoes
  implementation, tests and docs with the finding as feedback. The second implementation is
  clean, and the released patch contains no key.

---

## Paths not covered by a scenario

These are covered by the integration tests in `tests_orchestrator/test_engine.py`:

| Path | Test |
| --- | --- |
| Fallback agent after exhausted retries | `test_fallback_when_docs_agent_keeps_failing` |
| Rework budget exhausted, run fails, nothing released | `test_rework_limit_fails_the_run_safely` |
| Human rejection with feedback | `test_rejection_sends_stage_back_with_feedback` |
| Safe-stop mid-run and resume | `test_safe_stop_mid_run_and_resume` |
| Entry gate failure | `test_entry_gate_and_agent_errors` |
| Pause, resume from a new process, idempotent completion | `test_human_approval_checkpoints_pause_and_resume` |
| Audit log tampering detected | `test_cli_full_human_workflow` |

## Adding a scenario

1. Create `scenarios/<name>/scenario.yaml` with `name`, `type`, `requirement`, optional
   `faults`, and `demo_steps`.
2. Add `mock/<stage>.json` responses (or `<stage>.<n>.json` for the n-th call), or run it live
   with `sdlc run scenarios/<name> --llm live`.
3. `python scripts/run_scenario.py scenarios/<name> --record` saves it to `runs/samples/`.
