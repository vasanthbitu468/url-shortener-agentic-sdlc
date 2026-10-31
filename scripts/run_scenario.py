"""Run a scenario end to end, playing the human steps listed under ``demo_steps``.

    python scripts/run_scenario.py scenarios/greenfield-bulk-create
    python scripts/run_scenario.py --all --record      # all scenarios, save to runs/samples/

Each step waits for the run to reach the right state (e.g. a stage awaiting approval) and fails
loudly otherwise, so this doubles as an end-to-end check of the orchestration.
Steps:  approve: <stage>   |   reject: <stage>   |   edit: <artifact> + file: <json path>
(each with by: and comment:). In a real engagement these are people using the `sdlc` CLI.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.engine import EngineConfig, Orchestrator  # noqa: E402
from orchestrator.events import EventLog, verify_chain  # noqa: E402
from orchestrator.models import RunStatus, StageStatus  # noqa: E402
from orchestrator.reporting import status_lines  # noqa: E402
from orchestrator.scenario import load_scenario  # noqa: E402
from orchestrator.telemetry import run_metrics  # noqa: E402

SAMPLE_FILES = ("summary.md", "pr_description.md", "changes.patch", "events.jsonl", "state.json")


class StepError(RuntimeError):
    pass


def run_scenario(path: Path, runs_dir: Path, run_id: str | None = None, quiet: bool = False):
    scenario = load_scenario(path)
    raw = yaml.safe_load((path / "scenario.yaml").read_text(encoding="utf-8"))
    cfg = EngineConfig(runs_dir=runs_dir, repo_root=ROOT)
    orch = Orchestrator.create(scenario, cfg, run_id=run_id or scenario["name"])
    say = (lambda *_: None) if quiet else print

    say(f"\n=== {scenario['name']} ({scenario['type']}) ===")
    orch.run()
    for step in raw.get("demo_steps") or []:
        say(f"-> {orch.state.status.value}: {orch.state.message}")
        by, comment = step.get("by"), step.get("comment", "")
        if "approve" in step or "reject" in step:
            stage = step.get("approve") or step.get("reject")
            if orch.state.stages[stage].status != StageStatus.AWAITING_APPROVAL:
                raise StepError(
                    f"expected {stage} to await approval, run is "
                    f"{orch.state.status.value}: {orch.state.message}" + _errors(orch)
                )
            if "approve" in step:
                say(f"   {by} approves {stage}: {comment}")
                orch.approve(stage, actor=by, comment=comment)
            else:
                say(f"   {by} rejects {stage}: {comment}")
                orch.reject(stage, comment=comment, actor=by)
        elif "edit" in step:
            value = json.loads((path / step["file"]).read_text(encoding="utf-8"))
            say(f"   {by} edits {step['edit']}: {comment}")
            orch.edit_artifact(step["edit"], value, actor=by, reason=comment)
        else:
            raise StepError(f"unknown step {step}")
        orch.run()

    if not quiet:
        print("\n".join(status_lines(orch.state, orch.graph)))
    events = list(EventLog(orch.store.events_path).read())
    if verify_chain(events):
        raise StepError("audit log failed verification")
    if orch.state.status != RunStatus.COMPLETED:
        raise StepError(
            f"run ended {orch.state.status.value}: {orch.state.message}" + _errors(orch)
        )
    return orch, run_metrics(events)


def _errors(orch: Orchestrator) -> str:
    """Last error of every failed stage, so a broken run explains itself."""
    lines = [
        f"\n  {name}: {rec.last_error.splitlines()[0] if rec.last_error else '?'}"
        for name, rec in orch.state.stages.items()
        if rec.status == StageStatus.FAILED
    ]
    return "".join(lines)


def record(orch: Orchestrator, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in SAMPLE_FILES:
        src = orch.store.dir / name
        if src.exists():
            shutil.copy2(src, dest / name)
    shutil.copytree(orch.store.artifacts_dir, dest / "artifacts")
    # make machine-specific absolute paths repo-relative so samples read the same everywhere
    for f in [dest / "state.json", *(dest / "artifacts").glob("*.json")]:
        text = f.read_text(encoding="utf-8")
        for prefix in (str(ROOT) + "/", str(ROOT).replace("\\", "\\\\") + "\\\\"):
            text = text.replace(prefix, "")
        f.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("scenario", nargs="?")
    p.add_argument("--all", action="store_true", help="run every scenario under scenarios/")
    p.add_argument("--runs-dir", default=str(ROOT / "runs"))
    p.add_argument("--record", action="store_true", help="copy outputs to runs/samples/<name>")
    args = p.parse_args(argv)

    paths = (
        sorted(d for d in (ROOT / "scenarios").iterdir() if (d / "scenario.yaml").exists())
        if args.all
        else [Path(args.scenario).resolve()]
    )
    runs_dir = Path(args.runs_dir)
    results = {}
    for path in paths:
        name = path.name
        if (runs_dir / name).exists():
            shutil.rmtree(runs_dir / name)
        orch, metrics = run_scenario(path, runs_dir)
        results[name] = metrics
        if args.record:
            record(orch, runs_dir / "samples" / name)
    print("\nMetrics:")
    print(
        json.dumps(
            {
                k: {
                    m: v
                    for m, v in r.items()
                    if m
                    in (
                        "status",
                        "attempts",
                        "retries",
                        "rollbacks",
                        "reworks",
                        "replans",
                        "approvals",
                        "policy_violations",
                        "first_pass_success_rate",
                        "mttr_seconds",
                    )
                }
                for k, r in results.items()
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
