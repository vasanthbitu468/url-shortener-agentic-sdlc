"""Agent interface.

An agent is a small class with one method, ``run(ctx) -> StageResult``. It reads artifacts and
the workspace through ``AgentContext``, may ask the LLM for a JSON answer, and returns
outputs. It never changes run state directly; the engine decides what to accept.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestrator.llm import LLM
from orchestrator.models import Decision, StageResult, content_hash
from orchestrator.workspace import Workspace


@dataclass
class AgentContext:
    run_id: str
    stage: str
    scenario: dict[str, Any]
    workspace: Workspace
    run_dir: Path
    llm: LLM
    allowed_writes: tuple[str, ...]
    artifact: Callable[[str], Any]
    artifact_hash: Callable[[str], str | None]
    next_call_index: Callable[[], int]
    feedback: list[str] = field(default_factory=list)
    attempt: int = 1

    def ask(self, prompt: str) -> dict[str, Any]:
        if self.feedback:
            prompt += (
                "\n\n## Feedback on your previous attempt (address every point)\n"
                + "\n".join(f"- {f}" for f in self.feedback)
            )
        return self.llm.complete(self.stage, prompt, self.next_call_index())

    def decision(self, summary: str, rationale: str = "", inputs: tuple[str, ...] = ()) -> Decision:
        hashes = {n: h for n in inputs if (h := self.artifact_hash(n))}
        return Decision(
            id=f"{self.stage}-{content_hash([summary, hashes, self.attempt])[:8]}",
            stage=self.stage,
            summary=summary,
            rationale=rationale,
            inputs=hashes,
        )


class Agent:
    name: str = "agent"
    uses_llm: bool = True

    def run(self, ctx: AgentContext) -> StageResult:  # pragma: no cover - interface
        raise NotImplementedError


def as_json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)


def decisions_from(
    ctx: AgentContext, raw: list[dict] | None, inputs: tuple[str, ...]
) -> list[Decision]:
    """Turn the model's {summary, rationale} list into traceable decisions."""
    return [ctx.decision(d.get("summary", ""), d.get("rationale", ""), inputs) for d in (raw or [])]


def file_excerpts(ctx: AgentContext, paths: list[str], limit: int = 12_000) -> str:
    """Current content of workspace files, for grounding prompts in the real code."""
    parts, used = [], 0
    for p in paths:
        try:
            text = ctx.workspace.read(p)
        except (FileNotFoundError, IsADirectoryError):
            continue
        if used + len(text) > limit:
            parts.append(f"### {p}\n(omitted: prompt budget reached)")
            continue
        used += len(text)
        parts.append(f"### {p}\n```\n{text}\n```")
    return "\n\n".join(parts)
