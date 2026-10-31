"""The orchestration engine.

Scheduling: every pass, all PENDING stages whose dependencies are done run concurrently
(``asyncio.gather``); a stage with several dependencies is a join point. State is persisted
after every transition, so a run can be stopped, approved, edited and resumed from any
process at any time.

Control paths:
    entry gate fail          -> stage FAILED (inputs are wrong; retrying cannot help)
    agent error / exit gate  -> roll back the stage's writes, retry with feedback, exponential
                                backoff, up to RetryPolicy.max_attempts
    retries exhausted        -> fallback agent if defined, else rework: roll back to the rework
                                target's checkpoint and redo it and everything downstream with
                                the failure as feedback (bounded by max_reworks), else FAILED
    high-impact output       -> AWAITING_APPROVAL; descendants wait; run PAUSES when nothing
                                else can progress
    STOP file present        -> finish in-flight stages, persist, run STOPPED; resume continues
    upstream artifact edited -> re-plan: stale stages and their descendants are reset
"""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestrator.agents import REGISTRY, AgentContext
from orchestrator.events import EventLog
from orchestrator.gates import GateInput
from orchestrator.graph import Graph, Stage
from orchestrator.llm import LLM, build_llm
from orchestrator.models import (
    DONE_STATUSES,
    Decision,
    GateResult,
    PolicyViolation,
    RunStatus,
    StageResult,
    StageStatus,
    TransientError,
)
from orchestrator.pipeline import default_pipeline
from orchestrator.reporting import write_summary
from orchestrator.state import RunState, RunStore, StageRecord
from orchestrator.workspace import Workspace


class EngineError(RuntimeError):
    pass


@dataclass
class EngineConfig:
    runs_dir: Path
    repo_root: Path
    llm_mode: str = "mock"
    auto_approve: bool = False
    max_reworks: int = 2
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    graph_factory: Callable[[], Graph] = field(default=default_pipeline)


@dataclass
class _Outcome:
    kind: str  # "ok" | "failed" | "rework"
    reasons: list[str] = field(default_factory=list)


