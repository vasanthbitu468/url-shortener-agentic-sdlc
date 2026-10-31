# Sample runs

Recorded with the mock LLM and the scripted human steps in each `scenario.yaml`
(`python scripts/run_scenario.py --all --record`). They let a reviewer inspect complete runs
without installing anything.

| Run | Type | What to look at |
| --- | --- | --- |
| [greenfield-bulk-create](greenfield-bulk-create/summary.md) | Greenfield | Planning skips impact analysis; the implementation agent tries to write a test file, is refused by its autonomy boundary, rolled back and retried; design and release approvals |
| [brownfield-click-limits](brownfield-click-limits/summary.md) | Brownfield | Impact analysis of a schema change; additive migration; a real bug fix; first tests fail and are retried with the pytest output as feedback; schema change flagged for approval |
| [ambiguous-secure-faster](ambiguous-secure-faster/summary.md) | Ambiguous | Three ambiguities with defaults, signed off; product owner changes the spec at release; engine re-plans, rolls back the built code and rebuilds v2 |
| [demo-version-endpoint](demo-version-endpoint/summary.md) | Brownfield (demo) | Injected docs failure and retry; leaked key blocked by policy review; rework loop with rollback |

Each folder contains:

| File | Contents |
| --- | --- |
| `summary.md` | Engineering summary: plan, stage outcomes, approvals, validation, risks, assumptions, metrics |
| `pr_description.md` | Pull-request text produced at release |
| `changes.patch` | The change, applicable with `git apply` (CI checks this) |
| `events.jsonl` | Hash-chained audit log of every transition, retry, rollback and approval |
| `state.json` | Final state: stage records, artifact index, decisions with lineage, approvals |
| `artifacts/` | Every artifact version (spec, plan, impact, design, reports) |

List the events of a run:

```bash
python -c "import json; [print(e['seq'], e['type'], e['stage'] or '') for e in map(json.loads, open('runs/samples/ambiguous-secure-faster/events.jsonl'))]"
```
