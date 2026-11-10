"""Scenario flow (graph.agri_scenario_graph via tools.agri_scenario_flow): stage boundaries, capability separation,
idempotent restart and the distributable reproduction. Controller/executor behaviour is tested elsewhere.

REAL: the conserved H1/H2 copies and the recorded H3b capture (read-only). SYNTHETIC: every demo run (its own
sequence identity, request keys and storage under tmp_path; TEST_DOUBLE executor). No ROS, process or model call.
"""
import json
from pathlib import Path
import shutil
import sys

import pytest

from observability.hermes_capture_run import write_manifest
from reporting import agri_scenario_summary as summary
from tools import agri_ground_coordinator as coordinator
from tools import agri_scenario_flow as flow
from tools import preflight_sequences

ROOT = Path(__file__).resolve().parents[1]
SAVED_VIEW = ROOT / "evaluation/observability/agri_scenario_view_h2_2026_10_24/scenario_view.json"
REAL_3 = ROOT / "simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728"
REAL_3_CAPTURE = "container-copies/tmp/tfg_rover_xrce_capture/4ac58516-8fad-457e-918e-253483a2d728"
NODES = ["load_artifacts", "bind_and_validate", "aerial_sequence", "scenario_view", "hermes_evidence", "r1_prepare",
         "r1_coordinate", "report"]


def _forbid_operations(monkeypatch):
    """Any reachable operation fails the test: aerial start, R1 admission/start, executor calls."""
    def forbidden(*args, **kwargs):
        raise AssertionError("operation reached from a query/report path")
    from tools import rover_ground_executor as ground
    for module, name in ((preflight_sequences, "start_preflight_sequence"), (ground, "admit_ground_trial"),
                         (ground, "start_ground_trial"), (coordinator, "request"), (coordinator, "start"),
                         (coordinator, "track")):
        monkeypatch.setattr(module, name, forbidden)
    for name in ("admit", "start", "lookup", "query"):
        monkeypatch.setattr(coordinator.RoverGroundExecutorAdapter, name, forbidden)


def test_REAL_archive_query_rebuilds_the_saved_h2_view_and_reaches_no_operation(tmp_path, monkeypatch):
    _forbid_operations(monkeypatch)
    events = []
    out = tmp_path / "query"
    final = flow.query(out_dir=out, emit=events.append, r1_root=tmp_path / "no-r1-store")
    assert final["status"] == "COMPLETED_FLOW" and [t["node"] for t in final["transitions"]] == NODES
    assert final["view"] == json.loads(SAVED_VIEW.read_text())  # same view as the one saved on 24/10
    assert final["hermes"]["origin"] == "RECORDED_CAPTURE" and final["hermes"]["inference_performed"] is False
    assert final["hermes"]["h3b_explanation"]["view_received_equals_this_view"] is True
    assert final["preparation"]["stages"]["dependency"] == "MET"
    assert final["preparation"]["blockers"] == ["required_data_present", "operational_rover_policy_enabled"]
    assert final["r1"]["state"] == "NOT_REQUESTED"
    assert final["scenario"]["scenario_complete"] is False
    assert final["scenario"]["scenario_status"] == final["view"]["scenario"]["status"] == \
        "AERIAL_COMPLETED_GROUND_PENDING"  # no R1 record: the historical status stands
    assert {e["node"] for e in events if e["event"] == "start"} == set(NODES)
    assert all("waiting_on" in e for e in events if e["event"] == "start")
    record = json.loads((out / "flow_record.json").read_text())
    assert record["origin"] == "REAL_HISTORICAL" and record["movement_authorized"] is False
    assert "# Informe determinista" in (out / "scenario_report.md").read_text()
    assert not hasattr(flow.QuerySources(), "executor")


def test_REAL_query_report_is_deterministic(tmp_path):
    first = flow.query(out_dir=tmp_path / "a", r1_root=tmp_path / "r1")
    second = flow.query(out_dir=tmp_path / "b", r1_root=tmp_path / "r1")
    assert first["report_text"] == second["report_text"]


