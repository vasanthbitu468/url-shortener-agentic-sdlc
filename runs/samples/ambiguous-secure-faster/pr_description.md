## Block malicious destinations at creation and on every redirect

Clarified by the product owner after review: blocking must also disable links that already exist, because the phishing links reported by customers were created before the domains were known to be bad. Performance work stays deferred.

### What changed
- `docs/changes/denylist.md` (added)
- `service/api/routes.py` (modified)
- `service/config.py` (modified)
- `service/core/links.py` (modified)
- `service/core/validation.py` (modified)
- `tests/integration/test_denylist_create.py` (added)
- `tests/integration/test_denylist_redirect.py` (added)
- `tests/unit/test_denylist.py` (added)

### Design
Settings.blocked_domains (comma-separated) parsed into a frozenset; validate_target_url rejects blocked hosts and subdomains at creation; the redirect route re-checks the destination on every request, after the cache lookup, returning 410.
- API contract change: False
- Schema change: False

### Validation
- Test suite: passed {'passed': 77}
- Policy review: 0 findings, none blocking

### Risks
- Suffix matching could block lookalikes or miss subdomains → Match exact domain or '.'+domain only; tests for both directions
- Interpretation of a vague request may be wrong → Ambiguities listed with defaults and signed off before work starts
- Blocking existing links breaks legitimate links on a bad entry → Removing the domain from config restores them; nothing is deleted

### Rollback
Revert this PR. No data migration is involved unless listed under schema change.

_Produced by orchestrator run `ambiguous-secure-faster`; full audit trail in runs/ambiguous-secure-faster/events.jsonl._
