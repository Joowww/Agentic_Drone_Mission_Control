"""Offline detached-job orchestration: Popen, flight and readiness are doubles."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

import graph.virtual_preflight_graph as graph
import tools.vehicle_execution_lock as vehicle
import tools.virtual_preflight as workflow
import tools.virtual_preflight_jobs as jobs
import tools.virtual_preflight_worker as worker

EXAMPLE = Path(__file__).resolve().parents[1] / "missions/examples/simulation_navigation_3waypoint.json"
HISTORICAL = "d4519cab-ebd1-4359-b547-44be38294a6a"


@pytest.fixture
def admitted(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "RUN_ROOT", tmp_path / "runs")
    source = tmp_path / "input.json"
    source.write_bytes(EXAMPLE.read_bytes())
    spawned = Mock(return_value=SimpleNamespace(pid=os.getpid()))
    monkeypatch.setattr(jobs.subprocess, "Popen", spawned)
    monkeypatch.setattr(graph, "check_simulation_ready", Mock(side_effect=AssertionError("No real readiness")))
    monkeypatch.setattr(graph, "execute_approved_mission", Mock(side_effect=AssertionError("No real flight")))
    return source, spawned


def begin(admitted, key="joel-test-1"):
    return jobs.start_virtual_preflight(str(admitted[0]), key)


def run_admitted(result, admitted):
    token = admitted[1].call_args.args[0][-1]
    return worker.run_worker(result["run_id"], token)


def tree_bytes(root):
    return {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def persist_typed_stub(directory, report, selection, digest):
    """Synthetic worker reports obey the new identity contract, without a flight."""
    content = (directory / "input.json").read_bytes()
    (directory / "mission.json").write_bytes(content)
    mission = json.loads(content)
    report.update(schema_version="1.1", vehicle_selection=selection,
                  mission_identity={"mission_id": mission["mission_id"], "name": mission["name"], **selection},
                  mission_sha256=digest)
    raw = report.get("executor_result")
    if isinstance(raw, dict):
        raw.update(vehicle=selection["simulated_vehicle"], vehicle_id=selection["vehicle_id"],
                   mission_id=mission["mission_id"])
    vehicle.atomic_json(directory / "report.json", report)
    return report


def test_start_returns_without_running_workflow_and_detaches_stdio(admitted, monkeypatch):
    invoked = Mock(side_effect=AssertionError("Admission must not run the workflow"))
    monkeypatch.setattr(workflow, "run_preflight_in_directory", invoked)
    result = begin(admitted)
    assert result["admission_status"] == "ACCEPTED"
    assert result["job_state"] == "STARTING" and result["result_status"] is None
    assert result["run_id"] and result["mission_sha256"] == hashlib.sha256(admitted[0].read_bytes()).hexdigest()
    assert Path(result["paths"]["input_path"]).read_bytes() == admitted[0].read_bytes()
    assert Path(result["paths"]["job_path"]).exists()
    invoked.assert_not_called()
    call = admitted[1].call_args
    assert call.args[0][:3] == [jobs.sys.executable, "-m", "tools.virtual_preflight_worker"]
    assert call.kwargs["stdin"] == jobs.subprocess.DEVNULL
    assert call.kwargs["stderr"] == jobs.subprocess.STDOUT
    assert call.kwargs["start_new_session"] and call.kwargs["close_fds"]
    assert call.kwargs["stdout"].name == result["paths"]["worker_log_path"]


def test_query_by_key_and_id_are_read_only_and_never_start(admitted):
    result = begin(admitted)
    before = tree_bytes(jobs.RUN_ROOT), tree_bytes(vehicle.LOCK_ROOT)
    by_id = jobs.get_virtual_preflight(run_id=result["run_id"])
    by_key = jobs.get_virtual_preflight(request_key="joel-test-1")
    assert by_id == by_key
    assert by_id["worker_alive"] is True and by_id["job_state"] == "STARTING"
    assert by_id["phase"] == "worker_starting" and by_id["report"] is None
    assert before == (tree_bytes(jobs.RUN_ROOT), tree_bytes(vehicle.LOCK_ROOT))
    admitted[1].assert_called_once()


def test_same_key_never_spawns_twice_and_changed_mission_is_conflict(admitted):
    first = begin(admitted)
    assert begin(admitted)["admission_status"] == "EXISTING"
    admitted[0].write_text("{}")
    conflict = begin(admitted)
    assert conflict["admission_status"] == "REQUEST_CONFLICT"
    assert conflict["run_id"] == first["run_id"] and not conflict["spawned"]
    admitted[1].assert_called_once()


def test_different_key_cannot_reserve_busy_v1(admitted):
    first = begin(admitted)
    second = begin(admitted, "other-request")
    assert second["admission_status"] == "VEHICLE_BUSY"
    assert second["job_state"] == "REJECTED" and not second["spawned"]
    assert vehicle.restriction()["owner_id"] == first["run_id"]
    admitted[1].assert_called_once()


def test_concurrent_same_key_is_one_admission(admitted):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: begin(admitted), range(2)))
    assert results[0]["run_id"] == results[1]["run_id"]
    assert {r["admission_status"] for r in results} == {"ACCEPTED", "EXISTING"}
    admitted[1].assert_called_once()


def test_concurrent_different_keys_cannot_admit_two_workers(admitted):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda key: begin(admitted, key), ("one", "two")))
    assert {r["admission_status"] for r in results} == {"ACCEPTED", "VEHICLE_BUSY"}
    admitted[1].assert_called_once()


def test_reload_recovers_job_and_key_without_spawn(admitted, monkeypatch):
    result = begin(admitted)
    root = jobs.RUN_ROOT
    importlib.reload(jobs)
    monkeypatch.setattr(jobs, "RUN_ROOT", root)
    status = jobs.get_virtual_preflight(request_key="joel-test-1")
    assert status["run_id"] == result["run_id"] and status["job_state"] == "STARTING"
    assert begin(admitted)["admission_status"] == "EXISTING"
    admitted[1].assert_called_once()


def test_missing_worker_is_interrupted_without_release_or_restart(admitted, monkeypatch):
    result = begin(admitted)
    before = tree_bytes(vehicle.LOCK_ROOT)
    monkeypatch.setattr(jobs, "identity_alive", lambda identity: False)
    status = jobs.get_virtual_preflight(run_id=result["run_id"])
    assert status["job_state"] == "INTERRUPTED"
    assert status["result_status"] is None and status["worker_alive"] is False
    assert status["vehicle_restriction"]["owner_id"] == result["run_id"]
    assert tree_bytes(vehicle.LOCK_ROOT) == before
    assert begin(admitted)["spawned"] is False
    assert begin(admitted, "new-request")["admission_status"] == "VEHICLE_BUSY"
    admitted[1].assert_called_once()


def test_recycled_pid_is_not_a_live_worker(admitted, monkeypatch):
    result = begin(admitted)
    old = result["worker"]
    monkeypatch.setattr(vehicle, "process_identity", lambda pid=None: {**old, "start_ticks": old["start_ticks"] + 1})
    assert jobs.get_virtual_preflight(run_id=result["run_id"])["job_state"] == "INTERRUPTED"
    assert vehicle.restriction() is not None


def test_spawn_failure_retains_identity_key_and_restriction(admitted):
    admitted[1].side_effect = OSError("spawn failed")
    result = begin(admitted)
    assert result["run_id"] and result["job_state"] == "UNCONFIRMED"
    assert jobs.get_virtual_preflight(request_key="joel-test-1")["run_id"] == result["run_id"]
    assert vehicle.restriction()["owner_id"] == result["run_id"]
    assert begin(admitted)["admission_status"] == "EXISTING"
    admitted[1].assert_called_once()


@pytest.mark.parametrize("run_id", ["../outside", "/tmp/report.json", "bad", "00000000000000000000000000000000"])
def test_invalid_run_id_does_not_read_arbitrary_paths(admitted, run_id):
    assert jobs.get_virtual_preflight(run_id=run_id)["job_state"] == "ERROR"
    admitted[1].assert_not_called()


def test_unknown_id_or_key_is_read_only_not_found(admitted):
    assert jobs.get_virtual_preflight(run_id=str(uuid4()))["job_state"] == "NOT_FOUND"
    assert jobs.get_virtual_preflight(request_key="missing")["job_state"] == "NOT_FOUND"
    assert not jobs.RUN_ROOT.exists()
    assert not vehicle.LOCK_ROOT.exists()
    admitted[1].assert_not_called()


def test_symlink_escape_is_rejected(admitted, tmp_path):
    run_id = str(uuid4())
    jobs.RUN_ROOT.mkdir()
    (jobs.RUN_ROOT / run_id).symlink_to(tmp_path, target_is_directory=True)
    assert jobs.get_virtual_preflight(run_id=run_id)["job_state"] == "ERROR"


def test_historical_report_is_readable_without_mutation_or_worker(admitted):
    historical = jobs.LEGACY_ROOT / "virtual_preflight_2026_10_17/failed_wp3_report.json"
    before = historical.read_bytes()
    status = jobs.get_virtual_preflight(run_id=HISTORICAL)
    assert status["job_state"] == "FINISHED" and status["result_status"] == "FAILED"
    assert status["report"]["executor_result"]["recovery"]["landing_completed"] is True
    assert status["paths"]["report_path"] == str(historical)
    assert historical.read_bytes() == before and not jobs.RUN_ROOT.exists()
    admitted[1].assert_not_called()


@pytest.mark.parametrize("terminal", ["PASSED", "FAILED", "BLOCKED", "ERROR"])
def test_final_results_are_read_after_worker_completion(admitted, monkeypatch, terminal):
    result = begin(admitted)
    def finish(path, run_id, directory, **kwargs):
        report = {"run_id": run_id, "status": terminal, "stage": "analyze", "finished_at": vehicle.utc_now(),
                  "execution_attempted": False, "report_persisted": True,
                  "mission_sha256": kwargs["expected_sha256"], "executor_result": None}
        return persist_typed_stub(directory, report, kwargs["vehicle_selection"], kwargs["expected_sha256"])
    monkeypatch.setattr(workflow, "run_preflight_in_directory", finish)
    assert run_admitted(result, admitted)
    status = jobs.get_virtual_preflight(run_id=result["run_id"])
    assert status["job_state"] == "FINISHED" and status["result_status"] == terminal
    assert status["report"]["mission_sha256"] == result["mission_sha256"]
    assert vehicle.restriction() is None
    assert not run_admitted(result, admitted)  # no rerun
    assert begin(admitted)["admission_status"] == "EXISTING"  # key survives completion
    admitted[1].assert_called_once()


def test_worker_uses_real_graph_and_same_snapshot_gate_and_analysis(admitted, monkeypatch):
    result = begin(admitted)
    raw = {"success": False, "status": "BLOCKED", "stage": "EXECUTION_GATE", "message": "inner gate blocked",
           "vehicle": "v1", "vehicle_id": "drone_01"}
    execute = Mock(return_value=raw)
    monkeypatch.setattr(graph, "check_simulation_ready", lambda: {"ready": True})
    monkeypatch.setattr(graph, "execute_approved_mission", execute)
    assert run_admitted(result, admitted)
    status = jobs.get_virtual_preflight(run_id=result["run_id"])
    assert status["result_status"] == "BLOCKED"
    assert status["report"]["executor_result"] == raw
    assert status["report"]["mission_sha256"] == result["mission_sha256"]
    assert [t["node"] for t in status["report"]["transitions"]] == [
        "snapshot", "validate", "check_readiness", "compatibility", "execute", "analyze", "write_report"]
    execute.assert_called_once_with(result["paths"]["snapshot_path"], vehicle="v1", progress=False)
    assert vehicle.restriction() is None


def test_worker_rejects_changed_admission_snapshot_without_execution(admitted):
    result = begin(admitted)
    Path(result["paths"]["input_path"]).write_text("{}")
    assert not run_admitted(result, admitted)
    status = jobs.get_virtual_preflight(run_id=result["run_id"])
    assert status["job_state"] == "ERROR" and status["errors"]
    graph.execute_approved_mission.assert_not_called()
    assert vehicle.restriction()["owner_id"] == result["run_id"]  # tampered admission is never auto-cleared


def test_worker_exception_is_unconfirmed_and_restriction_survives(admitted, monkeypatch):
    result = begin(admitted)
    monkeypatch.setattr(workflow, "run_preflight_in_directory", Mock(side_effect=RuntimeError("worker lost telemetry")))
    assert not run_admitted(result, admitted)
    assert vehicle.restriction()["state"] == "UNCONFIRMED"
    status = jobs.get_virtual_preflight(run_id=result["run_id"])
    assert status["job_state"] == "UNCONFIRMED" and status["result_status"] is None
    assert not run_admitted(result, admitted)


def test_failed_recovery_keeps_restriction_even_with_final_report(admitted, monkeypatch):
    result = begin(admitted)
    def unsafe(path, run_id, directory, **kwargs):
        report = {"run_id": run_id, "status": "FAILED", "stage": "analyze", "finished_at": vehicle.utc_now(),
                  "execution_attempted": True, "report_persisted": True,
                  "executor_result": {"status": "FAILED", "success": False,
                                      "recovery": {"landing_completed": False}}}
        return persist_typed_stub(directory, report, kwargs["vehicle_selection"], kwargs["expected_sha256"])
    monkeypatch.setattr(workflow, "run_preflight_in_directory", unsafe)
    assert run_admitted(result, admitted)
    assert jobs.get_virtual_preflight(run_id=result["run_id"])["result_status"] == "FAILED"
    assert vehicle.restriction()["state"] == "UNCONFIRMED"
    assert begin(admitted, "another-flight")["admission_status"] == "VEHICLE_BUSY"


def test_sync_executor_cannot_bypass_async_reservation(admitted, monkeypatch):
    import tools.simulation_mission_executor as executor
    result = begin(admitted)
    gate = Mock(side_effect=AssertionError("must not reach gate or commands"))
    monkeypatch.setattr(executor, "check_mission_execution_ready", gate)
    blocked = executor.execute_approved_mission(str(admitted[0]), progress=False)
    assert blocked["status"] == "BLOCKED" and blocked["stage"] == "VEHICLE_EXCLUSION"
    assert vehicle.restriction()["owner_id"] == result["run_id"]
    gate.assert_not_called()


def test_sync_preflight_cannot_bypass_async_reservation(admitted, monkeypatch):
    import tools.simulation_mission_executor as executor
    begin(admitted)
    monkeypatch.setattr(workflow, "PREFLIGHT_ROOT", jobs.RUN_ROOT)
    monkeypatch.setattr(graph, "check_simulation_ready", lambda: {"ready": True})
    monkeypatch.setattr(graph, "execute_approved_mission", executor.execute_approved_mission)
    report = workflow.run_virtual_preflight(str(admitted[0]))
    assert report["status"] == "BLOCKED"
    assert report["executor_result"]["stage"] == "VEHICLE_EXCLUSION"


def test_progress_phase_is_persisted_while_readiness_runs(admitted, monkeypatch):
    result = begin(admitted)
    def ready():
        status = jobs.get_virtual_preflight(run_id=result["run_id"])
        assert status["job_state"] == "RUNNING"
        assert status["phase"] == "check_readiness"
        assert status["result_status"] is None
        return {"ready": False}
    monkeypatch.setattr(graph, "check_simulation_ready", ready)
    assert run_admitted(result, admitted)
    assert jobs.get_virtual_preflight(run_id=result["run_id"])["result_status"] == "BLOCKED"


def test_start_completes_while_detached_work_is_still_pending(admitted, monkeypatch):
    # A workflow double that cannot finish until explicitly released. Admission
    # returns before it is even invoked; no timing-sensitive wall clock assertion.
    from threading import Event
    pending = Event()
    invoked = Mock(side_effect=lambda *a, **k: pending.wait(1))
    monkeypatch.setattr(workflow, "run_preflight_in_directory", invoked)
    result = begin(admitted)
    assert result["job_state"] == "STARTING"
    assert not pending.is_set()
    invoked.assert_not_called()


def test_another_worker_cannot_claim_the_same_job(admitted, monkeypatch):
    result = begin(admitted)
    identity = {**result["worker"], "start_ticks": result["worker"]["start_ticks"] + 1}
    monkeypatch.setattr(worker, "process_identity", lambda: identity)
    assert not run_admitted(result, admitted)
    graph.execute_approved_mission.assert_not_called()
    assert vehicle.restriction()["owner_id"] == result["run_id"]


def test_final_report_wins_when_worker_exits_before_publishing_job_completion(admitted, monkeypatch):
    result = begin(admitted)
    directory = jobs.run_directory(result["run_id"])
    persist_typed_stub(directory, {
        "run_id": result["run_id"], "status": "FAILED", "stage": "analyze", "finished_at": vehicle.utc_now(),
    }, result["vehicle_selection"], result["mission_sha256"])
    monkeypatch.setattr(jobs, "identity_alive", lambda identity: False)
    status = jobs.get_virtual_preflight(run_id=result["run_id"])
    assert status["job_state"] == "FINISHED" and status["result_status"] == "FAILED"
    assert vehicle.restriction()["owner_id"] == result["run_id"]  # lookup never clears it


def test_worker_failure_before_finished_report_does_not_replay_on_reload(admitted, monkeypatch):
    result = begin(admitted)
    before = tree_bytes(jobs.RUN_ROOT)
    monkeypatch.setattr(jobs, "identity_alive", lambda identity: False)
    assert jobs.get_virtual_preflight(request_key="joel-test-1")["job_state"] == "INTERRUPTED"
    assert tree_bytes(jobs.RUN_ROOT) == before
    assert not worker.run_worker("00000000-0000-0000-0000-000000000000")


def test_worker_run_id_alone_cannot_launch_a_persisted_admission(admitted):
    result = begin(admitted)
    assert not worker.run_worker(result["run_id"])
    assert not worker.run_worker(result["run_id"], "wrong-token")
    graph.execute_approved_mission.assert_not_called()
    assert vehicle.restriction()["owner_id"] == result["run_id"]


def test_worker_scope_reaches_existing_internal_gate_through_langgraph(admitted, monkeypatch):
    import tools.simulation_mission_executor as executor
    result = begin(admitted)
    gate = Mock(return_value={"execution_authorized": False,
                              "mission_id": json.loads(admitted[0].read_bytes())["mission_id"]})
    monkeypatch.setattr(executor, "check_mission_execution_ready", gate)
    monkeypatch.setattr(graph, "check_simulation_ready", lambda: {"ready": True})
    monkeypatch.setattr(graph, "execute_approved_mission", executor.execute_approved_mission)
    assert run_admitted(result, admitted)
    report = jobs.get_virtual_preflight(run_id=result["run_id"])["report"]
    assert report["executor_result"]["stage"] == "EXECUTION_GATE"
    gate.assert_called_once_with(result["paths"]["snapshot_path"])
    assert vehicle.restriction() is None


def test_nonobject_persistent_job_is_a_defined_read_error(admitted):
    result = begin(admitted)
    Path(result["paths"]["job_path"]).write_text("[]")
    before = tree_bytes(jobs.RUN_ROOT), tree_bytes(vehicle.LOCK_ROOT)
    status = jobs.get_virtual_preflight(run_id=result["run_id"])
    assert status["job_state"] == "ERROR" and status["errors"]
    assert before == (tree_bytes(jobs.RUN_ROOT), tree_bytes(vehicle.LOCK_ROOT))
    admitted[1].assert_called_once()


def test_nonobject_persistent_report_is_a_defined_read_error(admitted):
    result = begin(admitted)
    Path(result["paths"]["report_path"]).write_text('["incomplete"]')
    assert jobs.get_virtual_preflight(run_id=result["run_id"])["job_state"] == "ERROR"
    assert vehicle.restriction()["owner_id"] == result["run_id"]


def test_admission_rejects_fifo_without_opening_it_in_blocking_mode(admitted, monkeypatch):
    # Intercept read_bytes so the pre-fix implementation fails instead of hanging.
    fifo = admitted[0].with_name("input.fifo")
    os.mkfifo(fifo)
    original = Path.read_bytes
    def bounded(path):
        if path == fifo:
            pytest.fail("Unbounded/blocking read of FIFO during admission")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", bounded)
    status = jobs.start_virtual_preflight(str(fifo), "fifo-input")
    assert status["admission_status"] == "ERROR"
    assert vehicle.restriction() is None
    admitted[1].assert_not_called()


def test_historical_passed_async_artifacts_are_consistent_and_lookup_is_read_only(admitted):
    from inputs.json_loader import load_mission_json
    from reporting.virtual_preflight_analysis import analyze_executor_result
    directory = jobs.LEGACY_ROOT / "virtual_preflight_2026_10_17"
    mission_path = directory / "passed_async_mission.json"
    report_path = directory / "passed_async_report.json"
    mission_bytes, report_bytes = mission_path.read_bytes(), report_path.read_bytes()
    saved = json.loads(report_bytes)
    assert saved["run_id"] == "f5f55084-5af6-4e58-ab1a-ce30a13832b3"
    assert hashlib.sha256(mission_bytes).hexdigest() == saved["mission_sha256"] == saved["expected_sha256"]
    assert analyze_executor_result(load_mission_json(str(mission_path)), saved["executor_result"])["passed"] is True
    status = jobs.get_virtual_preflight(run_id=saved["run_id"])
    assert status["job_state"] == "FINISHED" and status["result_status"] == "PASSED"
    assert mission_path.read_bytes() == mission_bytes and report_path.read_bytes() == report_bytes
    assert not jobs.RUN_ROOT.exists()
    admitted[1].assert_not_called()


def test_empty_request_record_cannot_be_treated_as_a_new_admission(admitted):
    first = begin(admitted)
    vehicle.release(first["run_id"])  # fake worker never executed; test simulates a finished reservation
    jobs.key_path("joel-test-1").write_text("{}")
    result = begin(admitted)
    assert result["admission_status"] == "ERROR"
    assert vehicle.restriction() is None
    admitted[1].assert_called_once()


@pytest.mark.parametrize("artifact", ["job.json", "report.json"])
def test_empty_record_is_an_error_instead_of_not_found(admitted, artifact):
    result = begin(admitted)
    (jobs.run_directory(result["run_id"]) / artifact).write_text("{}")
    assert jobs.get_virtual_preflight(run_id=result["run_id"])["job_state"] == "ERROR"
    assert vehicle.restriction()["owner_id"] == result["run_id"]


def test_oversized_regular_input_is_rejected_before_reading_content(admitted, monkeypatch):
    oversized = admitted[0].with_name("oversized.json")
    with oversized.open("wb") as file:
        file.truncate(jobs.MAX_INPUT_BYTES + 1)
    result = jobs.start_virtual_preflight(str(oversized), "oversized")
    assert result["admission_status"] == "ERROR"
    assert "5 MB" in result["errors"][0]
    assert vehicle.restriction() is None
    admitted[1].assert_not_called()
