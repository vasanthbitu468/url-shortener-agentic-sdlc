"""Human-readable run reports: status table, decision lineage, and the engineering summary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from orchestrator.events import EventLog, verify_chain
from orchestrator.telemetry import run_metrics

if TYPE_CHECKING:
    from orchestrator.graph import Graph
    from orchestrator.state import RunState, RunStore


def status_lines(state: RunState, graph: Graph) -> list[str]:
    lines = [f"Run {state.run_id}  [{state.status.value.upper()}]  {state.message}", ""]
    lines.append(f"{'stage':<16}{'status':<19}{'tries':>5}{'runs':>6}  summary")
    lines.append("-" * 96)
    for name in graph.order:
        r = state.stages[name]
        note = (
            r.summary or r.skipped_reason or (r.last_error.splitlines()[0] if r.last_error else "")
        )
        if r.used_fallback:
            note = "[fallback] " + note
        lines.append(f"{name:<16}{r.status.value:<19}{r.attempts:>5}{r.executions:>6}  {note[:60]}")
    lines.append("")
    approved = sum(a["decision"] == "approved" for a in state.approvals)
    arts = ", ".join(f"{k} v{v['version']}" for k, v in state.artifacts.items())
    lines.append(f"reworks used: {state.total_reworks}   approvals: {approved}   artifacts: {arts}")
    return lines


def trace_lines(state: RunState) -> list[str]:
    """Decision lineage: each decision with the artifact versions it was based on."""
    lines = []
    for d in state.decisions:
        inputs = ", ".join(f"{k}@{v[:8]}" for k, v in d.get("inputs", {}).items()) or "-"
        lines.append(f"[{d['stage']}] {d['summary']}  (by {d['actor']}; based on {inputs})")
        if d.get("rationale"):
            lines.append(f"    why: {d['rationale']}")
        if d.get("parents"):
            lines.append(
                f"    builds on: {', '.join(d['parents'][-4:])}"
                + (" ..." if len(d["parents"]) > 4 else "")
            )
    return lines


def _fmt(value: Any) -> str:
    return "n/a" if value is None else str(value)


def write_summary(store: RunStore, state: RunState, graph: Graph) -> str:
    events = list(EventLog(store.events_path).read())
    m = run_metrics(events)
    chain = verify_chain(events)
    spec = store.get_artifact(state, "spec") or {}
    plan = store.get_artifact(state, "plan") or {}
    design = store.get_artifact(state, "design") or {}
    adr = design.get("adr", {})
    review = store.get_artifact(state, "policy_report") or {}
    tests = store.get_artifact(state, "test_report") or {}

    out = [
        f"# Engineering summary: {spec.get('title') or state.scenario.get('name')}",
        "",
        f"- Run: `{state.run_id}`  |  Status: **{state.status.value}**  |  {state.message}",
        f"- Scenario: {state.scenario.get('name')} ({state.scenario.get('type')})",
        f"- Audit log: {len(events)} events, hash chain {'intact' if not chain else 'BROKEN'}",
        "",
        "## Requirement",
        "",
        state.scenario.get("requirement", "").strip(),
        "",
        "## Plan and rationale",
        "",
        *[f"- {t.get('id')}: {t.get('title')} ({t.get('stage')})" for t in plan.get("tasks", [])],
        "",
        f"Design: {design.get('summary', 'n/a')}",
        f"ADR: {adr.get('title', 'n/a')} - {adr.get('decision', '')}",
        "",
        "## Stage outcomes",
        "",
        "| Stage | Status | Attempts | Executions | Notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name in graph.order:
        r = state.stages[name]
        note = (r.summary or r.skipped_reason or "").replace("|", "/")[:80]
        if r.used_fallback:
            note = "fallback used; " + note
        out.append(f"| {name} | {r.status.value} | {r.attempts} | {r.executions} | {note} |")

    out += [
        "",
        "## Human oversight",
        "",
        *[
            f"- {a['stage']}: **{a['decision']}** by {a['actor']}"
            + (f" - {a['comment']}" if a["comment"] else "")
            for a in state.approvals
        ],
        "",
        "## Validation",
        "",
        f"- Tests: {'passed' if tests.get('passed') else 'not passed'} {tests.get('counts', '')}",
        *[
            f"- Policy [{f['severity']}] {f['rule']}: {f['message']} {f.get('path', '')}"
            for f in review.get("findings", [])
        ],
        "",
        "## Risks and trade-offs",
        "",
        *[f"- {r.get('risk')} -> {r.get('mitigation')}" for r in plan.get("risks", [])],
        "",
        "## Assumptions",
        "",
        *[f"- {a}" for a in spec.get("assumptions", [])],
        *[
            f"- Ambiguity resolved: {a.get('question')} -> {a.get('proposed_default')}"
            for a in spec.get("ambiguities", [])
        ],
        "",
        "## Reliability metrics",
        "",
        *[f"- {k}: {_fmt(v)}" for k, v in m.items()],
        "",
        "## Artifacts",
        "",
        *[
            f"- {k} v{v['version']} ({v['producer']}): `{v['path']}`"
            for k, v in state.artifacts.items()
        ],
        "",
        "## Apply the change (human step)",
        "",
        "```",
        "git checkout -b feat/<name>",
        f"git apply runs/{state.run_id}/changes.patch",
        "pytest --cov",
        "```",
        "",
    ]
    text = "\n".join(out)
    (store.dir / "summary.md").write_text(text, encoding="utf-8")
    return text
