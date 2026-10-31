"""Scenario files: what to build, how to classify it, and (for mock mode) canned responses.

scenarios/<name>/scenario.yaml:
    name: add-version-endpoint
    type: brownfield            # greenfield | brownfield | ambiguous
    requirement: |
      Free-text request as a stakeholder would write it.
    faults:                     # optional: inject transient failures (stage: count)
      docs: 1
mock responses live in scenarios/<name>/mock/<stage>[.<n>].json
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

VALID_TYPES = {"greenfield", "brownfield", "ambiguous"}


class ScenarioError(ValueError):
    pass


def load_scenario(path: Path, extra_faults: dict[str, int] | None = None) -> dict[str, Any]:
    file = path / "scenario.yaml" if path.is_dir() else path
    if not file.exists():
        raise ScenarioError(f"scenario file not found: {file}")
    raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    for key in ("name", "type", "requirement"):
        if not raw.get(key):
            raise ScenarioError(f"{file}: missing required field {key!r}")
    if raw["type"] not in VALID_TYPES:
        raise ScenarioError(f"{file}: type must be one of {sorted(VALID_TYPES)}")
    faults = {**(raw.get("faults") or {}), **(extra_faults or {})}
    return {
        "name": str(raw["name"]),
        "type": raw["type"],
        "requirement": str(raw["requirement"]),
        "faults": {k: int(v) for k, v in faults.items()},
        "mock_dir": str((file.parent / raw.get("mock_dir", "mock")).resolve()),
        "source": str(file.resolve()),
    }
