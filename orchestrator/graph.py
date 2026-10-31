"""Explicit dependency graph of SDLC stages.

The graph is data, validated at load time (unknown dependencies, cycles, bad rework targets).
The engine schedules any stage whose dependencies are done, so independent stages run in
parallel and a stage with several dependencies acts as a synchronisation (join) point.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from orchestrator.models import Impact, RetryPolicy

if TYPE_CHECKING:
    from orchestrator.gates import Gate


class GraphError(ValueError):
    pass


@dataclass(frozen=True)
class Stage:
    name: str
    agent: str  # key in the agent registry
    depends_on: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()  # artifacts read (change -> stage is stale -> re-plan)
    outputs: tuple[str, ...] = ()  # artifacts produced
    writes: tuple[str, ...] = ()  # workspace paths this stage may modify (autonomy boundary)
    entry_gate: Gate | None = None
    exit_gate: Gate | None = None
    approval: Callable[[dict], bool] | None = None  # (outputs) -> human sign-off needed?
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    fallback_agent: str | None = None
    rework_target: str | None = None  # on exhausted retries, roll back and redo this stage
    optional: bool = False  # planning may skip it
    impact: Impact = Impact.LOW
    description: str = ""


class Graph:
    def __init__(self, stages: Iterable[Stage]) -> None:
        self.stages: dict[str, Stage] = {}
        for s in stages:
            if s.name in self.stages:
                raise GraphError(f"duplicate stage {s.name!r}")
            self.stages[s.name] = s
        self._validate()
        self.order = self._topological_order()

    def __getitem__(self, name: str) -> Stage:
        return self.stages[name]

    def __iter__(self):
        return iter(self.order)

    def _validate(self) -> None:
        for s in self.stages.values():
            for dep in s.depends_on:
                if dep not in self.stages:
                    raise GraphError(f"stage {s.name!r} depends on unknown stage {dep!r}")
            if s.rework_target and s.rework_target not in self.ancestors(s.name):
                raise GraphError(
                    f"stage {s.name!r}: rework target {s.rework_target!r} must be an upstream stage"
                )
        self._topological_order()  # raises on cycles

    def _topological_order(self) -> list[str]:
        indegree = {n: len(s.depends_on) for n, s in self.stages.items()}
        ready = [n for n in self.stages if indegree[n] == 0]
        order: list[str] = []
        while ready:
            n = ready.pop(0)
            order.append(n)
            for child in self.children(n):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if len(order) != len(self.stages):
            stuck = sorted(set(self.stages) - set(order))
            raise GraphError(f"dependency cycle among stages: {', '.join(stuck)}")
        return order

    def children(self, name: str) -> list[str]:
        return [n for n, s in self.stages.items() if name in s.depends_on]

    def ancestors(self, name: str) -> set[str]:
        seen: set[str] = set()
        stack = list(self.stages[name].depends_on)
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.add(n)
                stack.extend(self.stages[n].depends_on)
        return seen

    def descendants(self, name: str) -> set[str]:
        seen: set[str] = set()
        stack = self.children(name)
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.add(n)
                stack.extend(self.children(n))
        return seen

    def levels(self) -> list[list[str]]:
        """Stages grouped by depth; stages in one level can run in parallel."""
        depth: dict[str, int] = {}
        for n in self.order:
            deps = self.stages[n].depends_on
            depth[n] = 1 + max((depth[d] for d in deps), default=-1)
        out: list[list[str]] = [[] for _ in range(max(depth.values()) + 1)]
        for n in self.order:
            out[depth[n]].append(n)
        return out
