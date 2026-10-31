"""Policy review and release-readiness agents (deterministic tools, no LLM)."""

from __future__ import annotations

import importlib.util

from orchestrator import policies
from orchestrator.agents.base import Agent, AgentContext
from orchestrator.models import StageResult


class ReviewAgent(Agent):
    name = "review"
    uses_llm = False

    def run(self, ctx: AgentContext) -> StageResult:
        cs = policies.collect_changes(ctx.workspace, ctx.artifact("design"))
        findings = policies.evaluate(cs)

        lint_errors = ""
        if importlib.util.find_spec("ruff") is not None:
            res = ctx.workspace.python("-m", "ruff", "check", "--no-cache", "service", "tests")
            if not res.ok:
                lint_errors = res.output
        else:  # pragma: no cover - ruff is a dev dependency
            findings.append(policies.Finding("quality.lint", policies.WARN, "ruff not installed"))

        report = {
            "findings": [f.to_dict() for f in findings],
            "lint_errors": lint_errors,
            "changed_files": cs.changed,
            "diff_lines": cs.diff_lines,
        }
        blocking = sum(f.severity == policies.BLOCK for f in findings) + bool(lint_errors)
        return StageResult(
            outputs={"policy_report": report},
            summary=f"{len(cs.changed)} files, {cs.diff_lines} changed lines, "
            f"{len(findings)} findings ({blocking} blocking)",
            decisions=[
                ctx.decision(
                    f"Policy review: {'pass' if not blocking else 'blocked'}",
                    f"{len(policies.RULES)} rules evaluated plus lint",
                    ("design", "implementation", "test_report", "docs"),
                )
            ],
        )


class ReleaseAgent(Agent):
    name = "release"
    uses_llm = False

    def run(self, ctx: AgentContext) -> StageResult:
        patch = ctx.workspace.diff()
        (ctx.run_dir / "changes.patch").write_text(patch, encoding="utf-8", newline="\n")

        spec = ctx.artifact("spec") or {}
        design = ctx.artifact("design") or {}
        tests = ctx.artifact("test_report") or {}
        review = ctx.artifact("policy_report") or {}
        plan = ctx.artifact("plan") or {}
        needs_approval = [f for f in review.get("findings", []) if f["severity"] == "approval"]
        warnings = [f for f in review.get("findings", []) if f["severity"] == "warn"]

        pr = [
            f"## {spec.get('title', 'Change')}",
            "",
            spec.get("description", ""),
            "",
            "### What changed",
            *[f"- `{p}` ({k})" for p, k in review.get("changed_files", {}).items()],
            "",
            "### Design",
            design.get("summary", ""),
            f"- API contract change: {design.get('api_changes')}",
            f"- Schema change: {design.get('data_model_changes')}",
            "",
            "### Validation",
            f"- Test suite: {'passed' if tests.get('passed') else 'failed'} "
            f"{tests.get('counts', {})}",
            f"- Policy review: {len(review.get('findings', []))} findings, none blocking",
            *[f"- Needs approval: [{f['rule']}] {f['message']}" for f in needs_approval],
            *[f"- Warning: [{f['rule']}] {f['message']}" for f in warnings],
            "",
            "### Risks",
            *[f"- {r.get('risk')} → {r.get('mitigation')}" for r in plan.get("risks", [])],
            "",
            "### Rollback",
            "Revert this PR. No data migration is involved unless listed under schema change.",
            "",
            f"_Produced by orchestrator run `{ctx.run_id}`; full audit trail in "
            f"runs/{ctx.run_id}/events.jsonl._",
        ]
        (ctx.run_dir / "pr_description.md").write_text(
            "\n".join(pr) + "\n", encoding="utf-8", newline="\n"
        )

        patch_lines = patch.count("\n")
        return StageResult(
            outputs={
                "release": {
                    "patch_file": "changes.patch",
                    "patch_lines": patch_lines,
                    "files": list(review.get("changed_files", {})),
                    "needs_approval": needs_approval,
                }
            },
            summary=f"patch ready: {len(review.get('changed_files', {}))} files, "
            f"{patch_lines} lines",
            decisions=[
                ctx.decision(
                    "Release candidate prepared",
                    "all upstream gates passed",
                    ("test_report", "policy_report"),
                )
            ],
        )
