"""Integration tests: full runs through the engine, one per control path."""

import json

import pytest

from orchestrator.engine import EngineError, Orchestrator
from orchestrator.events import verify_chain
from orchestrator.graph import Graph, Stage
from orchestrator.models import RunStatus, StageStatus
from orchestrator.telemetry import aggregate, run_metrics

from .conftest import events_of


def statuses(orch):
    return {n: r.status for n, r in orch.state.stages.items()}


def test_happy_path_with_auto_approve_exercises_retry_rework_and_parallel(start, demo_scenario):
    orch = start(demo_scenario, auto_approve=True)
    state = orch.run()

    assert state.status == RunStatus.COMPLETED
    assert all(s == StageStatus.COMPLETED for s in statuses(orch).values())
    # docs failed once (injected) and was retried; review blocked the leaked key -> rework
    assert orch.state.stages["docs"].executions >= 2
    assert orch.state.total_reworks == 1
    assert orch.state.stages["implementation"].executions == 2
    rework = events_of(orch, "rework")[0]
    assert rework["stage"] == "implementation" and "no_secrets" in rework["data"]["reasons"][0]
    assert events_of(orch, "parallel_batch")[0]["data"]["stages"] == ["tests", "docs"]

    # outputs
    patch = (orch.store.dir / "changes.patch").read_text()
    assert "service/api/version.py" in patch and "sk-live" not in patch
    assert (orch.store.dir / "summary.md").exists() and (
        orch.store.dir / "pr_description.md"
    ).exists()
    report = orch.store.get_artifact(orch.state, "test_report")
    assert report["passed"] and report["counts"]["passed"] >= 70

    # governance trail
    assert verify_chain(events_of(orch)) == []
    assert {a["actor"] for a in orch.state.approvals} == {"auto-approve"}
    m = run_metrics(events_of(orch))
    assert m["status"] == "completed" and m["reworks"] == 1 and m["retries"] >= 1
    assert m["rollbacks"] >= 2 and m["mttr_seconds"] is not None
    # lineage: implementation decisions build on design decisions
    impl = [d for d in orch.state.decisions if d["stage"] == "implementation"][-1]
    assert any(p.startswith("design-") for p in impl["parents"]) and "design" in impl["inputs"]


def test_human_approval_checkpoints_pause_and_resume(start, make_config, demo_scenario):
    orch = start(demo_scenario)
    assert orch.run().status == RunStatus.PAUSED
    assert statuses(orch)["design"] == StageStatus.AWAITING_APPROVAL
    assert statuses(orch)["implementation"] == StageStatus.PENDING

    with pytest.raises(EngineError, match="not awaiting"):
        orch.approve("release")
    with pytest.raises(EngineError, match="unknown stage"):
        orch.approve("nope")

    # a new process picks the run up from disk
    orch2 = Orchestrator.load("r1", make_config())
    orch2.approve("design", actor="alice", comment="ok")
    assert orch2.run().status == RunStatus.PAUSED
    assert statuses(orch2)["release"] == StageStatus.AWAITING_APPROVAL
    orch2.approve("release", actor="alice")
    assert orch2.run().status == RunStatus.COMPLETED
    assert [a["actor"] for a in orch2.state.approvals] == ["alice", "alice"]
    assert orch2.run().status == RunStatus.COMPLETED  # idempotent
    waits = run_metrics(events_of(orch2))["human_wait_seconds"]
    assert waits >= 0


def test_rejection_sends_stage_back_with_feedback(start, demo_scenario):
    orch = start(demo_scenario)
    orch.run()
    with pytest.raises(EngineError, match="comment"):
        orch.reject("design", comment="  ")
    orch.reject("design", comment="add rate limiting", actor="bob")
    assert statuses(orch)["design"] == StageStatus.PENDING
    assert "add rate limiting" in orch.state.stages["design"].feedback[0]
    orch.run()
    assert orch.state.stages["design"].executions == 2
    assert statuses(orch)["design"] == StageStatus.AWAITING_APPROVAL
    assert events_of(orch, "approval_rejected")[0]["actor"] == "human:bob"


def test_safe_stop_mid_run_and_resume(start, demo_scenario):
    orch = start(demo_scenario, auto_approve=True)

    async def stop_on_first_backoff(_s):  # docs retry triggers a backoff -> request stop then
        orch.request_stop("operator pressed stop", actor="ops")

    orch.config.sleep = stop_on_first_backoff
    state = orch.run()
    assert state.status == RunStatus.STOPPED
    assert not any(s == StageStatus.RUNNING for s in statuses(orch).values())
    assert orch.run().status == RunStatus.STOPPED  # still stopped until cleared

    orch.resume_after_stop(actor="ops")
    assert orch.run().status == RunStatus.COMPLETED
    types = [e["type"] for e in events_of(orch)]
    assert (
        "safe_stop_requested" in types and "run_stopped" in types and "safe_stop_cleared" in types
    )


def test_fallback_when_docs_agent_keeps_failing(start, custom_scenario):
    orch = start(custom_scenario(faults={"docs": 20}), auto_approve=True)  # fails on every pass
    assert orch.run().status == RunStatus.COMPLETED
    docs = orch.store.get_artifact(orch.state, "docs")
    assert docs["generated_by"] == "template-fallback"
    assert orch.state.stages["docs"].used_fallback
    assert (orch.workspace.root / "docs" / "changes" / "r1.md").exists()
    assert run_metrics(events_of(orch))["fallbacks"] >= 1


