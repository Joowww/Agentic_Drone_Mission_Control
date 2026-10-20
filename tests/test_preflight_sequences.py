"""Offline ordered jobs, actual workflow/analysis/locks, no Docker/ROS/LLM."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import graph.virtual_preflight_graph as graph
from inputs.json_loader import load_mission_json
from tools import preflight_sequences as seq
from tools import preflight_sequence_worker as coordinator
from tools import virtual_preflight_jobs as jobs
from tools import virtual_preflight_worker as worker
from tools import vehicle_execution_lock as locks
import tools.simulation_mission_executor as executor
from tests.test_virtual_preflight import EXAMPLE, completed_result
from tests.test_mission_response_views import registered


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setattr(seq, "SEQUENCE_ROOT", tmp_path / "sequences")
    monkeypatch.setattr(seq, "MISSION_ROOT", tmp_path / "missions")
    monkeypatch.setattr(jobs, "RUN_ROOT", tmp_path / "runs")
    seq.MISSION_ROOT.mkdir()
    paths = []
    for logical in ("drone_01", "drone_02"):
        data = json.loads(EXAMPLE.read_bytes())
        data["vehicle"]["vehicle_id"] = logical
        data["mission_id"] = logical + "_sequence"
        path = seq.MISSION_ROOT / (logical + ".json")
        path.write_text(json.dumps(data))
        paths.append(str(path))
    monkeypatch.setattr("subprocess.run", Mock(side_effect=AssertionError("No real subprocess")))
    spawn = Mock(return_value=SimpleNamespace(pid=os.getpid()))
    monkeypatch.setattr(seq.subprocess, "Popen", spawn)
    readiness = Mock(return_value={"ready": True})
    monkeypatch.setattr(graph, "check_simulation_ready", readiness)
    order, contexts = [], []
    @locks.serialized_execution
    def execute(path, *, vehicle, progress):
        locks.assert_execution_authority(vehicle)
        order.append(vehicle)
        contexts.append(copy_context())
        result = completed_result(load_mission_json(path))
        result.update(vehicle=vehicle, vehicle_id=load_mission_json(path).vehicle.vehicle_id)
        return result
    flight = Mock(side_effect=execute)
    monkeypatch.setattr(graph, "execute_approved_mission", flight)
    return SimpleNamespace(paths=paths, spawn=spawn, flight=flight, order=order, contexts=contexts,
                           readiness=readiness, execute=execute)


def start(system, key="ordered-test"):
    return seq.start_preflight_sequence(system.paths, key, "Operator explicitly authorizes these two ordered SITL snapshots")


def run(system, admitted):
    token = system.spawn.call_args.args[0][-1]
    return coordinator.run_coordinator(admitted["sequence_id"], token)


def tree(root):
    return {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("reverse", [False, True])
def test_quick_admission_then_actual_workers_graph_and_reports_in_operator_order(system, monkeypatch, reverse):
    if reverse: system.paths.reverse()
    validate = Mock(wraps=coordinator.validate_mission)
    monkeypatch.setattr(coordinator, "validate_mission", validate)
    original = system.flight.side_effect
    def execute(*args, **kwargs):
        assert validate.call_count == 2  # BOTH before the first flight
        return original(*args, **kwargs)
    system.flight.side_effect = execute
    before = [Path(p).read_bytes() for p in system.paths]
    admitted = start(system)
    assert admitted["admission_status"] == "ACCEPTED" and admitted["result_status"] is None
    system.flight.assert_not_called(); system.readiness.assert_not_called()
    call = system.spawn.call_args
    assert call.args[0][:3] == [seq.sys.executable, "-m", "tools.preflight_sequence_worker"]
    assert call.kwargs["stdin"] == seq.subprocess.DEVNULL and call.kwargs["stderr"] == seq.subprocess.STDOUT
    assert call.kwargs["start_new_session"] and call.kwargs["close_fds"]
    for i, child in enumerate(admitted["plan"]["children"]):
        assert (seq.directory(admitted["sequence_id"]) / f"mission_{i+1}.json").read_bytes() == before[i]
        assert jobs.get_virtual_preflight(run_id=child["run_id"])["job_state"] == "QUEUED"
    assert run(system, admitted)
    assert system.order == (["v2", "v1"] if reverse else ["v1", "v2"])
    assert system.readiness.call_count == 2
    status = seq.get_preflight_sequence(sequence_id=admitted["sequence_id"], detail=True)
    assert status["job_state"] == "FINISHED" and status["result_status"] == "PASSED"
    assert status["sequence_restriction"] is status["global_flight_restriction"] is None
    for child in status["children"]:
        assert child["state"] == "FINISHED" and child["result_status"] == "PASSED"
        assert child["detail"]["report"]["analysis"]["checks"]["landed_and_disarmed"]
        assert Path(child["paths"]["worker_log_path"]).read_text().count("worker finished") == 1
    assert [Path(p).read_bytes() for p in system.paths] == before
    assert not run(system, admitted)  # terminal launch token cannot replay the pair


@pytest.mark.parametrize("damage", ["battery", "autopilot", "action"])
def test_invalid_or_incompatible_second_mission_blocks_both_before_readiness_or_flight(system, damage):
    path = Path(system.paths[1]); data = json.loads(path.read_bytes())
    if damage == "battery": data["vehicle"]["battery_percent"] = 11
    elif damage == "autopilot": data["vehicle"]["autopilot"] = "PX4"
    else: data["route"]["waypoints"][0]["action"] = "take_photo"
    path.write_text(json.dumps(data))
    admitted = start(system); assert run(system, admitted)
    status = seq.get_preflight_sequence(sequence_id=admitted["sequence_id"])
    assert status["result_status"] == "BLOCKED"
    assert all(c["state"] == "NOT_STARTED" and c["result_status"] is None for c in status["children"])
    system.flight.assert_not_called(); system.readiness.assert_not_called()
    assert locks.restriction() is None


def test_readiness_is_rechecked_for_each_child_and_second_can_block(system):
    system.readiness.side_effect = [{"ready": True}, {"ready": False, "message": "Simulator gone"}]
    admitted = start(system); assert run(system, admitted)
    status = seq.get_preflight_sequence(sequence_id=admitted["sequence_id"])
    assert system.order == ["v1"] and status["result_status"] == "BLOCKED"
    assert [c["result_status"] for c in status["children"]] == ["PASSED", "BLOCKED"]
    assert locks.restriction() is None


def test_failed_first_with_confirmed_recovery_never_starts_second_and_keeps_reports(system):
    def failed(path, **kwargs):
        raw = system.execute(path, **kwargs)
        raw.update(status="FAILED", success=False, error="Synthetic waypoint failure",
                   recovery={"landing_completed": True, "landing": {"landed": True, "armed": False, "flying": False}})
        return raw
    system.flight.side_effect = failed
    admitted = start(system); assert run(system, admitted)
    status = seq.get_preflight_sequence(sequence_id=admitted["sequence_id"], detail=True)
    assert status["result_status"] == "FAILED" and system.order == ["v1"]
    assert status["children"][0]["detail"]["report"]["executor_result"]["recovery"]["landing_completed"]
    assert status["children"][1]["state"] == "NOT_STARTED"
    assert locks.restriction() is None


@pytest.mark.parametrize("damage", ["landing", "logical_identity", "snapshot", "analysis", "job", "worker"])
def test_partial_contradictory_or_missing_child_outcome_keeps_guard_and_forbids_second(system, monkeypatch, damage):
    actual_worker = coordinator.run_worker
    def altered(run_id, token):
        if damage == "worker": return False
        if damage in {"landing", "logical_identity"}:
            original = system.flight.side_effect
            def execute(*a, **k):
                raw = original(*a, **k)
                if damage == "landing": raw["events"][-1]["armed"] = True
                else: raw["vehicle_id"] = "drone_02"
                return raw
            system.flight.side_effect = execute
        done = actual_worker(run_id, token)
        root = jobs.run_directory(run_id)
        if damage == "snapshot": (root / "mission.json").write_text("{}")
        elif damage == "analysis":
            report = json.loads((root / "report.json").read_bytes())
            report["analysis"]["checks"]["identity"] = False
            locks.atomic_json(root / "report.json", report)
        elif damage == "job":
            job = json.loads((root / "job.json").read_bytes()); job["job_state"] = "RUNNING"
            locks.atomic_json(root / "job.json", job)
        return done
    monkeypatch.setattr(coordinator, "run_worker", altered)
    admitted = start(system); assert not run(system, admitted)
    assert system.flight.call_count <= 1
    op = json.loads((seq.directory(admitted["sequence_id"]) / "operation.json").read_bytes())
    assert op["job_state"] == "UNCONFIRMED" and op["children"][1]["state"] == "NOT_STARTED"
    assert locks.sequence_restriction()["state"] == "UNCONFIRMED"
    assert jobs.start_virtual_preflight(system.paths[1], "unrelated")["admission_status"] == "VEHICLE_BUSY"


def test_no_external_sync_async_or_expired_authority_can_enter_between_children(system, monkeypatch):
    actual = coordinator.complete_sequence_child
    def gap(owner_id, plan_hash, index):
        actual(owner_id, plan_hash, index)
        assert locks.restriction()["kind"] == "PREFLIGHT_SEQUENCE"
        assert jobs.start_virtual_preflight(system.paths[1], "interloper")["admission_status"] == "VEHICLE_BUSY"
        result = executor.execute_approved_mission(system.paths[1], progress=False)
        assert result["stage"] == "VEHICLE_EXCLUSION"
        old = system.contexts[0].run(executor.execute_approved_mission, system.paths[0], progress=False)
        assert old["stage"] == "VEHICLE_EXCLUSION"
        with pytest.raises(locks.VehicleBusy):
            locks.reserve_sequence_child(owner_id, plan_hash, index)  # used slot
    monkeypatch.setattr(coordinator, "complete_sequence_child", gap)
    admitted = start(system); assert run(system, admitted)
    assert system.order == ["v1", "v2"]
    system.spawn.assert_called_once()


def test_concurrent_duplicates_and_unrelated_admissions_only_spawn_one_coordinator(system):
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: start(system), range(3)))
    assert {r["admission_status"] for r in results} == {"ACCEPTED", "EXISTING"}
    assert len({r["sequence_id"] for r in results}) == 1
    system.spawn.assert_called_once()
    assert start(system, "other-sequence")["admission_status"] == "VEHICLE_BUSY"
    assert jobs.start_virtual_preflight(system.paths[0], "standalone")["admission_status"] == "VEHICLE_BUSY"
    system.paths.reverse()
    assert start(system)["admission_status"] == "REQUEST_CONFLICT"
    assert seq.start_preflight_sequence(system.paths, "ordered-test", "different consent")["admission_status"] == "REQUEST_CONFLICT"
    system.flight.assert_not_called()


def test_existing_reservation_rejects_sequence_before_coordinator(system):
    locks.reserve("other", "test", "v2")
    assert start(system)["admission_status"] == "VEHICLE_BUSY"
    system.spawn.assert_not_called(); system.flight.assert_not_called()
    assert locks.restriction()["owner_id"] == "other"


def test_coordinator_loss_reload_and_queries_preserve_unknown_restrictions_without_effects(system, monkeypatch):
    admitted = start(system)
    frozen = tree(seq.SEQUENCE_ROOT), tree(jobs.RUN_ROOT), tree(locks.LOCK_ROOT)
    root, missions = seq.SEQUENCE_ROOT, seq.MISSION_ROOT
    importlib.reload(seq)
    monkeypatch.setattr(seq, "SEQUENCE_ROOT", root); monkeypatch.setattr(seq, "MISSION_ROOT", missions)
    monkeypatch.setattr(seq, "identity_alive", lambda _: False)
    for _ in range(2):
        view = seq.get_preflight_sequence(sequence_id=admitted["sequence_id"])
        assert view["job_state"] == "UNCONFIRMED" and view["result_status"] is None
        assert all(c["state"] == "NOT_STARTED" for c in view["children"])
    assert seq.get_preflight_sequence(request_key="ordered-test")["sequence_id"] == admitted["sequence_id"]
    assert frozen == (tree(seq.SEQUENCE_ROOT), tree(jobs.RUN_ROOT), tree(locks.LOCK_ROOT))
    assert start(system)["admission_status"] == "EXISTING"
    system.spawn.assert_called_once(); system.flight.assert_not_called()


def test_death_between_children_keeps_guard_with_no_child_lease(system, monkeypatch):
    actual = coordinator.complete_sequence_child
    def die(owner, plan, index):
        actual(owner, plan, index)
        raise SystemExit("Synthetic coordinator loss")
    monkeypatch.setattr(coordinator, "complete_sequence_child", die)
    admitted = start(system); assert not run(system, admitted)
    assert system.order == ["v1"]
    assert locks.restriction("v1") is locks.restriction("v2") is None
    assert locks.restriction()["state"] == "UNCONFIRMED"
    assert executor.execute_approved_mission(system.paths[1])["stage"] == "VEHICLE_EXCLUSION"


@pytest.mark.parametrize("kind", ["same_vehicle", "unknown_vehicle", "third_mission", "no_consent", "outside", "fifo"])
def test_invalid_combinations_paths_and_consent_never_spawn(system, kind, tmp_path):
    paths, statement = list(system.paths), "Explicit two-flight SITL consent"
    if kind == "same_vehicle": paths[1] = paths[0]
    elif kind == "unknown_vehicle":
        p = Path(paths[1]); data = json.loads(p.read_bytes()); data["vehicle"]["vehicle_id"] = "v2"; p.write_text(json.dumps(data))
    elif kind == "third_mission": paths.append(paths[0])
    elif kind == "no_consent": statement = " "
    elif kind == "outside":
        p = tmp_path / "outside.json"; p.write_bytes(Path(paths[1]).read_bytes()); paths[1] = str(p)
    else:
        p = seq.MISSION_ROOT / "pipe"; os.mkfifo(p); paths[1] = str(p)
    result = seq.start_preflight_sequence(paths, "invalid", statement)
    assert result["admission_status"] == "ERROR" and locks.restriction() is None
    system.spawn.assert_not_called(); system.flight.assert_not_called()


def test_registered_mcp_schema_dispatch_summary_detail_and_bad_ids_are_readonly(system):
    from tools.hermes_mcp_server import mcp
    import asyncio
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    schema = tools["start_preflight_sequence"].input_schema
    assert schema["properties"]["mission_paths"]["minItems"] == 2
    assert schema["properties"]["mission_paths"]["maxItems"] == 2
    admitted = registered("start_preflight_sequence", {"mission_paths": system.paths, "request_key": "registered",
                          "authorization_statement": "Explicitly authorized both missions in this order"})
    assert run(system, admitted)
    frozen = tree(seq.SEQUENCE_ROOT), tree(jobs.RUN_ROOT), tree(locks.LOCK_ROOT)
    for view in ("summary", "detail"):
        status = registered("get_preflight_sequence", {"sequence_id": admitted["sequence_id"], "view": view})
        assert status["result_status"] == "PASSED" and status["view"] == view
        assert ("detail" in status["children"][0]) is (view == "detail")
    assert seq.get_preflight_sequence(sequence_id="../../etc/passwd")["job_state"] == "ERROR"
    assert seq.get_preflight_sequence(sequence_id=admitted["sequence_id"], request_key="registered")["job_state"] == "ERROR"
    assert frozen == (tree(seq.SEQUENCE_ROOT), tree(jobs.RUN_ROOT), tree(locks.LOCK_ROOT))


def test_actual_executor_and_its_internal_gate_are_reused_for_both_children(system, monkeypatch):
    from tests.test_simulated_vehicle_selection import controls
    spies, _ = controls(monkeypatch)
    gate = Mock(return_value={"execution_authorized": True})
    monkeypatch.setattr(executor, "check_mission_execution_ready", gate)
    monkeypatch.setattr(graph, "execute_approved_mission", executor.execute_approved_mission)
    admitted = start(system); assert run(system, admitted)
    assert gate.call_count == 2 and system.readiness.call_count == 2
    for double in spies.values():
        assert {c.kwargs["vehicle"] for c in double.call_args_list} == {"v1", "v2"}
    assert seq.get_preflight_sequence(sequence_id=admitted["sequence_id"])["result_status"] == "PASSED"


def test_finished_reload_and_queries_do_not_replay_workers(system, monkeypatch):
    admitted = start(system); assert run(system, admitted)
    frozen = tree(seq.SEQUENCE_ROOT), tree(jobs.RUN_ROOT), tree(locks.LOCK_ROOT)
    root, missions = seq.SEQUENCE_ROOT, seq.MISSION_ROOT
    importlib.reload(seq)
    monkeypatch.setattr(seq, "SEQUENCE_ROOT", root); monkeypatch.setattr(seq, "MISSION_ROOT", missions)
    for _ in range(2):
        status = seq.get_preflight_sequence(request_key="ordered-test", detail=True)
        assert status["result_status"] == "PASSED"
    assert start(system)["admission_status"] == "EXISTING"
    assert frozen == (tree(seq.SEQUENCE_ROOT), tree(jobs.RUN_ROOT), tree(locks.LOCK_ROOT))
    system.spawn.assert_called_once()
    assert system.order == ["v1", "v2"]


def test_changed_first_report_during_second_prevents_final_pass_and_release(system, monkeypatch):
    original = coordinator.run_worker
    calls = []
    def run_child(run_id, token):
        done = original(run_id, token)
        calls.append(run_id)
        if len(calls) == 2:
            path = jobs.run_directory(calls[0]) / "report.json"
            report = json.loads(path.read_bytes()); report["analysis"]["checks"]["identity"] = False
            locks.atomic_json(path, report)
        return done
    monkeypatch.setattr(coordinator, "run_worker", run_child)
    admitted = start(system); assert not run(system, admitted)
    assert seq.get_preflight_sequence(sequence_id=admitted["sequence_id"])["job_state"] == "ERROR"
    assert locks.restriction()["state"] == "UNCONFIRMED"


def test_dispatch_tokens_cannot_launch_queued_child_or_another_coordinator(system):
    admitted = start(system)
    child = admitted["plan"]["children"][0]
    assert worker.run_worker(child["run_id"], None) is False
    assert coordinator.run_coordinator(admitted["sequence_id"], "wrong-token") is False
    assert locks.restriction()["state"] == "RESERVED"
    system.flight.assert_not_called()


def test_spawn_ambiguity_never_clears_guard_or_retries(system):
    system.spawn.side_effect = RuntimeError("Synthetic spawn ambiguity")
    admitted = start(system)
    assert admitted["job_state"] == "UNCONFIRMED" and admitted["result_status"] is None
    assert locks.restriction() is not None
    assert start(system)["admission_status"] == "EXISTING"
    system.spawn.assert_called_once(); system.flight.assert_not_called()


def test_sequence_and_standalone_concurrent_admission_share_same_global_exclusion(system):
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(start, system)
        b = pool.submit(jobs.start_virtual_preflight, system.paths[1], "competing")
        results = [a.result(), b.result()]
    assert {r["admission_status"] for r in results} == {"ACCEPTED", "VEHICLE_BUSY"}
    system.spawn.assert_called_once(); system.flight.assert_not_called()


@pytest.mark.parametrize("damage", ["parent_snapshot", "child_input", "plan", "missing_snapshot", "guard", "queued_report"])
def test_persisted_corruption_is_error_without_queries_repairing_or_spawning(system, damage):
    admitted = start(system); root = seq.directory(admitted["sequence_id"])
    if damage == "parent_snapshot": (root / "mission_2.json").write_text("{}")
    elif damage == "child_input":
        (jobs.run_directory(admitted["plan"]["children"][0]["run_id"]) / "input.json").write_text("{}")
    elif damage == "plan": (root / "plan.json").write_text("[]")
    elif damage == "missing_snapshot": (root / "mission_2.json").unlink()
    elif damage == "queued_report":
        (jobs.run_directory(admitted["plan"]["children"][0]["run_id"]) / "report.json").write_text("{}")
    else: (locks.LOCK_ROOT / "sequence.json").write_text("{}")
    frozen = tree(seq.SEQUENCE_ROOT), tree(jobs.RUN_ROOT), tree(locks.LOCK_ROOT)
    assert seq.get_preflight_sequence(sequence_id=admitted["sequence_id"])["job_state"] == "ERROR"
    assert frozen == (tree(seq.SEQUENCE_ROOT), tree(jobs.RUN_ROOT), tree(locks.LOCK_ROOT))
    system.spawn.assert_called_once(); system.flight.assert_not_called()


def test_live_query_distinguishes_running_child_and_unstarted_second(system):
    original = system.flight.side_effect
    admitted = start(system)
    def execute(*a, **k):
        status = seq.get_preflight_sequence(sequence_id=admitted["sequence_id"])
        current = len(system.order)
        assert status["children"][current]["state"] == "RUNNING"
        if current == 0: assert status["children"][1]["state"] == "NOT_STARTED"
        assert status["result_status"] is None
        return original(*a, **k)
    system.flight.side_effect = execute
    assert run(system, admitted)


def test_child_authority_is_consumed_and_cannot_emit_commands_after_its_executor_returns(system):
    original = system.flight.side_effect
    def attempt_replay(path, **kwargs):
        raw = original(path, **kwargs)
        replay = original(path, **kwargs)
        assert replay["stage"] == "VEHICLE_EXCLUSION"
        assert "single-use" in replay["message"]
        with pytest.raises(locks.VehicleBusy):
            locks.assert_execution_authority(kwargs["vehicle"])
        return raw
    system.flight.side_effect = attempt_replay
    admitted = start(system); assert run(system, admitted)
    assert system.order == ["v1", "v2"]


def test_sequence_authority_rejects_another_snapshot_even_on_the_same_vehicle(system):
    other = seq.MISSION_ROOT / "other.json"
    data = json.loads(Path(system.paths[0]).read_bytes()); data["name"] = "Unapproved snapshot"
    other.write_text(json.dumps(data))
    original = system.flight.side_effect
    system.flight.side_effect = lambda path, **kwargs: original(str(other), **kwargs)
    admitted = start(system); assert not run(system, admitted)
    assert system.order == [] and locks.restriction()["state"] == "UNCONFIRMED"
