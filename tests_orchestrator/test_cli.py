"""CLI end to end: the commands a human uses during a run."""

import json

from orchestrator import cli

from .conftest import DEMO, REPO


def sdlc(runs_dir, *args):
    return cli.main(["--runs-dir", str(runs_dir), "--repo", str(REPO), *args])


def test_cli_full_human_workflow(runs_dir, tmp_path, capsys, monkeypatch):
    import orchestrator.engine as engine

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(
        engine.EngineConfig, "__init__", _patched_init(engine.EngineConfig, no_sleep)
    )

    assert sdlc(runs_dir, "graph") == 0
    assert "tests || docs" in capsys.readouterr().out

    assert sdlc(runs_dir, "run", str(DEMO), "--run-id", "c1") == 0
    out = capsys.readouterr().out
    assert "PAUSED" in out and "sdlc approve c1 design" in out

    assert sdlc(runs_dir, "status", "c1") == 0
    assert sdlc(runs_dir, "reject", "c1", "design", "-m", "tighten ADR", "--no-resume") == 0
    assert sdlc(runs_dir, "resume", "c1") == 0

    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"title": "Version endpoint v2", "acceptance_criteria": ["x"]}))
    assert sdlc(runs_dir, "edit", "c1", "spec", str(spec), "-m", "scope change") == 0
    capsys.readouterr()

    assert sdlc(runs_dir, "approve", "c1", "design", "-m", "ok", "--by", "lead") == 0
    assert "release" in capsys.readouterr().out
    assert sdlc(runs_dir, "stop", "c1", "-m", "pause") == 0
    assert sdlc(runs_dir, "approve", "c1", "release", "--no-resume") == 0
    assert sdlc(runs_dir, "resume", "c1") == 0
    out = capsys.readouterr().out
    assert "COMPLETED" in out and "changes.patch" in out

    assert sdlc(runs_dir, "trace", "c1") == 0
    assert "human:lead" in capsys.readouterr().out
    assert sdlc(runs_dir, "verify", "c1") == 0
    assert "hash chain verified" in capsys.readouterr().out
    assert sdlc(runs_dir, "metrics", "c1") == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
    assert sdlc(runs_dir, "metrics") == 0
    assert json.loads(capsys.readouterr().out)["runs"] == 1
    assert sdlc(runs_dir, "list") == 0
    assert "c1" in capsys.readouterr().out

    # tamper with the audit log -> verify fails
    log = runs_dir / "c1" / "events.jsonl"
    lines = log.read_text().splitlines()
    ev = json.loads(lines[3])
    ev["actor"] = "someone-else"
    lines[3] = json.dumps(ev)
    log.write_text("\n".join(lines) + "\n")
    assert sdlc(runs_dir, "verify", "c1") == 2
    assert "TAMPERED" in capsys.readouterr().out


def test_cli_errors(runs_dir, capsys):
    assert sdlc(runs_dir, "status", "missing") == 2
    assert "no run named" in capsys.readouterr().err
    assert sdlc(runs_dir, "run", "does/not/exist") == 2


def _patched_init(cls, sleep):
    original = cls.__init__

    def init(self, *a, **kw):
        original(self, *a, **kw)
        self.sleep = sleep

    return init
