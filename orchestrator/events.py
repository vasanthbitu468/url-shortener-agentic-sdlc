"""Append-only, hash-chained audit log (one JSON object per line).

Each event carries the hash of the previous one, so any edit, deletion or reordering of the
log is detectable with ``verify_chain``. The log is the single source for traceability
(``sdlc trace``) and reliability metrics (``sdlc metrics``).
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _digest(event: dict[str, Any]) -> str:
    body = {k: v for k, v in event.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class EventLog:
    def __init__(self, path: Path, clock: Callable[[], str] = utc_now) -> None:
        self.path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._seq, self._last_hash = self._tail()

    def _tail(self) -> tuple[int, str]:
        if not self.path.exists():
            return 0, GENESIS
        last = None
        for event in self.read():
            last = event
        return (last["seq"], last["hash"]) if last else (0, GENESIS)

    def emit(
        self,
        type_: str,
        *,
        run_id: str,
        stage: str | None = None,
        actor: str = "engine",
        **data: Any,
    ) -> dict[str, Any]:
        with self._lock:
            event = {
                "seq": self._seq + 1,
                "ts": self._clock(),
                "run_id": run_id,
                "type": type_,
                "stage": stage,
                "actor": actor,
                "data": data,
                "prev_hash": self._last_hash,
            }
            event["hash"] = _digest(event)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, default=str) + "\n")
            self._seq, self._last_hash = event["seq"], event["hash"]
            return event

    def read(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


def verify_chain(events: list[dict[str, Any]]) -> list[str]:
    """Return a list of problems; empty means the log is intact."""
    problems: list[str] = []
    prev = GENESIS
    for i, ev in enumerate(events, start=1):
        if ev.get("seq") != i:
            problems.append(f"event {i}: sequence is {ev.get('seq')}, expected {i}")
        if ev.get("prev_hash") != prev:
            problems.append(f"event {i}: prev_hash does not match event {i - 1}")
        if _digest(ev) != ev.get("hash"):
            problems.append(f"event {i}: content was modified (hash mismatch)")
        prev = ev.get("hash", "")
    return problems
