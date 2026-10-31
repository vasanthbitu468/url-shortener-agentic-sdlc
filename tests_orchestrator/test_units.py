"""Unit tests: graph, audit log, workspace, policies, gates, LLM, scenario loading."""

import json
import subprocess

import pytest

from orchestrator import gates, policies
from orchestrator.events import EventLog, verify_chain
from orchestrator.gates import GateInput
from orchestrator.graph import Graph, GraphError, Stage
from orchestrator.llm import MockLLM, build_llm, extract_json
from orchestrator.models import PolicyViolation, TransientError, content_hash
from orchestrator.pipeline import default_pipeline
from orchestrator.scenario import ScenarioError, load_scenario
from orchestrator.workspace import Edit, Workspace

# ---- graph ---------------------------------------------------------------------------------


def test_default_pipeline_shape():
    g = default_pipeline()
    assert g.levels() == [
        ["requirements"],
        ["planning"],
        ["impact_analysis"],
        ["design"],
        ["implementation"],
        ["tests", "docs"],
        ["review"],
        ["release"],
    ]
    assert g.descendants("implementation") == {"tests", "docs", "review", "release"}
    assert g.ancestors("review") >= {"tests", "docs", "implementation", "requirements"}
    assert list(g) == g.order and g["review"].depends_on == ("tests", "docs")


def test_graph_rejects_cycles_unknown_deps_duplicates_and_bad_rework():
    with pytest.raises(GraphError, match="cycle"):
        Graph([Stage("a", "x", depends_on=("b",)), Stage("b", "x", depends_on=("a",))])
    with pytest.raises(GraphError, match="unknown stage"):
        Graph([Stage("a", "x", depends_on=("zzz",))])
    with pytest.raises(GraphError, match="duplicate"):
        Graph([Stage("a", "x"), Stage("a", "x")])
    with pytest.raises(GraphError, match="upstream"):
        Graph([Stage("a", "x", rework_target="b"), Stage("b", "x", depends_on=("a",))])


# ---- audit log -----------------------------------------------------------------------------


