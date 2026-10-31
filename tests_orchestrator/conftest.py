import json
import shutil
from pathlib import Path

import pytest

from orchestrator.engine import EngineConfig, Orchestrator
from orchestrator.scenario import load_scenario

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "scenarios" / "demo-version-endpoint"


async def no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def runs_dir(tmp_path) -> Path:
    return tmp_path / "runs"


@pytest.fixture
def make_config(runs_dir):
    def _make(**kw) -> EngineConfig:
        return EngineConfig(runs_dir=runs_dir, repo_root=REPO, sleep=no_sleep, **kw)

    return _make


@pytest.fixture
def demo_scenario():
    return load_scenario(DEMO)


@pytest.fixture
def custom_scenario(tmp_path):
    """Copy the demo scenario so a test can override individual mock responses."""

    def _make(overrides: dict[str, dict] | None = None, remove: tuple[str, ...] = (), **fields):
        dest = tmp_path / "scenario"
        shutil.copytree(DEMO, dest)
        for name in remove:
            (dest / "mock" / name).unlink()
        for name, body in (overrides or {}).items():
            (dest / "mock" / name).write_text(json.dumps(body), encoding="utf-8")
        sc = load_scenario(dest)
        sc.update(fields)
        return sc

    return _make


@pytest.fixture
def start(make_config):
    def _start(scenario, run_id="r1", **cfg) -> Orchestrator:
        return Orchestrator.create(scenario, make_config(**cfg), run_id=run_id)

    return _start


def events_of(orch: Orchestrator, type_: str | None = None) -> list[dict]:
    evs = list(orch.events.read())
    return [e for e in evs if type_ is None or e["type"] == type_]
