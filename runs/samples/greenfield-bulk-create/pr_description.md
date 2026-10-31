## Bulk link creation API

New capability: shorten up to 100 URLs in one request for marketing campaign imports. Items are processed independently with per-item results.

### What changed
- `docs/changes/bulk-create.md` (added)
- `service/api/bulk.py` (added)
- `service/main.py` (modified)
- `service/openapi.json` (modified)
- `tests/integration/test_bulk.py` (added)

### Design
New module service/api/bulk.py with POST /api/v1/urls/bulk. Reuses LinkService.create per item (same validation, SSRF guard and alias rules) and the existing rate limiter per item. Response 200 with per-item results.
- API contract change: True
- Schema change: False

### Validation
- Test suite: passed {'passed': 73}
- Policy review: 0 findings, none blocking

### Risks
- Bulk endpoint multiplies abuse capacity (100 links per request) → Every item consumes one rate-limit token; overflow items fail explicitly
- Partial failures are easy for clients to miss → Return created/failed counts and per-item errors in request order

### Rollback
Revert this PR. No data migration is involved unless listed under schema change.

_Produced by orchestrator run `greenfield-bulk-create`; full audit trail in runs/greenfield-bulk-create/events.jsonl._
