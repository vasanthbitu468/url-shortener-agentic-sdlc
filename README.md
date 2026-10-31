# URL Shortener — Agentic SDLC

A URL shortener service, plus an agentic orchestration layer (`orchestrator/`) that builds and
evolves the service through a governed SDLC pipeline: dependency graph, entry/exit gates,
parallel stages, human approvals, bounded retries, fallback, rollback, safe-stop, re-planning,
policy guardrails and a hash-chained audit log.

**Status:** service, orchestrator and the three assessment scenarios complete. Next: the
architecture overview and engineering-summary docs, then the v1.0.0 release.

## Scenarios

Each scenario is a requirement plus scripted agent responses (mock LLM) and scripted human
steps, so it runs identically everywhere. Recorded results are in [runs/samples](runs/samples/).

| Scenario | Requirement | What it demonstrates |
| --- | --- | --- |
| [greenfield-bulk-create](scenarios/greenfield-bulk-create/scenario.yaml) | Shorten up to 100 URLs per request | Planning skips impact analysis; autonomy boundary refuses an out-of-scope edit (rollback, retry); API approval |
| [brownfield-click-limits](scenarios/brownfield-click-limits/scenario.yaml) | Limited-use links + fix a real idempotency bug | Impact analysis; schema change with additive migration; failing tests retried with pytest output as feedback; schema flagged for approval |
| [ambiguous-secure-faster](scenarios/ambiguous-secure-faster/scenario.yaml) | "Make the links more secure and faster" | Ambiguities with defaults and sign-off; late spec change by the product owner triggers re-plan, rollback and rebuild |
| [demo-version-endpoint](scenarios/demo-version-endpoint/scenario.yaml) | Version endpoint | Injected failure + retry; leaked key blocked by policy; rework loop |

```cmd
python scripts/run_scenario.py scenarios/ambiguous-secure-faster
python scripts/run_scenario.py --all
```

Or drive a scenario by hand with the CLI below and make the approvals yourself.

## Quick start (Windows, Command Prompt)

```cmd
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest --cov
uvicorn service.main:app --reload
```

macOS / Linux: same, but `python3 -m venv .venv` and `source .venv/bin/activate`.

Open http://localhost:8000/docs for interactive API docs.

With Docker: `docker compose up --build`, then the same URL.

## Agentic orchestrator

```
requirements -> planning -> impact_analysis* -> design -> implementation -+-> tests -+-> review -> release
                                                                          +-> docs  -+
```

Agents work in a sandbox copy of the repo under `runs/<run-id>/`; the deliverable is a patch a
human reviews and applies. Approval checkpoints: requirements (when ambiguous), design (when the
API or schema changes) and release (always).

| Command | What it does |
| --- | --- |
| `sdlc graph` | show the pipeline |
| `sdlc run scenarios/demo-version-endpoint` | runs until the design approval |
| `sdlc approve <run-id> design -m "looks good"` | continue; pauses at release |
| `sdlc approve <run-id> release -m "ship it"` | completes: changes.patch, summary.md |
| `sdlc status <run-id>` | stage table |
| `sdlc trace <run-id>` | decision lineage |
| `sdlc verify <run-id>` | check the audit log hash chain |
| `sdlc metrics` | reliability metrics across runs |
| `sdlc reject <run-id> design -m "what to change"` | send a stage back with feedback |
| `sdlc edit <run-id> spec my_spec.json` | change an artifact -> downstream re-plans |
| `sdlc stop <run-id>` | safe-stop (state saved) |
| `sdlc resume <run-id>` | continue a stopped or paused run |

The demo scenario is scripted (mock LLM) to show every control path: the docs agent fails once
(retry with backoff), tests and docs run in parallel, the first implementation leaks a
hard-coded key so policy review blocks it (rollback and rework with feedback), and the run
pauses twice for human approval. Use `--llm live` with `ANTHROPIC_API_KEY` set (and
`pip install -e ".[live]"`) to drive the same pipeline with Claude.

| Control | Where |
| --- | --- |
| Dependency graph, cycle checks, parallel levels | `orchestrator/graph.py`, `pipeline.py` |
| Scheduling, retries, fallback, rework, rollback, safe-stop, re-plan | `orchestrator/engine.py` |
| Entry/exit gates and approval rules | `orchestrator/gates.py` |
| Security, compliance, change-control policies | `orchestrator/policies.py` |
| Sandbox, scoped edits, checkpoints, patch | `orchestrator/workspace.py` |
| Hash-chained audit log | `orchestrator/events.py` |
| Metrics: success rate, retry/rollback frequency, MTTR, latency | `orchestrator/telemetry.py` |

## API