def test_measured_facts_requested_without_the_capture_are_not_available_and_change_no_blocker(tmp_path):
    from tools.rover_passive_journal import analyze_capture
    capture = {"value": analyze_capture(tmp_path / "absent-capture", "capture"), "source": "requested, not present"}
    without = flow.query(r1_root=tmp_path)
    final = flow.query(capture=capture, r1_root=tmp_path)
    assert final["preparation"]["measured_facts"]["status"] == "NOT_AVAILABLE"
    assert final["preparation"]["blockers"] == without["preparation"]["blockers"]
    assert final["preparation"]["candidate"] is None and final["status"] == "COMPLETED_FLOW"


@pytest.mark.skipif(not REAL_3.is_dir(), reason="optional evidence: the closed /3 capture is not distributed here")
def test_REAL_query_with_the_closed_3_capture_adds_measured_facts_only(tmp_path):
    from tools.rover_passive_journal import analyze_capture
    capture = {"value": analyze_capture(REAL_3, REAL_3_CAPTURE), "source": "REAL passive capture 4ac58516 (test)"}
    final = flow.query(capture=capture, r1_root=tmp_path)
    assert final["preparation"]["measured_facts"]["status"] == "OBSERVED"
    assert final["preparation"]["blockers"] == ["required_data_present", "operational_rover_policy_enabled"]


def _copy_archive(tmp_path):
    archive = tmp_path / "archive"
    shutil.copytree(flow.ARCHIVE, archive)
    return archive


def test_tampered_archive_copy_blocks_before_any_interpretation(tmp_path):
    archive = _copy_archive(tmp_path)
    report = archive / "child_2_febf7c4f/report.json"
    report.write_text(report.read_text().replace('"PASSED"', '"FAILED"', 1))
    final = flow.query(archive=archive, r1_root=tmp_path)
    assert final["status"] == "BLOCKED" and final["stage"] == "report" and "view" not in final
    assert any("ARCHIVE_COPY_MISMATCH" in r for r in final["reasons"])


def test_local_store_absent_is_blocked_with_the_archive_as_the_reproducible_route(tmp_path):
    evidence = tmp_path / "h1"
    evidence.mkdir()
    record = json.loads(flow.BINDING_RECORD.read_text())
    for artifact in record["artifacts"].values():
        artifact["mission_path"] = "missions/generated/absent/mission.json"
    (evidence / "h1_binding.json").write_text(json.dumps(record))
    write_manifest(evidence)
    final = flow.query(source="local", binding_record=evidence / "h1_binding.json", r1_root=tmp_path)
    assert final["status"] == "BLOCKED" and "use --source archive" in final["reasons"][0]


# --- SYNTHETIC demo: stage boundaries and failures ------------------------------------------------------------

EXPECTED = {  # variant: (scenario status, R1 state, admissions)
    "complete": ("SYNTHETIC_COMPLETE", "VERIFIED_SYNTHETIC", 1),
    "first_drone_failed": ("FAILED", "NOT_REQUESTED", 0),
    "poi_not_reached": ("AERIAL_COMPLETED_R1_DEPENDENCY_NOT_MET", "NOT_REQUESTED", 0),
    "sequence_pending": ("UNKNOWN", "NOT_REQUESTED", 0),
    "transform_absent": ("AERIAL_COMPLETED_GROUND_PENDING", "NOT_REQUESTED", 0),
    "authorization_absent": ("AERIAL_COMPLETED_GROUND_PENDING", "NOT_REQUESTED", 0),
    "executor_refuses": ("AERIAL_COMPLETED_GROUND_REJECTED_BY_EXECUTOR", "REJECTED_BY_EXECUTOR", 1),
    "insufficient_dwell": ("AERIAL_COMPLETED_GROUND_FAILED", "FAILED", 1),
    "stop_uncertain": ("AERIAL_COMPLETED_GROUND_UNCERTAIN", "UNCERTAIN", 1),
    "lost_admission_response": ("SYNTHETIC_COMPLETE", "VERIFIED_SYNTHETIC", 1),
}


