# Testing approach

106 automated tests, 99% line coverage, run on every push and pull request. The suite tests the
service, the orchestrator's building blocks, every orchestration control path, and the three
scenarios end to end.

| Command | Runs |
| --- | --- |
| `pytest --cov` | Everything with coverage (about 1.5 min on Linux, 3 min on Windows) |
| `pytest tests` | Service only (about 1 s) |
| `pytest tests_orchestrator -k engine` | One area |
| `python scripts/run_scenario.py --all` | Scenarios with their human steps |

## Layers

| Layer | Location | Tests | What it proves |
| --- | --- | --- | --- |
| Service unit | `tests/unit/` | 41 | Code generation, URL and alias validation (SSRF cases, reserved words), rate limiter windows and eviction, cache TTL and LRU |
| Service integration | `tests/integration/test_api.py` | 27 | Every endpoint and status code through the HTTP layer: idempotency, expiry, soft delete, cache invalidation, click analytics, privacy of stored data, readiness failure, request IDs, rate limiting, code collisions |
| API contract | `tests/integration/test_contract.py` | 1 | The committed `service/openapi.json` equals the app's schema, so API changes are always visible in review |
| Orchestrator units | `tests_orchestrator/test_units.py` | 17 | Graph validation (cycles, unknown dependencies, bad rework targets); audit chain and tamper detection; workspace edits, scope enforcement, path escapes, atomicity, checkpoints, git-applicable diff, line-ending handling; every policy rule; every gate; mock LLM sequencing; JSON extraction; scenario loading |
| Orchestrator integration | `tests_orchestrator/test_engine.py` | 13 | One full run per control path: retry, rework, parallel batch, approvals across processes, rejection, safe-stop, fallback, rework limit, re-plan, ambiguous sign-off, optional-stage skipping, autonomy violation, failing tests, entry gate, cross-run metrics |
| CLI | `tests_orchestrator/test_cli.py` | 2 | A human's full workflow through `sdlc`: run, reject, resume, edit, approve, stop, trace, verify, metrics, list; tampered log fails `verify` |
| Scenarios | `tests_orchestrator/test_scenarios.py` | 5 | Each scenario reaches release through its scripted human steps, and the control path it exists to show actually happened |

Counts include parametrised cases.

## Techniques

- **Real execution, not mocks of our own code.** Orchestrator tests run complete pipelines: agents
  edit a real sandbox, the tests stage runs the real service suite in a subprocess, review runs
  ruff and the policy rules. Only the LLM is replaced.
- **Scripted failures.** The mock LLM picks `<stage>.<n>.json` for the n-th call, so a test can
  script a bad answer followed by a good one. `faults:` injects transient errors. Together these
  reach every recovery path deterministically.
- **Fakes for time.** The rate limiter and cache take an injectable clock; the engine takes an
  injectable `sleep`, so backoff does not slow the suite.
- **Evidence-based assertions.** Engine tests assert on the audit log (`rework`, `rollback`,
  `replan`, `policy_violation` events with their data), on artifacts, and on the final patch, not
  only on the run status.
- **Cross-platform regressions.** Line-ending tests reproduce the Windows condition on any OS
  (see "A bug the tests caught" below).

## Continuous integration

`.github/workflows/ci.yml`, three jobs:

| Job | Steps |
| --- | --- |
| `test` | ruff lint and format check; full suite with an 85% coverage gate; coverage report uploaded |
| `orchestrator-demo` | Run all scenarios with their human steps; apply each scenario's patch to a clean checkout and run the service suite against it; CLI smoke test; upload audit logs, patches and summaries as a build artifact |
| `docker` | Build the image; start it; create a link and follow the redirect |

`main` is protected: changes land only through pull requests with green checks.

## Validation built into the product

Testing does not stop at the suite. Every orchestrator run validates its own output:

| Check | Where |
| --- | --- |
| Generated code compiles | implementation exit gate |
| API contract regenerated and consistent with the design | implementation gate + `change_control.api_contract` policy |
| New tests exist and the **whole** suite passes | tests exit gate |
| No secrets, no PII storage, no protected paths, bounded diff, schema changes declared, tests accompany code, lint clean | review gate (policies) |
| Patch is non-empty and applies | release gate; CI applies it |

## A bug the tests caught

The ambiguous scenario passed on Linux but failed on Windows. The cause was that the contract
export wrote CRLF line endings on Windows. The workspace diff compared bytes, so an unchanged
contract looked changed. The API-contract policy then correctly blocked a "change" the design had
not declared. The guardrail behaved as designed on a false signal.

Fix, in two layers: the export always writes LF, and the change detector ignores
line-ending-only differences. All orchestrator outputs are now written with LF. Two regression
tests reproduce the condition on any OS. This is why the suite runs on both platforms before a
release.

## Not covered (and why)

| Gap | Reason | Mitigation |
| --- | --- | --- |
| Live LLM mode (`ClaudeLLM`) | Needs network and an API key; responses are non-deterministic | Excluded from coverage; it shares the agent code path with mock mode; JSON parsing is unit-tested |
| PostgreSQL | CI uses SQLite | SQLAlchemy only, no SQLite-specific SQL in the service; the migration uses inspector APIs |
| Load and concurrency limits | Out of scope for a prototype | Click counting is atomic in SQL; the click limit is documented as approximate |
| Agent timeouts | Hard to trigger deterministically without slowing the suite | Implemented with `asyncio.wait_for`; the thread limitation is documented |
