## Click-limited links, plus fix for idempotent replay of deleted links

Enhancement: allow a link to stop working after N clicks (one-time or limited-use links). Bug fix: replaying an Idempotency-Key after its link was deleted returns 200 with a dead short URL.

### What changed
- `docs/changes/click-limits.md` (added)
- `service/api/routes.py` (modified)
- `service/api/schemas.py` (modified)
- `service/core/links.py` (modified)
- `service/db/models.py` (modified)
- `service/db/session.py` (modified)
- `service/openapi.json` (modified)
- `tests/integration/test_max_clicks.py` (added)

### Design
Add nullable urls.max_clicks. LinkService enforces it in ensure_active (click_count >= max_clicks -> 410). Redirect cache stores only unlimited links. init_db gains an additive migration that adds missing nullable columns. Idempotent replay of a deleted link raises LinkGoneError -> 410.
- API contract change: True
- Schema change: True

### Validation
- Test suite: passed {'passed': 76}
- Policy review: 1 findings, none blocking
- Needs approval: [change_control.schema] database schema change

### Risks
- Existing SQLite/Postgres databases lack the new column and would crash → Additive, idempotent startup migration for nullable columns; NOT NULL changes refused and left to a reviewed migration
- Redirect cache would bypass the click limit → Never cache click-limited links; test asserts it
- Limit can be exceeded by concurrent requests → Documented as approximate; strict mode out of scope

### Rollback
Revert this PR. No data migration is involved unless listed under schema change.

_Produced by orchestrator run `brownfield-click-limits`; full audit trail in runs/brownfield-click-limits/events.jsonl._