def test_rework_limit_fails_the_run_safely(start, demo_scenario):
    orch = start(demo_scenario, auto_approve=True, max_reworks=0)
    state = orch.run()
    assert state.status == RunStatus.FAILED
    assert statuses(orch)["review"] == StageStatus.FAILED
    assert events_of(orch, "rework_limit_reached")
    assert not (orch.store.dir / "changes.patch").exists()  # nothing released
    assert "review" in state.message


def test_replan_when_human_edits_the_spec(start, demo_scenario):
    orch = start(demo_scenario)
    orch.run()  # paused at design
    spec = orch.store.get_artifact(orch.state, "spec")
    spec["acceptance_criteria"].append("Response includes Cache-Control: no-store")
    orch.edit_artifact("spec", spec, actor="pm", reason="ops asked for no caching")

    orch.run()
    replan = events_of(orch, "replan")[0]
    assert replan["stage"] == "planning" and replan["data"]["changed_inputs"] == ["spec"]
    assert set(replan["data"]["reset"]) >= {"planning", "impact_analysis", "design", "release"}
    assert orch.state.stages["planning"].executions == 2
    assert orch.state.artifacts["spec"]["version"] == 2
    assert orch.state.artifacts["spec"]["producer"] == "human:pm"
    assert statuses(orch)["design"] == StageStatus.AWAITING_APPROVAL
    assert any(d["summary"].startswith("Re-plan") for d in orch.state.decisions)


def test_ambiguous_spec_requires_sign_off(start, custom_scenario, demo_scenario):
    spec = json.loads(
        (__import__("pathlib").Path(demo_scenario["mock_dir"]) / "requirements.json").read_text()
    )
    spec["spec"]["ambiguities"] = [{"question": "Auth?", "proposed_default": "none"}]
    orch = start(custom_scenario({"requirements.json": spec}))
    assert orch.run().status == RunStatus.PAUSED
    assert statuses(orch)["requirements"] == StageStatus.AWAITING_APPROVAL
    assert statuses(orch)["planning"] == StageStatus.PENDING


def test_planning_can_skip_optional_stages_only(start, custom_scenario, demo_scenario):
    plan = json.loads(
        (__import__("pathlib").Path(demo_scenario["mock_dir"]) / "planning.json").read_text()
    )
    plan["plan"]["skip_stages"] = ["impact_analysis", "tests"]
    orch = start(custom_scenario({"planning.json": plan}))
    orch.run()
    assert statuses(orch)["impact_analysis"] == StageStatus.SKIPPED
    ev = events_of(orch, "stages_skipped")[0]["data"]
    assert ev == {"skipped": ["impact_analysis"], "refused": ["tests"]}


def test_autonomy_violation_is_blocked_and_rolled_back(start, custom_scenario):
    bad = {
        "edits": [{"path": "tests/sneaky.py", "action": "create", "content": "x"}],
        "summary": "s",
    }
    orch = start(
        custom_scenario(
            {"implementation.1.json": bad, "implementation.2.json": bad, "implementation.json": bad}
        ),
        auto_approve=True,
    )
    state = orch.run()
    assert state.status == RunStatus.FAILED
    assert statuses(orch)["implementation"] == StageStatus.FAILED
    assert len(events_of(orch, "policy_violation")) == 3  # every attempt refused
    assert not (orch.workspace.root / "tests" / "sneaky.py").exists()


def test_failing_tests_trigger_rework_of_implementation(start, custom_scenario):
    failing = {
        "edits": [
            {
                "path": "tests/integration/test_version.py",
                "action": "create",
                "content": "def test_fails():\n    assert False\n",
            }
        ],
        "summary": "s",
    }
    orch = start(custom_scenario({"tests.json": failing}), auto_approve=True, max_reworks=1)
    state = orch.run()
    assert state.status == RunStatus.FAILED
    reworks = events_of(orch, "rework")
    assert reworks and reworks[0]["data"]["cause"] in ("tests", "review")
    assert any(e["stage"] == "tests" for e in events_of(orch, "attempt_failed"))


def test_entry_gate_and_agent_errors(make_config, custom_scenario):
    from orchestrator import gates

    def graph():
        return Graph(
            [
                Stage("design", "design", entry_gate=gates.requires_artifacts("spec")),
                Stage("planning", "planning"),  # no mock response -> agent error, retried, FAILED
            ]
        )

    cfg = make_config(graph_factory=graph)
    scenario = custom_scenario(remove=("planning.json",))
    orch = Orchestrator.create(scenario, cfg, run_id="g1")
    state = orch.run()
    assert state.status == RunStatus.FAILED
    failed = {e["stage"]: e["data"] for e in events_of(orch, "stage_failed")}
    assert failed["design"]["gate"] == "entry"
    assert failed["planning"]["gate"] == "exit"
    assert "FileNotFoundError" in failed["planning"]["reasons"][0]
    assert orch.state.stages["planning"].attempts == 3
    with pytest.raises(EngineError, match="already exists"):
        Orchestrator.create(scenario, cfg, run_id="g1")
    with pytest.raises(EngineError, match="no run"):
        Orchestrator.load("missing", cfg)


def test_metrics_aggregate_across_runs(start, demo_scenario, custom_scenario, runs_dir):
    start(demo_scenario, run_id="ok", auto_approve=True).run()
    start(demo_scenario, run_id="bad", auto_approve=True, max_reworks=0).run()
    agg = aggregate(runs_dir)
    assert agg["runs"] == 2 and agg["run_success_rate"] == 0.5
    assert agg["retry_frequency"] > 0 and agg["rollback_frequency"] > 0
    assert set(agg["per_run"]) == {"ok", "bad"}
