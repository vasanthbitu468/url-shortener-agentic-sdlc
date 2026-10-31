"""Requirements, planning, impact analysis and design agents (LLM-backed)."""

from __future__ import annotations

from orchestrator.agents.base import Agent, AgentContext, as_json, decisions_from, file_excerpts
from orchestrator.models import StageResult, TransientError

CORE_FILES = [
    "service/main.py",
    "service/api/routes.py",
    "service/api/schemas.py",
    "service/core/links.py",
    "service/db/models.py",
]


def _require(raw: dict, key: str) -> dict:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise TransientError(f"model response is missing the {key!r} object")
    return value


class RequirementsAgent(Agent):
    name = "requirements"

    def run(self, ctx: AgentContext) -> StageResult:
        sc = ctx.scenario
        prompt = f"""# Task: requirements analysis
Turn this {sc.get("type", "brownfield")} requirement into a precise engineering spec.

## Requirement (verbatim from the requester)
{sc["requirement"]}

## Existing code (file list)
{as_json(ctx.workspace.list_files("service"))}

## Rules
- List every ambiguity you see, each with a concrete proposed default. Do not guess silently.
- Acceptance criteria must be testable statements.

## Respond with JSON
{{"spec": {{"title": str, "description": str, "acceptance_criteria": [str],
  "ambiguities": [{{"question": str, "proposed_default": str}}], "assumptions": [str],
  "non_functional": [str], "out_of_scope": [str]}},
 "decisions": [{{"summary": str, "rationale": str}}]}}"""
        raw = ctx.ask(prompt)
        spec = _require(raw, "spec")
        return StageResult(
            outputs={"spec": spec},
            summary=f"{spec.get('title', '?')}: {len(spec.get('acceptance_criteria', []))} "
            f"acceptance criteria, {len(spec.get('ambiguities', []))} ambiguities",
            decisions=decisions_from(ctx, raw.get("decisions"), ()),
        )


class PlanningAgent(Agent):
    name = "planning"

    def run(self, ctx: AgentContext) -> StageResult:
        spec = ctx.artifact("spec")
        prompt = f"""# Task: plan the work
Decompose the spec into tasks with dependencies. Each task maps to one pipeline stage:
requirements, impact_analysis, design, implementation, tests, docs, review, release.
Scenario type: {ctx.scenario.get("type", "brownfield")}. Optional stages you may skip:
impact_analysis (skip only for greenfield work with no existing code to change).

## Spec
{as_json(spec)}

## Respond with JSON
{{"plan": {{"tasks": [{{"id": str, "title": str, "stage": str, "depends_on": [str],
  "estimate_hours": number}}], "risks": [{{"risk": str, "mitigation": str}}],
  "skip_stages": [str]}},
 "decisions": [{{"summary": str, "rationale": str}}]}}"""
        raw = ctx.ask(prompt)
        plan = _require(raw, "plan")
        return StageResult(
            outputs={"plan": plan},
            summary=f"{len(plan.get('tasks', []))} tasks, {len(plan.get('risks', []))} risks",
            decisions=decisions_from(ctx, raw.get("decisions"), ("spec",)),
            skip_stages=list(plan.get("skip_stages", [])),
        )


class ImpactAnalysisAgent(Agent):
    name = "impact_analysis"

    def run(self, ctx: AgentContext) -> StageResult:
        files = ctx.workspace.list_files("service") + ctx.workspace.list_files("tests")
        prompt = f"""# Task: impact analysis on the existing codebase
Identify which modules, APIs, data flows and tests this change touches, and the risk.

## Spec
{as_json(ctx.artifact("spec"))}

## Plan
{as_json(ctx.artifact("plan"))}

## Files in the repository
{as_json(files)}

## Key source files
{file_excerpts(ctx, CORE_FILES)}

## Respond with JSON
{{"impact": {{"modules": [{{"path": str, "change": str, "new": bool}}],
  "apis": [{{"endpoint": str, "change": "added|changed|removed"}}],
  "data_flows": [str], "tests_affected": [str],
  "risk_level": "low|medium|high", "risks": [str]}},
 "decisions": [{{"summary": str, "rationale": str}}]}}"""
        raw = ctx.ask(prompt)
        impact = _require(raw, "impact")
        impact["_known_files"] = files
        return StageResult(
            outputs={"impact": impact},
            summary=f"{len(impact.get('modules', []))} modules affected, "
            f"risk {impact.get('risk_level', '?')}",
            decisions=decisions_from(ctx, raw.get("decisions"), ("spec", "plan")),
        )


class DesignAgent(Agent):
    name = "design"

    def run(self, ctx: AgentContext) -> StageResult:
        prompt = f"""# Task: technical design
Produce the design and an architecture decision record (ADR). State explicitly whether the
public API contract or the database schema changes; those need human approval.

## Spec
{as_json(ctx.artifact("spec"))}

## Impact analysis (absent for greenfield)
{as_json(ctx.artifact("impact"))}

## Key source files
{file_excerpts(ctx, CORE_FILES, limit=8000)}

## Respond with JSON
{{"design": {{"summary": str, "components": [{{"name": str, "responsibility": str}}],
  "endpoints": [{{"method": str, "path": str, "response": str}}],
  "api_changes": bool, "data_model_changes": bool,
  "adr": {{"title": str, "context": str, "decision": str, "consequences": str}},
  "test_strategy": str}},
 "decisions": [{{"summary": str, "rationale": str}}]}}"""
        raw = ctx.ask(prompt)
        design = _require(raw, "design")
        return StageResult(
            outputs={"design": design},
            summary=design.get("summary", ""),
            decisions=decisions_from(ctx, raw.get("decisions"), ("spec", "impact")),
        )
