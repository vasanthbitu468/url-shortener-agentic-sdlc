"""Persistent run state.

Layout of ``runs/<run_id>/``:
    state.json        stage statuses, artifact index, decisions, approvals (rewritten atomically)
    events.jsonl      hash-chained audit log
    artifacts/        every artifact version as JSON (never overwritten)
    baseline/         snapshot of the repo the run started from
    workspace/        sandbox the agents edit
    checkpoints/      workspace snapshots used for rollback
    STOP              present while a safe-stop is requested
    changes.patch, summary.md, pr_description.md   release outputs
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestrator.models import Decision, RunStatus, StageStatus, content_hash


@dataclass
class StageRecord:
    status: StageStatus = StageStatus.PENDING
    attempts: int = 0  # attempts in the current pass
    executions: int = 0  # total agent executions across the run
    reworks: int = 0
    input_hashes: dict[str, str] = field(default_factory=dict)
    output_hashes: dict[str, str] = field(default_factory=dict)
    checkpoint: str | None = None  # workspace snapshot taken before this stage last started
    feedback: list[str] = field(default_factory=list)  # from failed gates / rejections
    summary: str = ""
    last_error: str = ""
    used_fallback: bool = False
    skipped_reason: str = ""
    decision_ids: list[str] = field(default_factory=list)  # decisions of the accepted output


@dataclass
class RunState:
    run_id: str
    scenario: dict[str, Any]
    status: RunStatus = RunStatus.CREATED
    stages: dict[str, StageRecord] = field(default_factory=dict)
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)  # name -> index entry
    decisions: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: dict[str, int] = field(default_factory=dict)
    total_reworks: int = 0
    message: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario": self.scenario,
            "status": self.status.value,
            "stages": {n: {**r.__dict__, "status": r.status.value} for n, r in self.stages.items()},
            "artifacts": self.artifacts,
            "decisions": self.decisions,
            "approvals": self.approvals,
            "llm_calls": self.llm_calls,
            "total_reworks": self.total_reworks,
            "message": self.message,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> RunState:
        stages = {
            n: StageRecord(**{**r, "status": StageStatus(r["status"])})
            for n, r in raw["stages"].items()
        }
        return cls(
            run_id=raw["run_id"],
            scenario=raw["scenario"],
            status=RunStatus(raw["status"]),
            stages=stages,
            artifacts=raw["artifacts"],
            decisions=raw["decisions"],
            approvals=raw["approvals"],
            llm_calls=raw.get("llm_calls", {}),
            total_reworks=raw.get("total_reworks", 0),
            message=raw.get("message", ""),
        )


class RunStore:
    """Filesystem persistence for one run."""

    def __init__(self, runs_dir: Path, run_id: str) -> None:
        self.run_id = run_id
        self.dir = runs_dir / run_id
        self.state_path = self.dir / "state.json"
        self.events_path = self.dir / "events.jsonl"
        self.artifacts_dir = self.dir / "artifacts"
        self.stop_path = self.dir / "STOP"

    def exists(self) -> bool:
        return self.state_path.exists()

    def save(self, state: RunState) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(state.to_json(), indent=2, default=str), encoding="utf-8", newline="\n"
        )
        os.replace(tmp, self.state_path)  # atomic: a crash never leaves half-written state

    def load(self) -> RunState:
        return RunState.from_json(json.loads(self.state_path.read_text(encoding="utf-8")))

    # ---- artifacts ----------------------------------------------------------------------

    def put_artifact(self, state: RunState, name: str, value: Any, producer: str) -> str:
        digest = content_hash(value)
        current = state.artifacts.get(name)
        if current and current["hash"] == digest:
            return digest
        version = (current["version"] + 1) if current else 1
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifacts_dir / f"{name}.v{version}.json"
        path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8", newline="\n")
        state.artifacts[name] = {
            "hash": digest,
            "version": version,
            "producer": producer,
            "path": str(path.relative_to(self.dir)),
        }
        return digest

    def get_artifact(self, state: RunState, name: str) -> Any:
        entry = state.artifacts.get(name)
        if entry is None:
            return None
        return json.loads((self.dir / entry["path"]).read_text(encoding="utf-8"))

    def artifact_hash(self, state: RunState, name: str) -> str | None:
        entry = state.artifacts.get(name)
        return entry["hash"] if entry else None

    def add_decision(self, state: RunState, decision: Decision) -> None:
        state.decisions.append(decision.to_dict())

    # ---- safe-stop ----------------------------------------------------------------------

    def request_stop(self, reason: str = "") -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stop_path.write_text(reason or "stop requested", encoding="utf-8", newline="\n")

    def stop_requested(self) -> bool:
        return self.stop_path.exists()

    def clear_stop(self) -> None:
        self.stop_path.unlink(missing_ok=True)
