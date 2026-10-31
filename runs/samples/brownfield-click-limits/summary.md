# Engineering summary: Click-limited links, plus fix for idempotent replay of deleted links

- Run: `brownfield-click-limits`  |  Status: **completed**  |  release ready: review changes.patch and pr_description.md
- Scenario: brownfield-click-limits (brownfield)
- Audit log: 50 events, hash chain intact

## Requirement

1) Sales wants one-time and limited-use links: a link should stop working after a set number
   of clicks. Existing links and existing databases must keep working.
2) Bug report: if a client retries a create request with the same Idempotency-Key after the
   link was deleted, it gets 200 and a short URL that is already dead.

## Plan and rationale

- B1: Impact analysis: model, migration path, cache, idempotency (impact_analysis)
- B2: Design schema change, migration and API field (design)
- B3: Add max_clicks column and additive migration (implementation)
- B4: Enforce limit in LinkService; bypass cache for limited links (implementation)
- B5: Fix idempotent replay of deleted links (410) (implementation)
- B6: Regression + migration tests (tests)
- B7: Docs and upgrade notes (docs)
- B8: Policy review and release (review)

Design: Add nullable urls.max_clicks. LinkService enforces it in ensure_active (click_count >= max_clicks -> 410). Redirect cache stores only unlimited links. init_db gains an additive migration that adds missing nullable columns. Idempotent replay of a deleted link raises LinkGoneError -> 410.
ADR: ADR-003: Additive startup migration instead of a migration framework - Add only nullable columns automatically and refuse anything else with an error that demands a reviewed migration.

## Stage outcomes

| Stage | Status | Attempts | Executions | Notes |
| --- | --- | --- | --- | --- |
| requirements | completed | 1 | 1 | Click-limited links, plus fix for idempotent replay of deleted links: 6 acceptan |
| planning | completed | 1 | 1 | 8 tasks, 3 risks |
| impact_analysis | completed | 1 | 1 | 6 modules affected, risk medium |
| design | completed | 1 | 1 | Add nullable urls.max_clicks. LinkService enforces it in ensure_active (click_co |
| implementation | completed | 1 | 1 | changed 6 files: service/api/routes.py, service/api/schemas.py, service/core/lin |
| tests | completed | 2 | 2 | suite passed {'passed': 76} |
| docs | completed | 1 | 1 | wrote docs/changes/click-limits.md |
| review | completed | 1 | 1 | 8 files, 242 changed lines, 1 findings (0 blocking) |
| release | completed | 1 | 1 | patch ready: 8 files, 410 lines |

## Human oversight

- design: **approved** by Vasanth (tech lead) - Schema change is additive and nullable; migration approach accepted
- release: **approved** by Vasanth (tech lead) - Schema change reviewed; upgrade notes present

## Validation

- Tests: passed {'passed': 76}
- Policy [approval] change_control.schema: database schema change service/db/models.py

## Risks and trade-offs

- Existing SQLite/Postgres databases lack the new column and would crash -> Additive, idempotent startup migration for nullable columns; NOT NULL changes refused and left to a reviewed migration
- Redirect cache would bypass the click limit -> Never cache click-limited links; test asserts it
- Limit can be exceeded by concurrent requests -> Documented as approximate; strict mode out of scope

## Assumptions

- The limit is approximate under concurrent clicks: clicks are counted after the redirect, so simultaneous requests can exceed the limit by the number of in-flight requests
- No backfill: existing links get max_clicks = NULL (unlimited)

## Reliability metrics

- status: completed
- attempts: 10
- attempt_success_rate: 0.9
- stages_accepted: 9
- first_pass_success_rate: 0.889
- retries: 1
- rollbacks: 1
- reworks: 0
- fallbacks: 0
- replans: 0
- policy_violations: 0
- approvals: 2
- rejections: 0
- mttr_seconds: 2.609
- end_to_end_latency_seconds: 5.724
- human_wait_seconds: 0.007
- agent_time_seconds: 5.717

## Artifacts

- spec v1 (requirements): `artifacts/spec.v1.json`
- plan v1 (planning): `artifacts/plan.v1.json`
- impact v1 (impact_analysis): `artifacts/impact.v1.json`
- design v1 (design): `artifacts/design.v1.json`
- implementation v1 (implementation): `artifacts/implementation.v1.json`
- docs v1 (docs): `artifacts/docs.v1.json`
- test_report v1 (tests): `artifacts/test_report.v1.json`
- policy_report v1 (review): `artifacts/policy_report.v1.json`
- release v1 (release): `artifacts/release.v1.json`

## Apply the change (human step)

```
git checkout -b feat/<name>
git apply runs/brownfield-click-limits/changes.patch
pytest --cov
```