def _admissions(out):
    path = Path(out) / "executor_test_double.json"
    return json.loads(path.read_text())["admit_calls"] if path.is_file() else 0


@pytest.mark.parametrize("variant", sorted(EXPECTED))
def test_SYNTHETIC_demo_variant_ends_where_its_stage_boundary_says(tmp_path, variant):
    status, r1_state, admissions = EXPECTED[variant]
    final = flow.run_demo(variant, tmp_path / variant)
    assert final["status"] == "COMPLETED_FLOW" and final["origin"] == "SYNTHETIC"
    assert final["scenario"]["scenario_status"] == status and final["r1"]["state"] == r1_state
    assert final["scenario"]["scenario_complete"] is False  # a synthetic demo never completes a scenario
    assert _admissions(tmp_path / variant) == admissions
    assert final["view"]["scenario"]["sequence"]["sequence_id"] != summary.H2_REQUEST_KEY
    assert final["hermes"]["origin"] == "SUBSTITUTED"
    if variant == "authorization_absent":  # dependency MET without authorization: no admission
        assert final["preparation"]["stages"]["dependency"] == "MET"
        assert final["r1"]["reason"] == "AUTHORIZATION_ABSENT_OR_MALFORMED"
    if variant == "transform_absent":
        assert "frame_transform" in final["preparation"]["missing_data"]
    if variant == "lost_admission_response":  # recovered by lookup, never re-admitted
        assert final["r1"]["request_status"] == "UNCONFIRMED"
        history = [h["state"] for h in final["r1"]["record"]["history"]]
        assert history[:3] == ["ADMISSION_REQUESTED", "ADMISSION_UNCONFIRMED", "ADMITTED"]


@pytest.mark.parametrize("variant,reason", [("invalid_mission", "validation error"),
                                            ("artifact_modified", "differs from the recorded hash")])
def test_SYNTHETIC_rejected_artifact_stops_before_the_aerial_stage(tmp_path, variant, reason):
    final = flow.run_demo(variant, tmp_path / variant)
    assert final["status"] == "REJECTED" and [t["node"] for t in final["transitions"]] == NODES[:2] + ["report"]
    assert reason in final["reasons"][0] and _admissions(tmp_path / variant) == 0


@pytest.mark.parametrize("variant", ["complete", "insufficient_dwell", "stop_uncertain", "executor_refuses"])
def test_SYNTHETIC_rerun_never_repeats_an_operation_nor_retries_failed_or_uncertain(tmp_path, variant):
    out = tmp_path / variant
    first = flow.run_demo(variant, out)
    executor_before = json.loads((out / "executor_test_double.json").read_text())
    with pytest.raises(FileExistsError):
        flow.run_demo(variant, out)  # a new run needs a new directory
    again = flow.run_demo(variant, out, resume=True)
    assert again["r1"]["request_status"] == "EXISTING" and again["r1"]["state"] == first["r1"]["state"]
    assert json.loads((out / "executor_test_double.json").read_text()) == executor_before  # no admit, no query


