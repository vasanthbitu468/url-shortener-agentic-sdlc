"""Command-line interface: ``sdlc <command>`` (or ``python -m orchestrator <command>``).

sdlc run scenarios/add-version-endpoint     start a run (pauses at approval checkpoints)
sdlc status <run>                           stage table
sdlc approve <run> <stage> [-m comment]     human sign-off, then the run continues
sdlc reject <run> <stage> -m "what to fix"  send the stage back with feedback
sdlc edit <run> spec edited_spec.json       change an artifact; downstream re-plans
sdlc stop <run> / sdlc resume <run>         safe-stop and resume
sdlc trace <run>                            decision lineage
sdlc verify <run>                           check the audit log hash chain
sdlc metrics [<run>]                        reliability metrics
sdlc list | sdlc graph
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orchestrator.engine import EngineConfig, EngineError, Orchestrator
from orchestrator.events import EventLog, verify_chain
from orchestrator.pipeline import default_pipeline
from orchestrator.reporting import status_lines, trace_lines
from orchestrator.scenario import ScenarioError, load_scenario
from orchestrator.telemetry import aggregate, run_metrics


def _config(args: argparse.Namespace) -> EngineConfig:
    return EngineConfig(
        runs_dir=Path(args.runs_dir).resolve(),
        repo_root=Path(args.repo).resolve(),
        llm_mode=getattr(args, "llm", "mock"),
        auto_approve=getattr(args, "auto_approve", False),
    )


def _print_status(orch: Orchestrator) -> None:
    print("\n".join(status_lines(orch.state, orch.graph)))
    st = orch.state.status.value
    if st == "paused":
        waiting = [n for n, r in orch.state.stages.items() if r.status.value == "awaiting_approval"]
        rid = orch.state.run_id
        print("\nNext: review the outputs in", orch.store.artifacts_dir)
        for w in waiting:
            print(f'  sdlc approve {rid} {w} -m "looks good"')
            print(f'  sdlc reject  {rid} {w} -m "what to change"')
    elif st == "completed":
        print(f"\nOutputs: {orch.store.dir / 'changes.patch'}")
        print(f"         {orch.store.dir / 'pr_description.md'}")
        print(f"         {orch.store.dir / 'summary.md'}")


def _faults(values: list[str]) -> dict[str, int]:
    out = {}
    for v in values:
        stage, _, n = v.partition("=")
        out[stage] = int(n or 1)
    return out


def cmd_run(args) -> int:
    scenario = load_scenario(Path(args.scenario), _faults(args.fault))
    orch = Orchestrator.create(scenario, _config(args), run_id=args.run_id)
    print(f"Created run {orch.state.run_id} ({scenario['type']}, llm={orch.llm.name})")
    orch.run()
    _print_status(orch)
    return 0 if orch.state.status.value in ("completed", "paused") else 1


def cmd_resume(args) -> int:
    orch = Orchestrator.load(args.run_id, _config(args))
    orch.resume_after_stop()
    orch.run()
    _print_status(orch)
    return 0 if orch.state.status.value in ("completed", "paused") else 1


def cmd_status(args) -> int:
    _print_status(Orchestrator.load(args.run_id, _config(args)))
    return 0


def cmd_approve(args) -> int:
    orch = Orchestrator.load(args.run_id, _config(args))
    orch.approve(args.stage, actor=args.by, comment=args.message)
    print(f"Approved {args.stage}.")
    if not args.no_resume:
        orch.run()
        _print_status(orch)
    return 0


def cmd_reject(args) -> int:
    orch = Orchestrator.load(args.run_id, _config(args))
    orch.reject(args.stage, comment=args.message, actor=args.by)
    print(f"Rejected {args.stage}; it will be redone with your feedback.")
    if not args.no_resume:
        orch.run()
        _print_status(orch)
    return 0


def cmd_edit(args) -> int:
    orch = Orchestrator.load(args.run_id, _config(args))
    value = json.loads(Path(args.file).read_text(encoding="utf-8"))
    orch.edit_artifact(args.artifact, value, actor=args.by, reason=args.message)
    print(f"Updated {args.artifact}. Stages that used it will re-plan on the next run.")
    if not args.no_resume:
        orch.run()
        _print_status(orch)
    return 0


def cmd_stop(args) -> int:
    orch = Orchestrator.load(args.run_id, _config(args))
    orch.request_stop(args.message, actor=args.by)
    print("Safe-stop requested: in-flight stages finish, then the run halts with state saved.")
    return 0


def cmd_trace(args) -> int:
    orch = Orchestrator.load(args.run_id, _config(args))
    print("\n".join(trace_lines(orch.state)))
    return 0


def cmd_verify(args) -> int:
    orch = Orchestrator.load(args.run_id, _config(args))
    events = list(EventLog(orch.store.events_path).read())
    problems = verify_chain(events)
    if problems:
        print("AUDIT LOG TAMPERED:\n" + "\n".join(problems))
        return 2
    print(f"Audit log intact: {len(events)} events, hash chain verified.")
    return 0


def cmd_metrics(args) -> int:
    runs_dir = Path(args.runs_dir).resolve()
    if args.run_id:
        data = run_metrics(list(EventLog(runs_dir / args.run_id / "events.jsonl").read()))
    else:
        data = aggregate(runs_dir)
    print(json.dumps(data, indent=2))
    return 0


def cmd_list(args) -> int:
    runs_dir = Path(args.runs_dir).resolve()
    for state_file in sorted(runs_dir.glob("*/state.json")):
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        print(f"{raw['run_id']:<55} {raw['status']:<10} {raw.get('message', '')}")
    return 0


def cmd_graph(_args) -> int:
    g = default_pipeline()
    for i, level in enumerate(g.levels()):
        print(f"level {i}: {' || '.join(level)}")
    print()
    for name in g.order:
        s = g[name]
        extras = [f"after {','.join(s.depends_on)}" if s.depends_on else "start"]
        if s.approval:
            extras.append("human approval")
        if s.rework_target:
            extras.append(f"rework->{s.rework_target}")
        if s.fallback_agent:
            extras.append(f"fallback->{s.fallback_agent}")
        if s.optional:
            extras.append("optional")
        print(f"  {name:<16} {s.description}  [{'; '.join(extras)}]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sdlc", description="Governed agentic SDLC orchestrator")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--repo", default=".", help="repository root the run copies from")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="start a run from a scenario")
    r.add_argument("scenario")
    r.add_argument("--llm", choices=["mock", "live"], default="mock")
    r.add_argument("--auto-approve", action="store_true", help="CI/demo only: auto sign-off")
    r.add_argument(
        "--fault",
        action="append",
        default=[],
        metavar="STAGE=N",
        help="inject N transient failures into a stage",
    )
    r.add_argument("--run-id")
    r.set_defaults(func=cmd_run)

    for name, func in (("status", cmd_status), ("trace", cmd_trace), ("verify", cmd_verify)):
        s = sub.add_parser(name)
        s.add_argument("run_id")
        s.set_defaults(func=func)

    s = sub.add_parser("resume")
    s.add_argument("run_id")
    s.add_argument("--llm", choices=["mock", "live"], default="mock")
    s.add_argument("--auto-approve", action="store_true")
    s.set_defaults(func=cmd_resume)

    for name, func in (("approve", cmd_approve), ("reject", cmd_reject)):
        s = sub.add_parser(name)
        s.add_argument("run_id")
        s.add_argument("stage")
        s.add_argument("-m", "--message", default="")
        s.add_argument("--by", help="approver name (default: your OS user)")
        s.add_argument("--llm", choices=["mock", "live"], default="mock")
        s.add_argument("--no-resume", action="store_true")
        s.set_defaults(func=func)

    s = sub.add_parser("edit", help="replace an artifact with a human-edited version")
    s.add_argument("run_id")
    s.add_argument("artifact")
    s.add_argument("file")
    s.add_argument("-m", "--message", default="")
    s.add_argument("--by")
    s.add_argument("--llm", choices=["mock", "live"], default="mock")
    s.add_argument("--no-resume", action="store_true")
    s.set_defaults(func=cmd_edit)

    s = sub.add_parser("stop")
    s.add_argument("run_id")
    s.add_argument("-m", "--message", default="")
    s.add_argument("--by")
    s.set_defaults(func=cmd_stop)

    s = sub.add_parser("metrics")
    s.add_argument("run_id", nargs="?")
    s.set_defaults(func=cmd_metrics)

    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("graph").set_defaults(func=cmd_graph)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (EngineError, ScenarioError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
