"""The three assessment scenarios, run end to end with their scripted human steps.

Each test pins the control path the scenario exists to demonstrate.
"""

import importlib.util

import pytest

from .conftest import REPO

spec = importlib.util.spec_from_file_location("run_scenario", REPO / "scripts" / "run_scenario.py")
run_scenario_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_scenario_mod)


def run(name, runs_dir):
    orch, metrics = run_scenario_mod.run_scenario(REPO / "scenarios" / name, runs_dir, quiet=True)
    types = [e["type"] for e in orch.events.read()]
    return orch, metrics, types


def test_greenfield_skips_impact_and_enforces_autonomy_boundary(runs_dir):
    orch, m, types = run("greenfield-bulk-create", runs_dir)
    assert orch.state.stages["impact_analysis"].status.value == "skipped"
    assert m["policy_violations"] == 1  # tried to write tests/ from the implementation stage
    violation = next(e for e in orch.events.read() if e["type"] == "policy_violation")
    assert "outside this stage's allowed paths" in violation["data"]["error"]
    assert orch.state.stages["implementation"].attempts == 2
    patch = (orch.store.dir / "changes.patch").read_text()
    assert "service/api/bulk.py" in patch and "tests/integration/test_bulk.py" in patch
    assert [a["stage"] for a in orch.state.approvals] == ["design", "release"]


def test_brownfield_retries_failing_tests_and_flags_schema_change(runs_dir):
    orch, m, types = run("brownfield-click-limits", runs_dir)
    failed = [e for e in orch.events.read() if e["type"] == "attempt_failed"]
    assert [e["stage"] for e in failed] == ["tests"]
    assert "test suite failed" in failed[0]["data"]["reasons"][0]
    assert orch.state.stages["tests"].attempts == 2
    report = orch.store.get_artifact(orch.state, "policy_report")
    assert {(f["rule"], f["severity"]) for f in report["findings"]} == {
        ("change_control.schema", "approval")
    }
    assert orch.store.get_artifact(orch.state, "impact")["risk_level"] == "medium"
    assert "add_missing_columns" in (orch.store.dir / "changes.patch").read_text()


def test_ambiguous_requires_sign_off_then_replans_on_spec_change(runs_dir):
    orch, m, types = run("ambiguous-secure-faster", runs_dir)
    assert types.index("approval_requested") < types.index("approval_granted")
    first_request = next(e for e in orch.events.read() if e["type"] == "approval_requested")
    assert first_request["stage"] == "requirements"

    replan = next(e for e in orch.events.read() if e["type"] == "replan")
    assert replan["stage"] == "planning" and replan["data"]["changed_inputs"] == ["spec"]
    assert "implementation" in replan["data"]["reset"]
    assert m["replans"] == 1 and m["rollbacks"] >= 1
    assert orch.state.artifacts["spec"]["producer"].startswith("human:Priya")
    for stage in ("planning", "design", "implementation", "tests"):
        assert orch.state.stages[stage].executions == 2
    patch = (orch.store.dir / "changes.patch").read_text()
    assert "destination has been blocked" in patch  # v2 behaviour shipped, v1 rolled back
    assert "test_denylist_redirect.py" in patch


@pytest.mark.parametrize("name", ["demo-version-endpoint"])
def test_demo_scenario_still_completes(name, runs_dir):
    orch, m, _ = run(name, runs_dir)
    assert m["reworks"] == 1


def test_step_errors_are_reported(runs_dir, tmp_path):
    import shutil

    dest = tmp_path / "broken"
    shutil.copytree(REPO / "scenarios" / "greenfield-bulk-create", dest)
    text = (dest / "scenario.yaml").read_text().replace("approve: design", "approve: tests", 1)
    (dest / "scenario.yaml").write_text(text)
    with pytest.raises(run_scenario_mod.StepError, match="expected tests to await approval"):
        run_scenario_mod.run_scenario(dest, runs_dir, quiet=True)
