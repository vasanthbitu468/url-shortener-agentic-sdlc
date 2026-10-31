"""Agentic SDLC orchestrator.

A stateful DAG engine that drives a requirement through requirements -> planning -> impact
analysis -> design -> implementation -> (tests || docs) -> policy review -> release, with
entry/exit gates, human approval checkpoints, bounded retries, fallback, rework loops with
rollback, safe-stop/resume, re-planning on upstream change, and a hash-chained audit log.

Agents never touch the real repository: they work in a per-run sandbox copy, and the output
is a patch that a human reviews and applies.
"""

__version__ = "1.0.0"
