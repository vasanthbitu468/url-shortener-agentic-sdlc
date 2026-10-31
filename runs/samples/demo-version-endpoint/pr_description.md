## Expose service version endpoint

Add a read-only endpoint that returns the running service version so operators and clients can confirm which build is deployed.

### What changed
- `docs/changes/version-endpoint.md` (added)
- `service/api/version.py` (added)
- `service/main.py` (modified)
- `service/openapi.json` (modified)
- `tests/integration/test_version.py` (added)

### Design
New APIRouter in service/api/version.py exposing GET /api/v1/version, returning VersionResponse{version}; registered in create_app before the redirect router.
- API contract change: True
- Schema change: False

### Validation
- Test suite: passed {'passed': 71}
- Policy review: 0 findings, none blocking

### Risks
- New path could be captured by the catch-all /{code} redirect route → Register the router before the redirect router; test it explicitly
- API contract drift → Regenerate service/openapi.json; contract test enforces it

### Rollback
Revert this PR. No data migration is involved unless listed under schema change.

_Produced by orchestrator run `demo-version-endpoint`; full audit trail in runs/demo-version-endpoint/events.jsonl._