| Method | Path | Purpose | Main responses |
| --- | --- | --- | --- |
| POST | `/api/v1/urls` | Create a short link (`url`, optional `custom_alias`, `expires_at`) | 201, 200 (idempotent replay), 409, 422, 429 |
| GET | `/{code}` | Redirect to the target | 302, 404, 410 |
| GET | `/api/v1/urls/{code}` | Link metadata | 200, 404, 410 |
| GET | `/api/v1/urls/{code}/stats` | Total clicks, last access, clicks per day | 200, 404 |
| DELETE | `/api/v1/urls/{code}` | Soft-delete a link | 204, 404, 410 |
| GET | `/health`, `/ready` | Liveness; readiness (checks DB) | 200, 503 |

The full contract is committed at `service/openapi.json`.

Example:

```bash
curl -X POST http://localhost:8000/api/v1/urls -H "Content-Type: application/json" ^
  -d "{\"url\": \"https://example.com/a/long/path\", \"custom_alias\": \"demo\"}"
curl -i http://localhost:8000/demo
curl http://localhost:8000/api/v1/urls/demo/stats
```

## Design decisions

| Decision | Why |
| --- | --- |
| Random base62 codes (7 chars, ~3.5 trillion) with bounded collision retry | Hashing the URL would give every user the same code and leak who shortened what |
| 302 redirect + `Cache-Control: no-store` | Browsers don't cache, so every click is counted |
| Clicks recorded in a background task, counter incremented in SQL | Redirect stays fast; no lost counts under concurrency |
| Soft delete; deleted and expired links return 410 | Keeps analytics and audit trail; clients can tell "gone" from "never existed" |
| SSRF guard: http/https only, no credentials, no loopback/private/link-local IPs, no self-links | Stops the service being used to reach internal hosts or cloud metadata |
| Privacy: no IP stored; user agent kept only as an HMAC hash | Minimises personal data |
| `Idempotency-Key` header on create | Safe client retries; a reused key with a different body returns 409 |
| Fixed-window rate limit on create, per client IP | Abuse protection; returns 429 with `Retry-After` |
| TTL + LRU cache on the redirect path | Hot links skip the DB; expiry re-checked on cache hits; deletes invalidate |
| Contract test on `openapi.json` | Any API change is explicit in the diff and fails CI until regenerated |

## Project layout

```
service/
  api/        routes.py (HTTP layer), schemas.py (request/response models)
  core/       links.py (business logic), validation.py, codegen.py, ratelimit.py, cache.py
  db/         models.py, session.py
  config.py   settings from APP_* environment variables
  main.py     app factory, JSON request logging with request IDs
  openapi.json
tests/
  unit/         validators, codegen, rate limiter, cache
  integration/  every endpoint, idempotency, expiry, caching, rate limit, contract
orchestrator/   engine, graph, gates, policies, workspace, agents/, cli
tests_orchestrator/  engine control paths, policies, gates, CLI, audit tampering
scenarios/      scenario.yaml + scripted mock LLM responses (+ human_edits/)
runs/samples/   recorded runs: summary, PR text, patch, audit log, artifacts
scripts/        export_openapi.py, run_scenario.py
```

## Configuration

All settings are environment variables prefixed `APP_` (or a `.env` file). See `.env.example`.

## Testing

`pytest --cov` runs the service tests (in-memory SQLite) and the orchestrator tests (full runs
through every control path: retry, fallback, rework, rollback, approvals, rejection, safe-stop,
re-plan, autonomy violations, audit tampering). Takes about a minute.
CI enforces lint (`ruff`), an 85% coverage gate, a Docker build + smoke test, and runs all
scenarios end to end; each scenario's patch must apply to a clean checkout and pass the suite.

## Known limitations (Phase 1)

- Rate limiter and cache are in-process; multiple instances need Redis behind the same interfaces.
- SSRF check does not resolve DNS; a public hostname resolving to a private IP is not caught.
- Client IP for rate limiting comes from the socket; behind a proxy, trusted `X-Forwarded-For` handling is needed.
- Tables are created at startup; schema changes from v2 onward go through migrations.
- No authentication: anyone can delete any link. Ownership/API keys are a planned enhancement.

Orchestrator limitations: an agent that times out keeps running in its thread until it ends
(its result is discarded); the run state is a JSON file, so two processes must not drive the
same run at once; mock mode replays scripted responses and does not judge prompt quality.

## Roadmap

1. ~~Core service~~
2. ~~Agentic orchestration engine with governance, audit and metrics~~
3. ~~Scenarios: greenfield, brownfield, ambiguous~~
4. Docs (architecture, scenarios, testing, engineering summary) and release
