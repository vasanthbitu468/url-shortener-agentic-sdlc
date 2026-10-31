# Engineering summary: Expose service version endpoint

- Run: `demo-version-endpoint`  |  Status: **completed**  |  release ready: review changes.patch and pr_description.md
- Scenario: demo-version-endpoint (brownfield)
- Audit log: 68 events, hash chain intact

## Requirement

Ops keep asking which build is deployed. Add an endpoint that tells us the service version.

## Plan and rationale

- T1: Analyse impact on routing (impact_analysis)
- T2: Design endpoint and response model (design)
- T3: Implement router and register it (implementation)
- T4: Integration test for /api/v1/version (tests)
- T5: Document the endpoint (docs)
- T6: Policy review and release (review)

Design: New APIRouter in service/api/version.py exposing GET /api/v1/version, returning VersionResponse{version}; registered in create_app before the redirect router.
ADR: ADR-001: Version endpoint reads app.version - Read the version from the FastAPI app object instead of a constant.

## Stage outcomes

| Stage | Status | Attempts | Executions | Notes |
| --- | --- | --- | --- | --- |
| requirements | completed | 1 | 1 | Expose service version endpoint: 4 acceptance criteria, 0 ambiguities |
| planning | completed | 1 | 1 | 6 tasks, 2 risks |
| impact_analysis | completed | 1 | 1 | 3 modules affected, risk low |
| design | completed | 1 | 1 | New APIRouter in service/api/version.py exposing GET /api/v1/version, returning  |
| implementation | completed | 1 | 2 | changed 3 files: service/api/version.py, service/main.py, service/openapi.json |
| tests | completed | 1 | 2 | suite passed {'passed': 71} |
| docs | completed | 1 | 3 | wrote docs/changes/version-endpoint.md |
| review | completed | 1 | 2 | 5 files, 74 changed lines, 0 findings (0 blocking) |
| release | completed | 1 | 1 | patch ready: 5 files, 123 lines |

## Human oversight

- design: **approved** by Vasanth (tech lead) - API addition is fine
- release: **approved** by Vasanth (tech lead) - Ship it

## Validation

- Tests: passed {'passed': 71}

## Risks and trade-offs

- New path could be captured by the catch-all /{code} redirect route -> Register the router before the redirect router; test it explicitly
- API contract drift -> Regenerate service/openapi.json; contract test enforces it

## Assumptions

- No authentication is required; the version is not sensitive

## Reliability metrics

- status: completed
- attempts: 14
- attempt_success_rate: 0.857
- stages_accepted: 12
- first_pass_success_rate: 0.917
- retries: 1
- rollbacks: 2
- reworks: 1
- fallbacks: 0
- replans: 0
- policy_violations: 0
- approvals: 2
- rejections: 0
- mttr_seconds: 1.63
- end_to_end_latency_seconds: 5.435
- human_wait_seconds: 0.007
- agent_time_seconds: 5.428

## Artifacts

- spec v1 (requirements): `artifacts/spec.v1.json`
- plan v1 (planning): `artifacts/plan.v1.json`
- impact v1 (impact_analysis): `artifacts/impact.v1.json`
- design v1 (design): `artifacts/design.v1.json`
- implementation v2 (implementation): `artifacts/implementation.v2.json`
- docs v1 (docs): `artifacts/docs.v1.json`
- test_report v2 (tests): `artifacts/test_report.v2.json`
- policy_report v1 (review): `artifacts/policy_report.v1.json`
- release v1 (release): `artifacts/release.v1.json`

## Apply the change (human step)

```
git checkout -b feat/<name>
git apply runs/demo-version-endpoint/changes.patch
pytest --cov
```