def test_SYNTHETIC_flow_interrupted_after_admission_resumes_without_a_second_admission(tmp_path, monkeypatch):
    out = tmp_path / "interrupted"
    original = coordinator.track
    monkeypatch.setattr(coordinator, "track", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        flow.run_demo("complete", out)
    assert _admissions(out) == 1
    assert json.loads((out / "flow_record.json").read_text())["stage"] == "r1_prepare"  # last persisted stage
    monkeypatch.setattr(coordinator, "track", original)
    final = flow.run_demo("complete", out, resume=True)
    assert final["r1"]["state"] == "VERIFIED_SYNTHETIC" and _admissions(out) == 1


# --- Interactive entry ------------------------------------------------------------------------------------------

def _script(*answers):
    answers = list(answers)

    def read(prompt=""):
        if not answers:
            raise EOFError
        return answers.pop(0)
    return read


def test_interactive_menu_exits_returns_and_runs_both_modes(tmp_path):
    lines = []
    assert flow.run_interactive(_script("exit"), lines.append) is False
    assert flow.run_interactive(_script(), lines.append) is False  # EOF / Ctrl+D closes
    assert flow.run_interactive(_script("1", "menu"), lines.append) is True
    assert any(line.startswith("[ESCENARIO agri_demo_001] origen: REAL_HISTORICAL") for line in lines)
    assert flow.run_interactive(_script("2", "stop_uncertain", str(tmp_path / "demo"), "4"), lines.append) is True
    assert any("R1: UNCERTAIN" in line for line in lines)
    assert any(str(tmp_path / "demo" / "scenario_report.md") in line for line in lines)


def test_reports_open_with_their_origin_so_sessions_are_never_merged(tmp_path):
    real = flow.query(r1_root=tmp_path)["report_text"]
    synthetic = flow.run_demo("complete", tmp_path / "demo")["report_text"]
    assert real.startswith("> **Origen: REAL HISTÓRICO.**")
    assert synthetic.startswith("> **Origen: SINTÉTICO (demostración offline).**") and "REIDENTIFICADA" in synthetic


# --- State dimensions: the conserved H2 and synthetic records never contradict each other ----------------------

def test_REAL_h2_dimensions_keep_the_historical_view_and_mix_nothing(tmp_path):
    final = flow.query(r1_root=tmp_path)
    d = final["r1_dimensions"]
    view_task = final["view"]["scenario"]["ground_task"]
    assert d["dependency"] == "MET" and view_task["dependency"] == "MET"
    assert d["eligibility"]["historical_view"] == {"status": "BLOCKED_PENDING", "barriers": view_task["barriers"]}
    assert len(d["eligibility"]["historical_view"]["barriers"]) == 4
    assert d["eligibility"]["this_preparation"]["eligibility"] == "NOT_ELIGIBLE"
    assert d["authorization"] == "ABSENT" and d["request"]["status"] == "NOT_REQUESTED_VIA_THIS_COORDINATOR"
    assert "proves no eligibility and removes no blocker" in d["request"]["meaning"]
    assert d["execution"] == {"status": "NOT_STARTED"}
    assert d["completeness"] == {"scenario_status": "AERIAL_COMPLETED_GROUND_PENDING", "scenario_complete": False,
                                 "synthetic_complete": False}
    saved = json.loads(SAVED_VIEW.read_text())["scenario"]  # the historical result itself is unchanged
    assert (saved["status"], saved["ground_task"]["status"]) == ("AERIAL_COMPLETED_GROUND_PENDING", "BLOCKED_PENDING")


@pytest.mark.parametrize("variant,request_status,authorization,acceptance,complete", [
    ("complete", "VERIFIED_SYNTHETIC", "DECLARED_NOT_AUTHENTICATED", "VERIFIED", (False, True)),
    ("stop_uncertain", "UNCERTAIN", "DECLARED_NOT_AUTHENTICATED", "UNCERTAIN", (False, False)),
    ("authorization_absent", "NOT_REQUESTED_VIA_THIS_COORDINATOR", "ABSENT", None, (False, False)),
    ("executor_refuses", "REJECTED_BY_EXECUTOR", "DECLARED_NOT_AUTHENTICATED", None, (False, False)),
])
def test_SYNTHETIC_dimensions_are_reported_separately(tmp_path, variant, request_status, authorization,
                                                      acceptance, complete):
    d = flow.run_demo(variant, tmp_path / variant)["r1_dimensions"]
    assert d["dependency"] == "MET" and d["request"]["status"] == request_status
    assert d["authorization"] == authorization
    assert d["execution"].get("acceptance") == acceptance
    if variant in ("authorization_absent", "executor_refuses"):
        assert d["execution"] == {"status": "NOT_STARTED"}
    assert (d["completeness"]["scenario_complete"], d["completeness"]["synthetic_complete"]) == complete


# --- Public entry: usage and recovery -------------------------------------------------------------------------

def test_existing_output_directories_are_refused_by_the_cli(tmp_path, capsys):
    (tmp_path / "q").mkdir()
    assert flow.main(["query", "--out", str(tmp_path / "q")]) == 2
    assert flow.main(["demo", "--variant", "complete", "--out", str(tmp_path / "q")]) == 2
    assert list((tmp_path / "q").iterdir()) == []  # nothing written into it
    (tmp_path / "foreign").mkdir()
    (tmp_path / "foreign" / "notes.txt").write_text("someone else's file")
    assert flow.main(["demo", "--out", str(tmp_path / "foreign"), "--resume"]) == 2  # no recorded flow there
    assert "NO_OUTPUTS_MANIFEST" in capsys.readouterr().err


def test_resume_with_another_identity_is_refused_without_any_admission(tmp_path, capsys):
    out = str(tmp_path / "demo")
    assert flow.main(["demo", "--variant", "complete", "--out", out]) == 0
    before = (tmp_path / "demo" / "executor_test_double.json").read_bytes()
    assert flow.main(["demo", "--variant", "stop_uncertain", "--out", out, "--resume"]) == 2
    assert "IDENTITY_MISMATCH" in capsys.readouterr().err
    assert (tmp_path / "demo" / "executor_test_double.json").read_bytes() == before


@pytest.mark.parametrize("name", ["flow_record.json", "executor_test_double.json", "scenario_report.md", "r1"])
def test_altered_derived_files_refuse_resume(tmp_path, capsys, name):
    out = tmp_path / "demo"
    assert flow.main(["demo", "--out", str(out)]) == 0
    target = next(p for p in sorted((out / name).rglob("*.json"))) if name == "r1" else out / name
    target.write_text(target.read_text() + " ")
    assert flow.main(["demo", "--out", str(out), "--resume"]) == 2
    assert "DERIVED_FILES_ALTERED" in capsys.readouterr().err


def test_interrupted_cli_run_resumes_once_with_the_same_admission(tmp_path, monkeypatch, capsys):
    out = tmp_path / "demo"
    original = coordinator.track
    monkeypatch.setattr(coordinator, "track", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert flow.main(["demo", "--out", str(out)]) == 130
    assert "--resume" in capsys.readouterr().err and _admissions(out) == 1
    assert json.loads((out / flow.OUTPUTS_MANIFEST).read_text())["state"] == "IN_PROGRESS"
    monkeypatch.setattr(coordinator, "track", original)
    assert flow.main(["demo", "--out", str(out), "--resume"]) == 0
    assert "Reanudado tras una interrupción" in capsys.readouterr().out and _admissions(out) == 1
    assert json.loads((out / flow.OUTPUTS_MANIFEST).read_text())["state"] == "FINISHED"


@pytest.mark.parametrize("profile", ["offline", None])
def test_main_menu_marks_llm_and_store_options_unavailable_only_in_the_offline_profile(monkeypatch, capsys, profile):
    import main as entry
    if profile:
        monkeypatch.setenv("TFG_PROFILE", profile)
    else:
        monkeypatch.delenv("TFG_PROFILE", raising=False)
    called = []
    for name in ("run_natural_language_mission", "run_json_mission", "run_ai_mission_planner",
                 "run_qgroundcontrol_mission"):
        monkeypatch.setattr(entry, name, lambda name=name: called.append(name) or True)
    answers = iter(["1", "2", "3", "4", "6"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    entry.main()
    out = capsys.readouterr().out
    if profile:
        assert called == [] and out.count("[NOT AVAILABLE:") == 4 * 5  # menu printed before each choice
        assert "Option 1 is not available here: not part of the student distribution" in out
        assert "Option 4 is not available here: saves the session under missions/generated" in out
        assert "AI planning is the separate Hermes service" in out and "5. Agricultural scenario" in out
        assert "ollama" not in out.lower()
    else:
        assert len(called) == 4 and "NOT AVAILABLE" not in out


def test_disk_full_leaves_a_partial_tmp_that_is_never_consumed_and_resume_is_safe(tmp_path, monkeypatch, capsys):
    out = tmp_path / "demo"
    original_write = Path.write_text
    calls = {"n": 0}

    def full_disk(self, data, *args, **kwargs):
        if self.name == "flow_record.tmp":
            calls["n"] += 1
            if calls["n"] >= 3:  # after admission-free stages persisted twice: truncated temp, then ENOSPC
                with open(self, "w", encoding="utf-8") as handle:
                    handle.write(data[:10])
                raise OSError(28, "No space left on device")
        return original_write(self, data, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", full_disk)
    assert flow.main(["demo", "--out", str(out)]) == 4
    assert "NOT marked finished" in capsys.readouterr().err
    assert (out / "flow_record.tmp").read_text() != "" and json.loads((out / "flow_record.json").read_text())
    assert json.loads((out / flow.OUTPUTS_MANIFEST).read_text())["state"] == "IN_PROGRESS"  # never FINISHED
    admissions = _admissions(out) if (out / "executor_test_double.json").exists() else 0
    capsys.readouterr()
    monkeypatch.setattr(Path, "write_text", original_write)
    assert flow.main(["demo", "--out", str(out), "--resume"]) == 0
    manifest = json.loads((out / flow.OUTPUTS_MANIFEST).read_text())
    assert manifest["state"] == "FINISHED" and not any(name.endswith(".tmp") for name in manifest["files"])
    assert not (out / "flow_record.tmp").exists()  # the next successful write replaced it
    assert json.loads((out / "flow_record.json").read_text())["stage"] == "report"
    assert _admissions(out) == max(admissions, 1)


def test_report_write_failure_is_an_error_not_a_completed_flow(tmp_path, monkeypatch, capsys):
    import graph.agri_scenario_graph as scenario_graph

    def refuse(*args, **kwargs):
        raise PermissionError("read-only output")
    monkeypatch.setattr(scenario_graph, "_write_report", refuse)
    assert flow.main(["query", "--out", str(tmp_path / "q")]) == 3
    captured = capsys.readouterr().out
    assert "Estado del flujo: ERROR" in captured and "REPORT_NOT_WRITTEN" in captured
    record = json.loads((tmp_path / "q" / "flow_record.json").read_text())
    assert record["status"] == "ERROR" and record["report_path"] is None


def test_a_different_previous_report_is_kept_never_silently_overwritten(tmp_path):
    from graph.agri_scenario_graph import _write_report
    (tmp_path / "scenario_report.md").write_text("old")
    result = _write_report(tmp_path, "new")
    assert Path(result["previous_report_kept"]).read_text() == "old"
    assert (tmp_path / "scenario_report.md").read_text() == "new"
    assert _write_report(tmp_path, "new")["previous_report_kept"] is None  # identical: nothing to keep


def test_menu_cancellation_at_prompts_and_during_a_run(tmp_path, monkeypatch):
    lines = []
    assert flow.run_interactive(_script("2", "exit"), lines.append) is False  # at the variant prompt

    def interrupted(prompt=""):
        raise KeyboardInterrupt
    assert flow.run_interactive(interrupted, lines.append) is False
    monkeypatch.setattr(flow, "query", lambda **kw: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert flow.run_interactive(_script("1"), lines.append) is False
    assert lines[-1].strip().startswith("Interrupted. Durable records are kept")


# --- Distributable inventory ----------------------------------------------------------------------------------

def test_distribution_inventory_verifies_and_detects_changes(tmp_path):
    from tools import agri_scenario_distribution as dist
    inventory = dist.build_inventory()
    assert dist.check_inventory(inventory) == []
    assert [e["path"] for e in inventory["entries"] if not e["required"]] == [e[0] for e in dist.ENTRIES[-2:]]  # /3, identity
    paths = [e["path"] for e in inventory["entries"]]
    assert not any(p.startswith(dist.FORBIDDEN_PREFIXES) for p in paths)
    assert {e["manifest"] for e in inventory["entries"] if e["type"] == "directory"} <= set(dist.MANIFESTS)
    changed = json.loads(json.dumps(inventory))
    changed["entries"][1]["sha256"] = "0" * 64
    changed["entries"].append({"path": "missions/generated/x.json", "type": "file", "size_bytes": 0, "sha256": ""})
    problems = dist.check_inventory(changed)
    assert f"CHANGED: {paths[1]}" in problems and "FORBIDDEN_PATH: missions/generated/x.json" in problems


def test_app_image_set_is_the_import_closure_and_matches_the_build_allowlist(tmp_path):
    from tools import agri_scenario_distribution as dist
    root = Path(dist.__file__).resolve().parents[1]
    files = dist.module_closure()
    assert {"main.py", "tools/agri_scenario_flow.py", "tools/scenario_package.py", "tools/qgc_plan_compare.py",
            "reporting/agri_experiment_comparison.py", "graph/agri_scenario_graph.py"} <= set(files)
    assert not any(f.startswith("tests/") for f in files)
    assert (root / "deploy/app/Dockerfile.dockerignore").read_text(encoding="utf-8") == dist.dockerignore_text()
    inventory = dist.build_inventory(entry_set="app_image")
    assert dist.check_inventory(inventory) == []
    kept = {line[1:] for line in dist.dockerignore_text().splitlines() if line.startswith("!")}
    assert not any(e["path"] in kept for e in inventory["entries"] if not e["required"])  # optional captures out
    # relative imports resolve inside a package; third-party and missing modules are not followed
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/__init__.py").write_text("")
    (tmp_path / "pkg/a.py").write_text("from . import b\nfrom .c import f\nimport rclpy\n")
    (tmp_path / "pkg/b.py").write_text("")
    (tmp_path / "pkg/c.py").write_text("def f():\n    from pkg import d\n")
    (tmp_path / "pkg/d.py").write_text("")
    (tmp_path / "pkg/unused.py").write_text("")
    assert dist.module_closure(tmp_path, ("pkg.a",)) == ["pkg/__init__.py", "pkg/a.py", "pkg/b.py", "pkg/c.py",
                                                         "pkg/d.py"]


def test_app_image_entry_turns_an_unhandled_early_ctrl_c_into_130_and_passes_exit_codes(tmp_path, monkeypatch,
                                                                                       capsys):
    import importlib.util
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("app_entry", root / "deploy/app/entry.py")
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    (tmp_path / "slow_import.py").write_text("raise KeyboardInterrupt  # Ctrl+C while modules load\n")
    assert entry.main(["-m", "slow_import"]) == 130
    assert "Interrupted (Ctrl+C) before the program could handle it" in capsys.readouterr().err
    (tmp_path / "exits.py").write_text("import sys\nsys.exit(3)\n")
    with pytest.raises(SystemExit) as exited:
        entry.main(["-m", "exits"])
    assert exited.value.code == 3
    assert entry.main(["-c", "import sys; assert sys.argv == ['-c', 'x']", "x"]) == 0
    assert entry.main([]) == 2


def test_distribution_check_detects_a_tampered_evidence_copy(tmp_path):
    from tools import agri_scenario_distribution as dist
    archive = _copy_archive(tmp_path)
    (archive / "sequence/plan.json").write_text("{}")
    assert dist._manifest_problems(archive, "SHA256SUMS") == ["archive: sequence/plan.json"]
