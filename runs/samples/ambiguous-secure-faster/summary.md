# Engineering summary: Block malicious destinations at creation and on every redirect

- Run: `ambiguous-secure-faster`  |  Status: **completed**  |  release ready: review changes.patch and pr_description.md
- Scenario: ambiguous-secure-faster (ambiguous)
- Audit log: 84 events, hash chain intact

## Requirement

Customers say our short links feel unsafe and slow. Make the links more secure and faster.

## Plan and rationale

- A1: Impact analysis on validation and config (impact_analysis)
- A2: Design denylist config and matching rules (design)
- A3: Enforce denylist on create (implementation)
- A3b: Enforce denylist on every redirect (incl. cache) (implementation)
- A4: Tests: matching rules, create and redirect (tests)
- A5: Operator docs (docs)
- A6: Policy review and release (review)

Design: Settings.blocked_domains (comma-separated) parsed into a frozenset; validate_target_url rejects blocked hosts and subdomains at creation; the redirect route re-checks the destination on every request, after the cache lookup, returning 410.
ADR: ADR-004: Config-based denylist, enforced at create and redirect - Operator-managed domain denylist with subdomain matching; checked on every redirect so existing links are disabled immediately

## Stage outcomes

| Stage | Status | Attempts | Executions | Notes |
| --- | --- | --- | --- | --- |
| requirements | completed | 1 | 1 | Block malicious destinations at link creation: 4 acceptance criteria, 3 ambiguit |
| planning | completed | 1 | 2 | 7 tasks, 3 risks |
| impact_analysis | completed | 1 | 2 | 4 modules affected, risk medium |
| design | completed | 1 | 2 | Settings.blocked_domains (comma-separated) parsed into a frozenset; validate_tar |
| implementation | completed | 1 | 2 | changed 5 files: service/api/routes.py, service/config.py, service/core/links.py |
| tests | completed | 1 | 2 | suite passed {'passed': 77} |
| docs | completed | 1 | 2 | wrote docs/changes/denylist.md |
| review | completed | 1 | 2 | 8 files, 145 changed lines, 0 findings (0 blocking) |
| release | completed | 1 | 2 | patch ready: 8 files, 240 lines |

## Human oversight

- requirements: **approved** by Vasanth (tech lead) - Defaults accepted: abuse denylist now, performance after measurement
- release: **approved** by Vasanth (tech lead) - v2 reviewed: create and redirect enforcement, reversible via config
- spec edited by Priya (product owner) - Reported phishing links already exist; blocking must disable existing links too
- Re-plan from planning: inputs ['spec'] changed - upstream artifact changed after this stage ran

## Validation

- Tests: passed {'passed': 77}

## Risks and trade-offs

- Suffix matching could block lookalikes or miss subdomains -> Match exact domain or '.'+domain only; tests for both directions
- Interpretation of a vague request may be wrong -> Ambiguities listed with defaults and signed off before work starts
- Blocking existing links breaks legitimate links on a bad entry -> Removing the domain from config restores them; nothing is deleted

## Assumptions

- Denylist is small (hundreds of domains) and changes via deployment config
- Blocked links return 410, consistent with expired links
- Ambiguity resolved: 'More secure' against what threat: abuse by link creators, account takeover, or data exposure? -> Abuse: stop the shortener from fronting phishing/malware destinations, using an operator-managed domain denylist
- Ambiguity resolved: Should blocking also disable links that already exist? -> Yes (decided by product owner): enforce on every redirect, cached links included
- Ambiguity resolved: 'Faster' for which operation, and what is the target? -> No change now: redirects for hot links are already served from the in-process cache; measure p95/p99 before optimising

## Reliability metrics

- status: completed
- attempts: 17
- attempt_success_rate: 1.0
- stages_accepted: 17
- first_pass_success_rate: 1.0
- retries: 0
- rollbacks: 1
- reworks: 0
- fallbacks: 0
- replans: 1
- policy_violations: 0
- approvals: 2
- rejections: 0
- mttr_seconds: n/a
- end_to_end_latency_seconds: 5.52
- human_wait_seconds: 0.008
- agent_time_seconds: 5.512

## Artifacts

- spec v2 (human:Priya (product owner)): `artifacts/spec.v2.json`
- plan v2 (planning): `artifacts/plan.v2.json`
- impact v2 (impact_analysis): `artifacts/impact.v2.json`
- design v2 (design): `artifacts/design.v2.json`
- implementation v2 (implementation): `artifacts/implementation.v2.json`
- docs v1 (docs): `artifacts/docs.v1.json`
- test_report v2 (tests): `artifacts/test_report.v2.json`
- policy_report v2 (review): `artifacts/policy_report.v2.json`
- release v2 (release): `artifacts/release.v2.json`

## Apply the change (human step)

```
git checkout -b feat/<name>
git apply runs/ambiguous-secure-faster/changes.patch
pytest --cov
```
