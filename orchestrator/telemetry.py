"""Reliability metrics, computed from the audit log only (no separate counters to drift).

Per run:
    stage first-pass success rate   stages accepted on attempt 1 / stages accepted
    attempt success rate            successful attempts / attempts
    retries, rollbacks, reworks, fallbacks, policy violations, re-plans
    MTTR                            mean seconds from a failed attempt to that stage's next
                                    accepted output
    end-to-end latency              run_created -> run_completed
    human wait                      approval_requested -> approval_granted / rejected
Across runs:
    run success rate                completed runs / runs
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from orchestrator.events import EventLog

ACCEPTED = ("stage_completed", "approval_requested")


def _ts(ev: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(ev["ts"])


def run_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    count = lambda t: sum(1 for e in events if e["type"] == t)  # noqa: E731
    attempts = count("attempt_started")
    failed_attempts = count("attempt_failed")

    accepted_first_try = 0
    accepted = sum(1 for e in events if e["type"] in ACCEPTED)
    # first-pass: accepted stages whose preceding attempt_started had attempt == 1
    last_attempt: dict[str, int] = {}
    for e in events:
        if e["type"] == "attempt_started":
            last_attempt[e["stage"]] = e["data"]["attempt"]
        elif e["type"] in ACCEPTED and last_attempt.get(e["stage"]) == 1:
            accepted_first_try += 1

    # MTTR: failure -> next acceptance of the same stage
    repair_times: list[float] = []
    open_failures: dict[str, datetime] = {}
    for e in events:
        if e["type"] in ("attempt_failed", "stage_failed") and e["stage"]:
            open_failures.setdefault(e["stage"], _ts(e))
        elif e["type"] in ACCEPTED and e["stage"] in open_failures:
            repair_times.append((_ts(e) - open_failures.pop(e["stage"])).total_seconds())

    # human wait
    waits: list[float] = []
    asked: dict[str, datetime] = {}
    for e in events:
        if e["type"] == "approval_requested":
            asked[e["stage"]] = _ts(e)
        elif e["type"] in ("approval_granted", "approval_rejected") and e["stage"] in asked:
            waits.append((_ts(e) - asked.pop(e["stage"])).total_seconds())

    start = next((_ts(e) for e in events if e["type"] == "run_created"), None)
    end = next((_ts(e) for e in reversed(events) if e["type"] == "run_completed"), None)
    latency = (end - start).total_seconds() if start and end else None
    human_wait = round(sum(waits), 3)

    return {
        "status": next(
            (
                e["type"].removeprefix("run_")
                for e in reversed(events)
                if e["type"] in ("run_completed", "run_failed", "run_paused", "run_stopped")
            ),
            "running",
        ),
        "attempts": attempts,
        "attempt_success_rate": round((attempts - failed_attempts) / attempts, 3)
        if attempts
        else None,
        "stages_accepted": accepted,
        "first_pass_success_rate": round(accepted_first_try / accepted, 3) if accepted else None,
        "retries": count("retry_scheduled"),
        "rollbacks": count("rollback"),
        "reworks": count("rework"),
        "fallbacks": count("fallback_started"),
        "replans": count("replan"),
        "policy_violations": count("policy_violation"),
        "approvals": count("approval_granted"),
        "rejections": count("approval_rejected"),
        "mttr_seconds": round(mean(repair_times), 3) if repair_times else None,
        "end_to_end_latency_seconds": round(latency, 3) if latency is not None else None,
        "human_wait_seconds": human_wait,
        "agent_time_seconds": round(latency - human_wait, 3) if latency is not None else None,
    }


def aggregate(runs_dir: Path) -> dict[str, Any]:
    per_run = {}
    for log in sorted(runs_dir.glob("*/events.jsonl")):
        per_run[log.parent.name] = run_metrics(list(EventLog(log).read()))
    total = len(per_run)
    completed = sum(1 for m in per_run.values() if m["status"] == "completed")

    def avg(key: str) -> float | None:
        values = [m[key] for m in per_run.values() if m[key] is not None]
        return round(mean(values), 3) if values else None

    attempts = sum(m["attempts"] for m in per_run.values())
    return {
        "runs": total,
        "run_success_rate": round(completed / total, 3) if total else None,
        "retries_per_run": round(sum(m["retries"] for m in per_run.values()) / total, 3)
        if total
        else None,
        "rollbacks_per_run": round(sum(m["rollbacks"] for m in per_run.values()) / total, 3)
        if total
        else None,
        "retry_frequency": round(sum(m["retries"] for m in per_run.values()) / attempts, 3)
        if attempts
        else None,
        "rollback_frequency": round(sum(m["rollbacks"] for m in per_run.values()) / attempts, 3)
        if attempts
        else None,
        "mean_mttr_seconds": avg("mttr_seconds"),
        "mean_latency_seconds": avg("end_to_end_latency_seconds"),
        "per_run": per_run,
    }
