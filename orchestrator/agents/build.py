"""Implementation, test and documentation agents."""

from __future__ import annotations

import re

from orchestrator.agents.analysis import CORE_FILES
from orchestrator.agents.base import Agent, AgentContext, as_json, decisions_from, file_excerpts
from orchestrator.models import StageResult, TransientError
from orchestrator.workspace import Edit

EDIT_SCHEMA = """{"edits": [{"path": str, "action": "create|replace|delete",
   "content": str (create: full file), "find": str, "replace": str (replace: exact unique text)}],
 "summary": str, "decisions": [{"summary": str, "rationale": str}]"""


def _edits(raw: dict) -> list[Edit]:
    edits = raw.get("edits")
    if not isinstance(edits, list) or not edits:
        raise TransientError("model response contains no edits")
    return [Edit.from_dict(e) for e in edits]


class ImplementationAgent(Agent):
    name = "implementation"

    def run(self, ctx: AgentContext) -> StageResult:
        impact = ctx.artifact("impact") or {}
        paths = list(dict.fromkeys([m["path"] for m in impact.get("modules", [])] + CORE_FILES))
        prompt = f"""# Task: implement the approved design
You may only edit paths under: {list(ctx.allowed_writes)}. Tests and docs are written by other
agents. Set "regenerate_openapi" to true if you change any endpoint.

## Spec
{as_json(ctx.artifact("spec"))}

## Approved design
{as_json(ctx.artifact("design"))}

## Current code
{file_excerpts(ctx, paths)}

## Respond with JSON
{EDIT_SCHEMA[:-1]}, "regenerate_openapi": bool}}"""
        raw = ctx.ask(prompt)
        changed = ctx.workspace.apply(_edits(raw), ctx.allowed_writes)
        compile_errors = ctx.workspace.compile_check(changed)
        openapi_error = ""
        if raw.get("regenerate_openapi") and not compile_errors:
            res = ctx.workspace.python("scripts/export_openapi.py", timeout=120)
            if res.ok:
                changed = sorted(set(changed) | {"service/openapi.json"})
            else:
                openapi_error = res.output[-800:]
        return StageResult(
            outputs={
                "implementation": {
                    "changed_files": changed,
                    "compile_errors": compile_errors,
                    "openapi_error": openapi_error,
                    "summary": raw.get("summary", ""),
                }
            },
            summary=f"changed {len(changed)} files: {', '.join(changed)}",
            decisions=decisions_from(ctx, raw.get("decisions"), ("spec", "design")),
        )


def _test_counts(output: str) -> dict[str, int]:
    counts = {}
    for n, label in re.findall(r"(\d+) (passed|failed|error|errors)", output):
        counts[label.rstrip("s") if label == "errors" else label] = int(n)
    return counts


class TestAgent(Agent):
    __test__ = False  # not a pytest test class
    name = "tests"

    def run(self, ctx: AgentContext) -> StageResult:
        impl = ctx.artifact("implementation") or {}
        prompt = f"""# Task: write tests for the change, then the full suite is run
Edit only under {list(ctx.allowed_writes)}. Use the existing fixtures in tests/conftest.py
(`client`, `app`, `session`). Cover every acceptance criterion and the main failure cases.

## Spec
{as_json(ctx.artifact("spec"))}

## Design (test strategy)
{as_json((ctx.artifact("design") or {}).get("test_strategy", ""))}

## Changed code
{file_excerpts(ctx, impl.get("changed_files", []))}

## Test fixtures
{file_excerpts(ctx, ["tests/conftest.py"])}

## Respond with JSON
{EDIT_SCHEMA}"""
        raw = ctx.ask(prompt)
        changed = ctx.workspace.apply(_edits(raw), ctx.allowed_writes)
        result = ctx.workspace.python(
            "-m", "pytest", "-o", "addopts=", "-q", "-p", "no:cacheprovider", timeout=600
        )
        report = {
            "passed": result.ok,
            "new_tests": changed,
            "counts": _test_counts(result.output),
            "output_tail": result.output[-3000:],
        }
        return StageResult(
            outputs={"test_report": report},
            summary=f"suite {'passed' if result.ok else 'FAILED'} {report['counts']}",
            decisions=decisions_from(ctx, raw.get("decisions"), ("spec", "implementation")),
        )


class DocsAgent(Agent):
    name = "docs"

    def run(self, ctx: AgentContext) -> StageResult:
        prompt = f"""# Task: document the change for developers and API consumers
Edit only under {list(ctx.allowed_writes)}. Write docs/changes/<short-name>.md covering what
changed, how to use it (with an example request), and the design decision (ADR).

## Spec
{as_json(ctx.artifact("spec"))}

## Design
{as_json(ctx.artifact("design"))}

## Respond with JSON
{EDIT_SCHEMA}"""
        raw = ctx.ask(prompt)
        changed = ctx.workspace.apply(_edits(raw), ctx.allowed_writes)
        return StageResult(
            outputs={"docs": {"changed_files": changed, "generated_by": "llm"}},
            summary=f"wrote {', '.join(changed)}",
            decisions=decisions_from(ctx, raw.get("decisions"), ("spec", "design")),
        )


class TemplateDocsAgent(Agent):
    """Fallback when the docs agent keeps failing: deterministic docs from spec + design."""

    name = "docs_template"
    uses_llm = False

    def run(self, ctx: AgentContext) -> StageResult:
        spec = ctx.artifact("spec") or {}
        design = ctx.artifact("design") or {}
        adr = design.get("adr", {})
        lines = [
            f"# {spec.get('title', 'Change')}",
            "",
            spec.get("description", ""),
            "",
            "## Acceptance criteria",
            *[f"- {c}" for c in spec.get("acceptance_criteria", [])],
            "",
            "## Endpoints",
            *[
                f"- `{e.get('method')} {e.get('path')}` → {e.get('response')}"
                for e in design.get("endpoints", [])
            ],
            "",
            f"## Decision: {adr.get('title', '')}",
            f"- Context: {adr.get('context', '')}",
            f"- Decision: {adr.get('decision', '')}",
            f"- Consequences: {adr.get('consequences', '')}",
            "",
            "_Generated from the approved spec and design by the fallback docs agent._",
        ]
        path = f"docs/changes/{ctx.run_id}.md"
        changed = ctx.workspace.apply(
            [Edit(path=path, action="create", content="\n".join(lines) + "\n")], ctx.allowed_writes
        )
        return StageResult(
            outputs={"docs": {"changed_files": changed, "generated_by": "template-fallback"}},
            summary=f"fallback wrote {path}",
            decisions=[
                ctx.decision(
                    "Used template documentation",
                    "LLM docs agent exhausted its retries",
                    ("spec", "design"),
                )
            ],
        )