def new_run_id(name: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{name}-{stamp}-{secrets.token_hex(2)}"


def default_actor() -> str:
    return os.environ.get("USERNAME") or os.environ.get("USER") or "human"


class Orchestrator:
    def __init__(
        self, store: RunStore, state: RunState, config: EngineConfig, llm: LLM | None = None
    ):
        self.store = store
        self.state = state
        self.config = config
        self.graph = config.graph_factory()
        self.events = EventLog(store.events_path)
        self.workspace = Workspace(store.dir)
        mock_dir = Path(state.scenario.get("mock_dir", "."))
        self.llm = llm or build_llm(config.llm_mode, mock_dir)
        self._checkpoint_seq = (
            sum(1 for _ in self.workspace.checkpoints.glob("cp*"))
            if self.workspace.checkpoints.exists()
            else 0
        )

    # ---- construction -------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        scenario: dict[str, Any],
        config: EngineConfig,
        run_id: str | None = None,
        llm: LLM | None = None,
    ) -> Orchestrator:
        run_id = run_id or new_run_id(scenario["name"])
        store = RunStore(config.runs_dir, run_id)
        if store.exists():
            raise EngineError(f"run {run_id} already exists")
        graph = config.graph_factory()
        state = RunState(
            run_id=run_id, scenario=scenario, stages={name: StageRecord() for name in graph.order}
        )
        store.save(state)
        orch = cls(store, state, config, llm)
        orch.workspace.create_from(config.repo_root)
        orch._emit(
            "run_created",
            scenario=scenario["name"],
            type=scenario.get("type"),
            llm=orch.llm.name,
            stages=graph.order,
            levels=graph.levels(),
        )
        return orch

    @classmethod
    def load(cls, run_id: str, config: EngineConfig, llm: LLM | None = None) -> Orchestrator:
        store = RunStore(config.runs_dir, run_id)
        if not store.exists():
            raise EngineError(f"no run named {run_id!r} in {config.runs_dir}")
        return cls(store, store.load(), config, llm)

    # ---- helpers ------------------------------------------------------------------------

    def _emit(self, type_: str, stage: str | None = None, actor: str = "engine", **data: Any):
        return self.events.emit(type_, run_id=self.state.run_id, stage=stage, actor=actor, **data)

    def _save(self) -> None:
        self.store.save(self.state)

    def _artifact(self, name: str) -> Any:
        return self.store.get_artifact(self.state, name)

    def _hashes(self, names: tuple[str, ...]) -> dict[str, str]:
        return {n: h for n in names if (h := self.store.artifact_hash(self.state, n))}

    def _rec(self, name: str) -> StageRecord:
        return self.state.stages[name]

    def _set(self, name: str, status: StageStatus) -> None:
        self._rec(name).status = status

    def _reset(self, names: set[str] | list[str]) -> None:
        for n in names:
            rec = self._rec(n)
            rec.status = StageStatus.PENDING
            rec.attempts = 0
            rec.feedback = []
            rec.skipped_reason = ""
            rec.used_fallback = False

    def _restore_for(self, names: set[str], label: str | None) -> None:
        scopes = tuple(sorted({w for n in names for w in self.graph[n].writes}))
        if label and scopes:
            self.workspace.restore(label, scopes)
            self._emit("rollback", checkpoint=label, scopes=list(scopes), stages=sorted(names))

    # ---- public control API (used by the CLI) -------------------------------------------

    def run(self) -> RunState:
        return asyncio.run(self.run_async())

    async def run_async(self) -> RunState:
        if self.state.status == RunStatus.COMPLETED:
            return self.state
        if self.store.stop_requested():
            return self._stopped()
        resumed = self.state.status != RunStatus.CREATED
        self.state.status = RunStatus.RUNNING
        self._emit(
            "run_resumed" if resumed else "run_started", auto_approve=self.config.auto_approve
        )
        self._replan_if_stale()
        self._save()

        while True:
            if self.store.stop_requested():
                return self._stopped()
            ready = [
                n
                for n in self.graph.order
                if self._rec(n).status == StageStatus.PENDING
                and all(self._rec(d).status in DONE_STATUSES for d in self.graph[n].depends_on)
            ]
            if not ready:
                return self._finish()

            self._checkpoint_seq += 1
            label = self.workspace.checkpoint(f"cp{self._checkpoint_seq:03d}")
            for n in ready:
                self._rec(n).checkpoint = label
            if len(ready) > 1:
                self._emit("parallel_batch", stages=ready, checkpoint=label)
            self._save()

            outcomes = await asyncio.gather(*(self._execute(n) for n in ready))
            for name, outcome in zip(ready, outcomes, strict=True):
                if outcome.kind == "rework":
                    self._rework(name, outcome.reasons)
            self._save()

    def approve(self, stage: str, actor: str | None = None, comment: str = "") -> None:
        rec = self._require_awaiting(stage)
        actor = actor or default_actor()
        approved = self._hashes(self.graph[stage].outputs)  # includes any human edits
        self.state.approvals.append(
            {
                "stage": stage,
                "decision": "approved",
                "actor": actor,
                "comment": comment,
                "ts": datetime.now(UTC).isoformat(),
                "output_hashes": approved,
            }
        )
        self.store.add_decision(
            self.state,
            Decision(
                id=f"approval-{stage}-{len(self.state.approvals)}",
                stage=stage,
                summary=f"{stage} approved",
                rationale=comment,
                inputs=approved,
                parents=list(rec.decision_ids),
                actor=f"human:{actor}",
            ),
        )
        rec.status = StageStatus.COMPLETED
        self._emit("approval_granted", stage=stage, actor=f"human:{actor}", comment=comment)
        self._save()

    def reject(self, stage: str, comment: str, actor: str | None = None) -> None:
        rec = self._require_awaiting(stage)
        actor = actor or default_actor()
        if not comment.strip():
            raise EngineError("a rejection needs a comment explaining what to change")
        self.state.approvals.append(
            {
                "stage": stage,
                "decision": "rejected",
                "actor": actor,
                "comment": comment,
                "ts": datetime.now(UTC).isoformat(),
                "output_hashes": rec.output_hashes,
            }
        )
        affected = {stage} | self.graph.descendants(stage)
        self._restore_for(affected, rec.checkpoint)
        self._reset(affected)
        self._rec(stage).feedback = [f"Rejected by reviewer {actor}: {comment}"]
        self._emit(
            "approval_rejected",
            stage=stage,
            actor=f"human:{actor}",
            comment=comment,
            reset=sorted(affected),
        )
        self._save()

    def edit_artifact(
        self, name: str, value: Any, actor: str | None = None, reason: str = ""
    ) -> None:
        actor = actor or default_actor()
        old = self.store.artifact_hash(self.state, name)
        new = self.store.put_artifact(self.state, name, value, producer=f"human:{actor}")
        self.store.add_decision(
            self.state,
            Decision(
                id=f"edit-{name}-{new[:8]}",
                stage="human",
                summary=f"{name} edited by {actor}",
                rationale=reason,
                inputs={name: new},
                actor=f"human:{actor}",
            ),
        )
        self._emit(
            "artifact_edited",
            actor=f"human:{actor}",
            artifact=name,
            old_hash=old,
            new_hash=new,
            reason=reason,
        )
        self._save()

    def request_stop(self, reason: str = "", actor: str | None = None) -> None:
        self.store.request_stop(reason)
        self._emit("safe_stop_requested", actor=f"human:{actor or default_actor()}", reason=reason)

    def resume_after_stop(self, actor: str | None = None) -> None:
        if self.store.stop_requested():
            self.store.clear_stop()
            self._emit("safe_stop_cleared", actor=f"human:{actor or default_actor()}")

    def _require_awaiting(self, stage: str) -> StageRecord:
        if stage not in self.state.stages:
            raise EngineError(f"unknown stage {stage!r}")
        rec = self._rec(stage)
        if rec.status != StageStatus.AWAITING_APPROVAL:
            raise EngineError(f"stage {stage!r} is {rec.status.value}, not awaiting approval")
        return rec

    # ---- stage execution ----------------------------------------------------------------

    def _context(
        self, stage: Stage, feedback: list[str], attempt: int, agent_stage: str
    ) -> AgentContext:
        def next_call() -> int:
            self.state.llm_calls[agent_stage] = self.state.llm_calls.get(agent_stage, 0) + 1
            return self.state.llm_calls[agent_stage]

        return AgentContext(
            run_id=self.state.run_id,
            stage=agent_stage,
            scenario=self.state.scenario,
            workspace=self.workspace,
            run_dir=self.store.dir,
            llm=self.llm,
            allowed_writes=stage.writes,
            artifact=self._artifact,
            artifact_hash=lambda n: self.store.artifact_hash(self.state, n),
            next_call_index=next_call,
            feedback=list(feedback),
            attempt=attempt,
        )

    def _gate(self, gate, outputs: dict[str, Any]) -> GateResult:
        if gate is None:
            return GateResult.ok()
        return gate(
            GateInput(outputs=outputs, artifact=self._artifact, scenario=self.state.scenario)
        )

    async def _attempt(self, stage: Stage, agent_name: str, feedback: list[str], attempt: int):
        rec = self._rec(stage.name)
        rec.executions += 1
        self._emit("attempt_started", stage=stage.name, attempt=attempt, agent=agent_name)
        try:
            faults = int(self.state.scenario.get("faults", {}).get(stage.name, 0))
            if agent_name == stage.agent and rec.executions <= faults:
                raise TransientError(f"injected fault {rec.executions}/{faults}")
            agent = REGISTRY[agent_name]()
            ctx = self._context(stage, feedback, attempt, agent_name)
            result: StageResult = await asyncio.wait_for(
                asyncio.to_thread(agent.run, ctx), timeout=stage.retry.timeout_seconds
            )
            return result, self._gate(stage.exit_gate, result.outputs)
        except PolicyViolation as exc:
            self._emit("policy_violation", stage=stage.name, error=str(exc))
            return None, GateResult.fail(f"autonomy boundary: {exc}")
        except TimeoutError:
            return None, GateResult.fail(f"timed out after {stage.retry.timeout_seconds}s")
        except Exception as exc:  # noqa: BLE001 - any agent failure is a failed attempt
            return None, GateResult.fail(f"{type(exc).__name__}: {exc}")

    async def _execute(self, name: str) -> _Outcome:
        stage = self.graph[name]
        rec = self._rec(name)
        rec.status = StageStatus.RUNNING
        self._emit(
            "stage_started",
            stage=name,
            checkpoint=rec.checkpoint,
            inputs=self._hashes(stage.inputs),
        )

        entry = self._gate(stage.entry_gate, {})
        if not entry.passed:
            rec.status = StageStatus.FAILED
            rec.last_error = "; ".join(entry.reasons)
            self._emit("stage_failed", stage=name, gate="entry", reasons=entry.reasons)
            return _Outcome("failed", entry.reasons)

        feedback = list(rec.feedback)
        delay = stage.retry.backoff_seconds
        result: StageResult | None = None
        gate = GateResult.fail("not run")
        while rec.attempts < stage.retry.max_attempts:
            rec.attempts += 1
            result, gate = await self._attempt(stage, stage.agent, feedback, rec.attempts)
            if gate.passed:
                break
            rec.last_error = "\n".join(gate.reasons)[:2000]
            self._restore_for({name}, rec.checkpoint)
            feedback = list(rec.feedback) + gate.reasons
            self._emit("attempt_failed", stage=name, attempt=rec.attempts, reasons=gate.reasons)
            if rec.attempts < stage.retry.max_attempts:
                self._emit(
                    "retry_scheduled",
                    stage=name,
                    next_attempt=rec.attempts + 1,
                    backoff_seconds=delay,
                )
                self._save()
                await self.config.sleep(delay)
                delay *= 2

        if not gate.passed and stage.fallback_agent:
            self._emit("fallback_started", stage=name, agent=stage.fallback_agent)
            result, gate = await self._attempt(
                stage, stage.fallback_agent, feedback, rec.attempts + 1
            )
            if gate.passed:
                rec.used_fallback = True
            else:
                self._restore_for({name}, rec.checkpoint)

        if not gate.passed or result is None:
            if stage.rework_target:
                return _Outcome("rework", gate.reasons)
            rec.status = StageStatus.FAILED
            self._emit("stage_failed", stage=name, gate="exit", reasons=gate.reasons)
            return _Outcome("failed", gate.reasons)

        self._accept(stage, result, gate)
        return _Outcome("ok")

    def _accept(self, stage: Stage, result: StageResult, gate: GateResult) -> None:
        rec = self._rec(stage.name)
        rec.input_hashes = self._hashes(stage.inputs)
        rec.output_hashes = {}
        for art, value in result.outputs.items():
            digest = self.store.put_artifact(self.state, art, value, producer=stage.name)
            rec.output_hashes[art] = digest
            self._emit(
                "artifact_written",
                stage=stage.name,
                artifact=art,
                hash=digest,
                version=self.state.artifacts[art]["version"],
            )

        parents = [d for n in self.graph.ancestors(stage.name) for d in self._rec(n).decision_ids]
        rec.decision_ids = []
        for d in result.decisions:
            d.parents = d.parents or parents
            self.store.add_decision(self.state, d)
            rec.decision_ids.append(d.id)
        rec.summary = result.summary
        rec.feedback = []
        rec.last_error = ""

        if result.skip_stages:
            self._apply_skips(stage.name, result.skip_stages)

        needs_approval = gate.needs_approval or bool(
            stage.approval and stage.approval(result.outputs)
        )
        if needs_approval and self.config.auto_approve:
            self.state.approvals.append(
                {
                    "stage": stage.name,
                    "decision": "approved",
                    "actor": "auto-approve",
                    "comment": "--auto-approve flag (CI / demo)",
                    "ts": datetime.now(UTC).isoformat(),
                    "output_hashes": rec.output_hashes,
                }
            )
            self._emit(
                "approval_granted",
                stage=stage.name,
                actor="auto-approve",
                comment="--auto-approve flag",
            )
            needs_approval = False

        if needs_approval:
            rec.status = StageStatus.AWAITING_APPROVAL
            self._emit(
                "approval_requested",
                stage=stage.name,
                summary=result.summary,
                outputs=list(result.outputs),
                impact=stage.impact.value,
            )
        else:
            rec.status = StageStatus.COMPLETED
            self._emit(
                "stage_completed",
                stage=stage.name,
                summary=result.summary,
                attempts=rec.attempts,
                fallback=rec.used_fallback,
            )

    def _apply_skips(self, by: str, requested: list[str]) -> None:
        skipped, refused = [], []
        for n in requested:
            if (
                n in self.graph.stages
                and self.graph[n].optional
                and self._rec(n).status == StageStatus.PENDING
            ):
                self._rec(n).status = StageStatus.SKIPPED
                self._rec(n).skipped_reason = f"skipped by {by}"
                skipped.append(n)
            else:
                refused.append(n)
        self._emit("stages_skipped", stage=by, skipped=skipped, refused=refused)

    # ---- recovery -----------------------------------------------------------------------

    def _rework(self, failed: str, reasons: list[str]) -> None:
        target = self.graph[failed].rework_target
        if target is None:  # pragma: no cover - only stages with a target return "rework"
            raise EngineError(f"stage {failed!r} has no rework target")
        if self.state.total_reworks >= self.config.max_reworks:
            self._set(failed, StageStatus.FAILED)
            self._emit(
                "rework_limit_reached", stage=failed, limit=self.config.max_reworks, reasons=reasons
            )
            return
        self.state.total_reworks += 1
        self._rec(target).reworks += 1
        affected = {target} | self.graph.descendants(target)
        self._restore_for(affected, self._rec(target).checkpoint)
        self._reset(affected)
        self._rec(target).feedback = [f"{failed} failed after retries: {r}" for r in reasons]
        self._emit(
            "rework",
            stage=target,
            cause=failed,
            reasons=reasons,
            reset=sorted(affected),
            rework_number=self.state.total_reworks,
        )

    def _replan_if_stale(self) -> None:
        """Reset any stage whose inputs changed since it ran, plus everything downstream."""
        invalidated: set[str] = set()
        for name in self.graph.order:
            rec = self._rec(name)
            if name in invalidated or rec.status not in (
                StageStatus.COMPLETED,
                StageStatus.AWAITING_APPROVAL,
            ):
                continue
            current = self._hashes(self.graph[name].inputs)
            if rec.input_hashes and current != rec.input_hashes:
                changed = sorted(k for k in current if current.get(k) != rec.input_hashes.get(k))
                affected = {name} | self.graph.descendants(name)
                self._restore_for(affected, rec.checkpoint)
                self._reset(affected)
                invalidated |= affected
                self._emit("replan", stage=name, changed_inputs=changed, reset=sorted(affected))
                self.store.add_decision(
                    self.state,
                    Decision(
                        id=f"replan-{name}-{len(self.state.decisions)}",
                        stage="engine",
                        summary=f"Re-plan from {name}: inputs {changed} changed",
                        rationale="upstream artifact changed after this stage ran",
                        inputs={k: current[k] for k in changed},
                        actor="engine",
                    ),
                )

    # ---- terminal states ----------------------------------------------------------------

    def _stopped(self) -> RunState:
        for rec in self.state.stages.values():
            if rec.status == StageStatus.RUNNING:
                rec.status = StageStatus.PENDING
        self.state.status = RunStatus.STOPPED
        self.state.message = "safe-stop: state persisted; run `sdlc resume` to continue"
        self._emit("run_stopped")
        self._save()
        return self.state

    def _finish(self) -> RunState:
        statuses = {n: r.status for n, r in self.state.stages.items()}
        waiting = [n for n, s in statuses.items() if s == StageStatus.AWAITING_APPROVAL]
        failed = [n for n, s in statuses.items() if s == StageStatus.FAILED]
        if all(s in DONE_STATUSES for s in statuses.values()):
            self.state.status = RunStatus.COMPLETED
            self.state.message = "release ready: review changes.patch and pr_description.md"
            self._emit("run_completed")
        elif waiting:
            self.state.status = RunStatus.PAUSED
            self.state.message = f"waiting for human approval: {', '.join(waiting)}"
            self._emit("run_paused", waiting_for=waiting)
        else:
            self.state.status = RunStatus.FAILED
            self.state.message = f"failed at: {', '.join(failed) or 'no runnable stage'}"
            self._emit("run_failed", failed=failed)
        self._save()
        write_summary(self.store, self.state, self.graph)
        return self.state
