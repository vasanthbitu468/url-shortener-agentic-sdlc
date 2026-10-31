"""Core data types shared across the orchestrator."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


DONE_STATUSES = frozenset({StageStatus.COMPLETED, StageStatus.SKIPPED})


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"  # waiting for a human approval
    STOPPED = "stopped"  # safe-stop requested
    COMPLETED = "completed"
    FAILED = "failed"


class Impact(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: float = 0.5  # doubled after each failed attempt
    timeout_seconds: float = 600.0


@dataclass
class Decision:
    """One traceable decision made by an agent or a human."""

    id: str
    stage: str
    summary: str
    rationale: str = ""
    inputs: dict[str, str] = field(default_factory=dict)  # artifact name -> hash it was based on
    parents: list[str] = field(default_factory=list)  # ids of decisions this builds on
    actor: str = "agent"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StageResult:
    """What an agent hands back to the engine."""

    outputs: dict[str, Any] = field(default_factory=dict)  # artifact name -> JSON-able content
    summary: str = ""
    decisions: list[Decision] = field(default_factory=list)
    skip_stages: list[str] = field(default_factory=list)  # planning may skip optional stages


@dataclass
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    needs_approval: bool = False

    @classmethod
    def ok(cls, needs_approval: bool = False) -> GateResult:
        return cls(True, [], needs_approval)

    @classmethod
    def fail(cls, *reasons: str) -> GateResult:
        return cls(False, list(reasons))


class TransientError(RuntimeError):
    """A failure worth retrying (timeouts, flaky tools, rate limits)."""


class PolicyViolation(RuntimeError):
    """An agent tried something outside its autonomy boundary. Never retried blindly."""


def content_hash(value: Any) -> str:
    """Stable short hash of any JSON-able value (used for artifacts and lineage)."""
    raw = json.dumps(value, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]
