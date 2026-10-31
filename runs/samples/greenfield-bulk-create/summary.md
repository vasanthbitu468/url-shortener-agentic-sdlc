# Engineering summary: Bulk link creation API

- Run: `greenfield-bulk-create`  |  Status: **completed**  |  release ready: review changes.patch and pr_description.md
- Scenario: greenfield-bulk-create (greenfield)
- Audit log: 48 events, hash chain intact

## Requirement

Marketing imports campaign links from spreadsheets and has to create them one at a time.
Build a way to shorten many URLs in a single request, up to 100 at once. Bad rows must not
block the good ones, and the bulk path must not become a way around our abuse protection.

## Plan and rationale

- G1: Design bulk request/response contract (design)
- G2: Implement bulk router reusing LinkService (implementation)
- G3: Tests: success, partial failure, limits, rate limiting (tests)
- G4: API documentation with example (docs)
- G5: Policy review and release (review)

Design: New module service/api/bulk.py with POST /api/v1/urls/bulk. Reuses LinkService.create per item (same validation, SSRF guard and alias rules) and the existing rate limiter per item. Response 200 with per-item results.
ADR: ADR-002: Partial success with 200 and per-item results - Process items independently and return 200 with per-item status; reject only structurally invalid batches with 422. 207 Multi-Status was rejected as WebDAV-specific.

## Stage outcomes

| Stage | Status | Attempts | Executions | Notes |
| --- | --- | --- | --- | --- |
| requirements | completed | 1 | 1 | Bulk link creation API: 6 acceptance criteria, 0 ambiguities |
| planning | completed | 1 | 1 | 5 tasks, 2 risks |
| impact_analysis | skipped | 0 | 0 | skipped by planning |
| design | completed | 1 | 1 | New module service/api/bulk.py with POST /api/v1/urls/bulk. Reuses LinkService.c |
| implementation | completed | 2 | 2 | changed 3 files: service/api/bulk.py, service/main.py, service/openapi.json |
| tests | completed | 1 | 1 | suite passed {'passed': 73} |
| docs | completed | 1 | 1 | wrote docs/changes/bulk-create.md |
| review | completed | 1 | 1 | 5 files, 278 changed lines, 0 findings (0 blocking) |
| release | completed | 1 | 1 | patch ready: 5 files, 327 lines |

## Human oversight

- design: **approved** by Vasanth (tech lead) - Partial-success contract approved; 200 with per-item results is fine
- release: **approved** by Vasanth (tech lead) - Reviewed patch, tests and docs

## Validation

- Tests: passed {'passed': 73}

## Risks and trade-offs

- Bulk endpoint multiplies abuse capacity (100 links per request) -> Every item consumes one rate-limit token; overflow items fail explicitly
- Partial failures are easy for clients to miss -> Return created/failed counts and per-item errors in request order

## Assumptions

- Per-item Idempotency-Key is out of scope for v1 of the bulk API
- Same validation and SSRF rules as the single-create endpoint

## Reliability metrics

- status: completed
- attempts: 9
- attempt_success_rate: 0.889
- stages_accepted: 8
- first_pass_success_rate: 0.875
- retries: 1
- rollbacks: 1
- reworks: 0
- fallbacks: 0
- replans: 0
- policy_violations: 1
- approvals: 2
- rejections: 0
- mttr_seconds: 1.243
- end_to_end_latency_seconds: 3.601
- human_wait_seconds: 0.006
- agent_time_seconds: 3.595

## Artifacts

- spec v1 (requirements): `artifacts/spec.v1.json`
- plan v1 (planning): `artifacts/plan.v1.json`
- design v1 (design): `artifacts/design.v1.json`
- implementation v1 (implementation): `artifacts/implementation.v1.json`
- docs v1 (docs): `artifacts/docs.v1.json`
- test_report v1 (tests): `artifacts/test_report.v1.json`
- policy_report v1 (review): `artifacts/policy_report.v1.json`
- release v1 (release): `artifacts/release.v1.json`

## Apply the change (human step)

```
git checkout -b feat/<name>
git apply runs/greenfield-bulk-create/changes.patch
pytest --cov
```