def test_event_log_hash_chain_detects_tampering(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    for i in range(3):
        log.emit("tick", run_id="r", n=i)
    events = list(log.read())
    assert verify_chain(events) == []
    assert EventLog(tmp_path / "e.jsonl")._seq == 3  # resumes the chain on reopen

    tampered = [dict(e) for e in events]
    tampered[1]["data"] = {"n": 99}
    assert any("modified" in p for p in verify_chain(tampered))
    assert any("prev_hash" in p or "sequence" in p for p in verify_chain([events[0], events[2]]))


# ---- workspace -----------------------------------------------------------------------------


@pytest.fixture
def ws(tmp_path):
    repo = tmp_path / "repo"
    (repo / "service").mkdir(parents=True)
    (repo / "service" / "a.py").write_text("x = 1\n")
    (repo / "tests").mkdir()
    (repo / "README.md").write_text("hi\n")
    w = Workspace(tmp_path / "run")
    w.create_from(repo)
    return w


def test_apply_create_replace_delete_and_diff(ws, tmp_path):
    changed = ws.apply(
        [
            Edit("service/b.py", "create", content="y = 2\n"),
            Edit("service/a.py", "replace", find="x = 1", replace="x = 3"),
        ],
        ("service",),
    )
    assert changed == ["service/a.py", "service/b.py"]
    ws.apply([Edit("README.md", "delete")], ("README.md",))
    assert ws.changed_files() == {
        "README.md": "deleted",
        "service/a.py": "modified",
        "service/b.py": "added",
    }
    patch = ws.diff()
    assert "new file mode" in patch and "deleted file mode" in patch

    # the patch applies to a git copy of the baseline
    target = tmp_path / "gitcopy"
    import shutil

    shutil.copytree(ws.baseline, target)
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    (target / "p.patch").write_text(patch)
    subprocess.run(["git", "apply", "p.patch"], cwd=target, check=True)
    assert (target / "service" / "a.py").read_text() == "x = 3\n"
    assert not (target / "README.md").exists()


def test_apply_enforces_scope_and_paths(ws):
    with pytest.raises(PolicyViolation, match="outside"):
        ws.apply([Edit("tests/t.py", "create", content="")], ("service",))
    with pytest.raises(PolicyViolation, match="escapes"):
        ws.apply([Edit("../evil.py", "create", content="")], ("service",))
    with pytest.raises(PolicyViolation, match="escapes"):
        ws.apply([Edit("/etc/passwd", "create", content="")], ("service",))


def test_apply_is_atomic_and_strict(ws):
    with pytest.raises(ValueError, match="exactly once"):
        ws.apply(
            [
                Edit("service/new.py", "create", content="z"),
                Edit("service/a.py", "replace", find="nope"),
            ],
            ("service",),
        )
    assert not (ws.root / "service" / "new.py").exists()  # nothing was written
    with pytest.raises(ValueError, match="missing file"):
        ws.apply([Edit("service/none.py", "replace", find="a")], ("service",))
    with pytest.raises(ValueError, match="unknown edit"):
        ws.apply([Edit("service/a.py", "rename")], ("service",))


def test_checkpoint_and_scoped_restore(ws):
    ws.checkpoint("cp1")
    ws.apply([Edit("service/a.py", "create", content="broken")], ("service",))
    (ws.root / "tests" / "t.py").write_text("keep")
    ws.restore("cp1", ("service",))
    assert ws.read("service/a.py") == "x = 1\n"
    assert (ws.root / "tests" / "t.py").exists()  # other scopes untouched
    ws.restore("cp1")
    assert not (ws.root / "tests" / "t.py").exists()
    with pytest.raises(FileNotFoundError):
        ws.restore("missing")


def test_compile_check_and_run(ws):
    ws.apply([Edit("service/bad.py", "create", content="def (:\n")], ("service",))
    assert ws.compile_check(["service/bad.py", "service/a.py"])[0].startswith("service/bad.py")
    assert ws.python("-c", "print('hi')").output.strip() == "hi"
    assert ws.python("-c", "import time; time.sleep(5)", timeout=0.5).returncode == 124
    assert "service/a.py" in ws.list_files()


# ---- policies ------------------------------------------------------------------------------


def cs(changed=None, added=None, lines=10, design=None):
    return policies.ChangeSet(changed or {}, added or {}, lines, design or {})


def rules(findings):
    return {(f.rule, f.severity) for f in findings}


def test_policy_secrets_pii_paths_deps_size():
    found = policies.evaluate(
        cs(
            changed={
                "service/x.py": "added",
                "tests/t.py": "added",
                ".github/workflows/ci.yml": "modified",
                "pyproject.toml": "modified",
            },
            added={
                "service/x.py": [
                    'KEY = "sk-live-abcdefghijklmnop1234"',
                    "AKIAABCDEFGHIJKLMNOP",
                    'password = "hunter2hunter2"',
                    "-----BEGIN RSA PRIVATE KEY-----",
                    "db.add(Click(ip=request.client.host))",
                ]
            },
            lines=900,
        )
    )
    r = rules(found)
    assert ("security.no_secrets", "block") in r
    assert ("compliance.no_pii", "block") in r
    assert ("change_control.protected_paths", "block") in r
    assert ("change_control.dependencies", "approval") in r
    assert ("change_control.diff_size", "block") in r
    assert sum(f.rule == "security.no_secrets" for f in found) == 4


def test_policy_contract_schema_and_tests():
    undeclared = rules(
        policies.evaluate(
            cs(
                changed={"service/openapi.json": "modified", "service/db/models.py": "modified"},
                design={"api_changes": False, "data_model_changes": False},
            )
        )
    )
    assert ("change_control.api_contract", "block") in undeclared
    assert ("change_control.schema", "block") in undeclared
    assert ("quality.tests_required", "block") in undeclared

    declared = rules(
        policies.evaluate(
            cs(
                changed={"service/db/models.py": "modified", "tests/t.py": "added"},
                design={"api_changes": True, "data_model_changes": True},
            )
        )
    )
    assert ("change_control.schema", "approval") in declared
    assert ("change_control.api_contract", "warn") in declared
    assert not any(sev == "block" for _, sev in declared)


# ---- gates ---------------------------------------------------------------------------------


def g(outputs, artifacts=None):
    return GateInput(outputs=outputs, artifact=(artifacts or {}).get, scenario={})


def test_gates():
    assert not gates.requires_artifacts("spec")(g({})).passed
    assert gates.requires_artifacts("spec")(g({}, {"spec": {}})).passed

    assert not gates.spec_is_complete(g({"spec": {"ambiguities": [{"question": "q"}]}})).passed
    assert gates.spec_is_complete(g({"spec": {"title": "t", "acceptance_criteria": ["a"]}})).passed

    assert not gates.plan_is_valid(g({"plan": {}})).passed
    bad = {
        "tasks": [
            {"id": "a", "depends_on": ["b"]},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["z"]},
        ]
    }
    reasons = gates.plan_is_valid(g({"plan": bad})).reasons
    assert any("cycle" in r for r in reasons) and any("unknown task z" in r for r in reasons)

    assert not gates.impact_is_grounded(g({"impact": {}})).passed
    ghost = {"modules": [{"path": "nope.py"}], "_known_files": ["service/a.py"]}
    assert not gates.impact_is_grounded(g({"impact": ghost})).passed

    assert len(gates.design_is_complete(g({"design": {"api_changes": "yes"}})).reasons) == 5
    impl = {"implementation": {"compile_errors": ["x"], "openapi_error": "boom"}}
    assert len(gates.implementation_applied(g(impl)).reasons) == 3
    assert len(gates.tests_pass(g({"test_report": {}})).reasons) == 2
    assert not gates.docs_written(g({})).passed
    pr = {
        "policy_report": {
            "findings": [{"rule": "r", "severity": "block", "message": "m"}],
            "lint_errors": "E1",
        }
    }
    assert len(gates.policies_pass(g(pr)).reasons) == 2
    assert not gates.release_ready(g({"release": {}})).passed
    assert gates.always({}) and not gates.approve_if_ambiguous({"spec": {}})


