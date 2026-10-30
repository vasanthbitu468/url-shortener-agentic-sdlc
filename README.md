# URL Shortener — Agentic SDLC

A URL shortener service, plus (in later phases) an agentic orchestration layer that builds and
evolves the service through a governed SDLC pipeline with gates, human approvals, retries,
rollback and audit.

**Status:** Phase 1 — core service complete (create, redirect, analytics, reliability features).

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
scripts/export_openapi.py
```

## Configuration

All settings are environment variables prefixed `APP_` (or a `.env` file). See `.env.example`.

## Testing

`pytest --cov` runs unit and integration tests against an in-memory SQLite DB.
CI enforces lint (`ruff`), an 85% coverage gate, and a Docker build + smoke test.

## Known limitations (Phase 1)

- Rate limiter and cache are in-process; multiple instances need Redis behind the same interfaces.
- SSRF check does not resolve DNS; a public hostname resolving to a private IP is not caught.
- Client IP for rate limiting comes from the socket; behind a proxy, trusted `X-Forwarded-For` handling is needed.
- Tables are created at startup; schema changes from v2 onward go through migrations.
- No authentication: anyone can delete any link. Ownership/API keys are a planned enhancement.

## Roadmap

1. ~~Core service~~
2. Agentic orchestration engine (DAG, gates, approvals, retries, rollback, re-plan)
3. Governance: policies, audit log, reliability metrics
4. Scenarios: greenfield, brownfield, ambiguous
5. Docs and release
