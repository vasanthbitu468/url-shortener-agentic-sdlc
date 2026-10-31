"""Entry and exit gates.

A gate is a pure function of what a stage produced (and the artifacts it can see). Entry gates
stop a stage from starting on bad inputs; exit gates decide whether its output is accepted.
A failed exit gate counts as a failed attempt: the engine rolls back the stage's writes and
retries with the gate's reasons as feedback.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from orchestrator.models import GateResult


@dataclass
class GateInput:
    outputs: dict[str, Any]
    artifact: Callable[[str], Any]
    scenario: dict[str, Any]


Gate = Callable[[GateInput], GateResult]


def requires_artifacts(*names: str) -> Gate:
    def gate(g: GateInput) -> GateResult:
        missing = [n for n in names if g.artifact(n) is None]
        return (
            GateResult.fail(*(f"missing input artifact {n!r}" for n in missing))
            if missing
            else GateResult.ok()
        )

    gate.__name__ = f"requires_artifacts({', '.join(names)})"
    return gate


def spec_is_complete(g: GateInput) -> GateResult:
    spec = g.outputs.get("spec") or {}
    reasons = []
    if not spec.get("title"):
        reasons.append("spec has no title")
    if not spec.get("acceptance_criteria"):
        reasons.append("spec has no acceptance criteria")
    for amb in spec.get("ambiguities", []):
        if not amb.get("proposed_default"):
            reasons.append(f"ambiguity without a proposed default: {amb.get('question', '?')}")
    return GateResult(not reasons, reasons)


def plan_is_valid(g: GateInput) -> GateResult:
    plan = g.outputs.get("plan") or {}
    tasks = plan.get("tasks") or []
    if not tasks:
        return GateResult.fail("plan has no tasks")
    ids = {t.get("id") for t in tasks}
    reasons = [
        f"task {t.get('id')} depends on unknown task {d}"
        for t in tasks
        for d in t.get("depends_on", [])
        if d not in ids
    ]
    # cycle check on the task graph
    deps = {t["id"]: set(t.get("depends_on", [])) for t in tasks if "id" in t}
    resolved: set[str] = set()
    while True:
        ready = {t for t, d in deps.items() if t not in resolved and d <= resolved}
        if not ready:
            break
        resolved |= ready
    if len(resolved) != len(deps):
        reasons.append("task dependencies contain a cycle")
    return GateResult(not reasons, reasons)


def impact_is_grounded(g: GateInput) -> GateResult:
    impact = g.outputs.get("impact") or {}
    modules = impact.get("modules") or []
    if not modules:
        return GateResult.fail("impact analysis names no affected modules")
    known = set(impact.get("_known_files", []))
    unknown = [
        m["path"] for m in modules if known and m.get("path") not in known and not m.get("new")
    ]
    if unknown:
        return GateResult.fail(*(f"impact names a file that does not exist: {p}" for p in unknown))
    return GateResult.ok()


def design_is_complete(g: GateInput) -> GateResult:
    design = g.outputs.get("design") or {}
    reasons = []
    for key in ("summary", "components", "adr"):
        if not design.get(key):
            reasons.append(f"design is missing {key!r}")
    for key in ("api_changes", "data_model_changes"):
        if not isinstance(design.get(key), bool):
            reasons.append(f"design must state {key!r} as true or false")
    return GateResult(not reasons, reasons)


def implementation_applied(g: GateInput) -> GateResult:
    impl = g.outputs.get("implementation") or {}
    reasons = []
    if not impl.get("changed_files"):
        reasons.append("implementation changed no files")
    reasons += [f"does not compile: {e}" for e in impl.get("compile_errors", [])]
    if impl.get("openapi_error"):
        reasons.append(f"could not regenerate API contract: {impl['openapi_error']}")
    return GateResult(not reasons, reasons)


def tests_pass(g: GateInput) -> GateResult:
    report = g.outputs.get("test_report") or {}
    reasons = []
    if not report.get("new_tests"):
        reasons.append("no new or changed tests for this change")
    if not report.get("passed"):
        reasons.append("test suite failed:\n" + report.get("output_tail", "")[-1500:])
    return GateResult(not reasons, reasons)


def docs_written(g: GateInput) -> GateResult:
    docs = g.outputs.get("docs") or {}
    if not docs.get("changed_files"):
        return GateResult.fail("no documentation was written")
    return GateResult.ok()


def policies_pass(g: GateInput) -> GateResult:
    report = g.outputs.get("policy_report") or {}
    blocking = [f for f in report.get("findings", []) if f["severity"] == "block"]
    reasons = [f"[{f['rule']}] {f['message']} {f.get('path', '')}".strip() for f in blocking]
    if report.get("lint_errors"):
        reasons.append("lint errors:\n" + report["lint_errors"][-1500:])
    return GateResult(not reasons, reasons)


def release_ready(g: GateInput) -> GateResult:
    release = g.outputs.get("release") or {}
    if not release.get("patch_lines"):
        return GateResult.fail("release has an empty patch")
    return GateResult.ok()


# ---- approval rules: (outputs) -> needs human sign-off? --------------------------------


def approve_if_ambiguous(outputs: dict[str, Any]) -> bool:
    return bool((outputs.get("spec") or {}).get("ambiguities"))


def approve_if_contract_or_schema_change(outputs: dict[str, Any]) -> bool:
    d = outputs.get("design") or {}
    return bool(d.get("api_changes") or d.get("data_model_changes"))


def always(_outputs: dict[str, Any]) -> bool:
    return True