# ---- llm + scenario ------------------------------------------------------------------------


def test_mock_llm_sequencing(tmp_path):
    (tmp_path / "s.json").write_text('{"v": "default"}')
    (tmp_path / "s.2.json").write_text('{"v": "second"}')
    llm = MockLLM(tmp_path)
    assert [llm.complete("s", "", i)["v"] for i in (1, 2, 3)] == ["default", "second", "default"]
    with pytest.raises(FileNotFoundError):
        llm.complete("other", "", 1)
    assert build_llm("mock", tmp_path).name == "mock"
    with pytest.raises(ValueError):
        build_llm("gpt", tmp_path)


def test_extract_json():
    assert extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('noise {"a": {"b": 2}} trailing') == {"a": {"b": 2}}
    with pytest.raises(TransientError):
        extract_json("no json here")
    with pytest.raises(TransientError):
        extract_json("[1, 2]")


def test_scenario_loading(tmp_path, demo_scenario):
    assert demo_scenario["type"] == "brownfield" and demo_scenario["faults"] == {"docs": 1}
    f = tmp_path / "scenario.yaml"
    f.write_text("name: x\ntype: weird\nrequirement: r\n")
    with pytest.raises(ScenarioError, match="type"):
        load_scenario(f)
    f.write_text("name: x\n")
    with pytest.raises(ScenarioError, match="missing"):
        load_scenario(tmp_path)
    with pytest.raises(ScenarioError, match="not found"):
        load_scenario(tmp_path / "nope")


def test_content_hash_is_stable():
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})
    assert json.dumps(content_hash([1]))
