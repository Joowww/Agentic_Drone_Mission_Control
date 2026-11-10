"""Offline binding/commands/worker/exclusion contracts; no live MCP or ROS/Docker."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy
import importlib
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from inputs.json_loader import load_mission_json
from planning.verified_preflight import verified_source
from reporting.virtual_preflight_analysis import analyze_executor_result
import graph.virtual_preflight_graph as graph
import tools.ros2_flight_control as ros
import tools.simulation_mission_executor as executor
import tools.vehicle_execution_lock as locks
import tools.virtual_preflight as sync
import tools.virtual_preflight_jobs as jobs
import tools.virtual_preflight_worker as worker
from tools.simulated_vehicle import resolve_vehicle
from tests.test_mission_response_views import registered
from tests.test_virtual_preflight import EXAMPLE, completed_result
from tests.test_waypoint_diagnostic import Clock


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(sync, "PREFLIGHT_ROOT", jobs.RUN_ROOT)
    monkeypatch.setattr("subprocess.run", Mock(side_effect=AssertionError("No Docker or subprocess")))
    spawned = Mock(return_value=SimpleNamespace(pid=os.getpid()))
    monkeypatch.setattr(jobs.subprocess, "Popen", spawned)
    monkeypatch.setattr(graph, "check_simulation_ready", Mock(return_value={"ready": True}))
    monkeypatch.setattr(executor, "check_mission_execution_ready", Mock(return_value={"execution_authorized": True}))
    paths = {}
    for logical in ("drone_01", "drone_02"):
        data = json.loads(EXAMPLE.read_bytes())
        data["vehicle"]["vehicle_id"] = logical
        data["mission_id"] += "_" + logical
        path = tmp_path / (logical + ".json")
        path.write_text(json.dumps(data))
        paths[logical] = path
    return paths, spawned


def controls(monkeypatch, *, fail_waypoint=False, recovery_fails=False):
    """Actual executor and mapper, independent launch poses, fake control and waits."""
    poses = {"v1": {"latitude": -35., "longitude": 149., "altitude_amsl_m": 500.},
             "v2": {"latitude": -36., "longitude": 150., "altitude_amsl_m": 600.}}
    mocks = {}
    def set_double(name, side_effect):
        mocks[name] = Mock(side_effect=side_effect)
        monkeypatch.setattr(executor, name, mocks[name])
    set_double("get_vehicle_global_origin", lambda **k: {**poses[k["vehicle"]], "latitude": -34.})
    set_double("get_vehicle_geopose", lambda **k: deepcopy(poses[k["vehicle"]]))
    for name in ("switch_vehicle_mode", "arm_vehicle", "takeoff_vehicle", "send_global_position_target", "land_vehicle"):
        set_double(name, lambda *a, **k: {"success": True})
    set_double("_wait_for_takeoff", lambda **k: {
        "reached": True, "target_altitude_m": k["target_altitude_m"], "altitude_error_m": 0.,
        "altitude_amsl_m": k["launch_altitude_amsl_m"] + k["target_altitude_m"]})
    def waypoint(target, **k):
        if fail_waypoint:
            raise executor.WaypointWaitError("Synthetic position timeout", {
                "vehicle": k["vehicle"], "waypoint_id": target["waypoint_id"],
                "position_outcome": "NO_POSITION_OBSERVATION", "target": target})
        return {"reached": True, "waypoint_id": target["waypoint_id"],
                "horizontal_error_m": 0., "altitude_error_m": 0.,
                "final_position": {"latitude": target["latitude"], "longitude": target["longitude"],
                                   "altitude_amsl_m": k["launch_altitude_amsl_m"] + target["altitude_m"]}}
    set_double("_wait_for_waypoint", waypoint)
    def landed(**k):
        if recovery_fails:
            raise TimeoutError("Synthetic LAND unconfirmed")
        return {"landed": True, "armed": False, "flying": False, "final_position": poses[k["vehicle"]]}
    set_double("_wait_for_landing", landed)
    return mocks, poses


def admit(system, logical="drone_02", key="vehicle-test"):
    return jobs.start_virtual_preflight(str(system[0][logical]), key)


def finish(system, admitted):
    return worker.run_worker(admitted["run_id"], system[1].call_args.args[0][-1])


@pytest.mark.parametrize("logical,interface", [("drone_01", "v1"), ("drone_02", "v2")])
def test_full_executor_directs_origin_launch_targets_return_and_landing_to_selected_vehicle(system, monkeypatch, logical, interface):
    spies, poses = controls(monkeypatch)
    mission = load_mission_json(str(system[0][logical]))
    result = executor.execute_approved_mission(str(system[0][logical]), progress=False)
    assert result["status"] == "COMPLETED" and result["vehicle_id"] == logical and result["vehicle"] == interface
    assert analyze_executor_result(mission, result, require_vehicle_identity=True)["passed"] is True
    assert result["launch_position"] == poses[interface]
    assert result["simulation_origin"]["latitude"] != result["launch_position"]["latitude"]
    for double in spies.values():
        assert double.called
        assert all(call.kwargs["vehicle"] == interface for call in double.call_args_list)
    home = spies["send_global_position_target"].call_args
    assert home.args[:2] == (poses[interface]["latitude"], poses[interface]["longitude"])
    assert locks.restriction() is None


@pytest.mark.parametrize("bad_id", ["drone_03", "drone_2", "v2", "../v1", "drone_01;echo bad"])
def test_unknown_id_rejected_before_executor_gate_commands_reservation_or_worker(system, monkeypatch, bad_id):
    path = system[0]["drone_02"]
    content = json.loads(path.read_bytes()); content["vehicle"]["vehicle_id"] = bad_id
    path.write_text(json.dumps(content))
    spies, _ = controls(monkeypatch)
    assert executor.execute_approved_mission(str(path))["stage"] == "VEHICLE_SELECTION"
    assert admit(system)["admission_status"] == "ERROR"
    executor.check_mission_execution_ready.assert_not_called()
    for double in spies.values(): double.assert_not_called()
    system[1].assert_not_called()
    assert locks.restriction() is None


def test_explicit_interface_must_match_mission_before_any_flight(system, monkeypatch):
    spies, _ = controls(monkeypatch)
    result = executor.execute_approved_mission(str(system[0]["drone_02"]), vehicle="v1")
    assert result["status"] == "BLOCKED" and result["stage"] == "VEHICLE_SELECTION"
    executor.check_mission_execution_ready.assert_not_called()
    for double in spies.values(): double.assert_not_called()
    assert locks.restriction() is None


@pytest.mark.parametrize("kind", ["PX4", "fixed_wing", "take_photo"])
def test_unsupported_capabilities_block_before_origin_or_commands_for_v2(system, monkeypatch, kind):
    path = system[0]["drone_02"]; value = json.loads(path.read_bytes())
    if kind == "PX4": value["vehicle"]["autopilot"] = kind
    elif kind == "fixed_wing": value["vehicle"]["vehicle_type"] = kind
    else: value["route"]["waypoints"][0]["action"] = kind
    path.write_text(json.dumps(value)); spies, _ = controls(monkeypatch)
    result = executor.execute_approved_mission(str(path), progress=False)
    assert result["stage"] == "EXECUTION_COMPATIBILITY" and result["vehicle"] == "v2"
    for double in spies.values(): double.assert_not_called()
    assert locks.restriction() is None


def test_async_v2_runs_existing_graph_executor_analysis_and_readonly_mcp_views(system, monkeypatch):
    spies, _ = controls(monkeypatch)
    before = system[0]["drone_02"].read_bytes()
    admitted = registered("start_virtual_preflight", {"mission_path": str(system[0]["drone_02"]), "request_key": "mcp-v2"})
    assert admitted["vehicle_selection"] == {"vehicle_id": "drone_02", "simulated_vehicle": "v2"}
    assert admitted["global_flight_restriction"]["vehicle"] == "v2"
    assert finish(system, admitted)
    frozen = {str(p): p.read_bytes() for p in jobs.RUN_ROOT.rglob("*") if p.is_file()}
    for view in ("summary", "detail"):
        status = registered("get_virtual_preflight", {"run_id": admitted["run_id"], "view": view})
        assert status["result_status"] == "PASSED" and status["job_state"] == "FINISHED"
        assert status["vehicle_selection"] == status["report"]["vehicle_selection"] == admitted["vehicle_selection"]
        assert status["report"]["analysis"]["checks"]["identity"] is True
        assert status["vehicle_restriction"] is status["global_flight_restriction"] is None
    assert frozen == {str(p): p.read_bytes() for p in jobs.RUN_ROOT.rglob("*") if p.is_file()}
    assert system[0]["drone_02"].read_bytes() == before
    assert verified_source(admitted["run_id"])["report"]["status"] == "PASSED"
    assert all(call.kwargs["vehicle"] == "v2" for double in spies.values() for call in double.call_args_list)
    system[1].assert_called_once()


@pytest.mark.parametrize("recovery_fails", [False, True])
def test_waypoint_failure_report_and_recovery_land_stay_on_v2(system, monkeypatch, recovery_fails):
    spies, _ = controls(monkeypatch, fail_waypoint=True, recovery_fails=recovery_fails)
    admitted = admit(system); assert finish(system, admitted)
    status = jobs.get_virtual_preflight(run_id=admitted["run_id"])
    assert status["result_status"] == "FAILED"
    raw = status["report"]["executor_result"]
    assert raw["waypoint_diagnostic"]["vehicle"] == raw["vehicle"] == "v2"
    assert raw["recovery"]["landing_attempted"] is True
    assert raw["recovery"]["landing_completed"] is (not recovery_fails)
    spies["land_vehicle"].assert_called_once_with(vehicle="v2")
    if recovery_fails:
        assert locks.restriction("v2")["state"] == "UNCONFIRMED"
        assert admit(system, "drone_01", "new-v1")["admission_status"] == "VEHICLE_BUSY"
    else:
        assert locks.restriction() is None


@pytest.mark.parametrize("logical,other", [("drone_01", "drone_02"), ("drone_02", "drone_01")])
def test_global_reservation_blocks_other_vehicle_sync_async_and_duplicate_requests(system, monkeypatch, logical, other):
    controls(monkeypatch)
    first = admit(system, logical)
    assert admit(system, logical)["admission_status"] == "EXISTING"
    conflict = admit(system, other)
    assert conflict["admission_status"] == "REQUEST_CONFLICT" and conflict["run_id"] == first["run_id"]
    assert conflict["vehicle_selection"] == first["vehicle_selection"]
    assert admit(system, other, "other-key")["admission_status"] == "VEHICLE_BUSY"
    assert executor.execute_approved_mission(str(system[0][other]))["stage"] == "VEHICLE_EXCLUSION"
    assert sync.run_virtual_preflight(str(system[0][other]))["executor_result"]["stage"] == "VEHICLE_EXCLUSION"
    system[1].assert_called_once()


def test_concurrent_different_vehicles_admit_only_one_worker(system):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda logical: admit(system, logical, logical), ["drone_01", "drone_02"]))
    assert {r["admission_status"] for r in results} == {"ACCEPTED", "VEHICLE_BUSY"}
    system[1].assert_called_once()


def test_concurrent_v2_duplicates_and_reload_recover_same_admission_without_replay(system, monkeypatch):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: admit(system), range(2)))
    assert {r["admission_status"] for r in results} == {"ACCEPTED", "EXISTING"}
    assert results[0]["run_id"] == results[1]["run_id"]
    root = jobs.RUN_ROOT
    importlib.reload(jobs)
    monkeypatch.setattr(jobs, "RUN_ROOT", root)
    status = jobs.get_virtual_preflight(request_key="vehicle-test")
    assert status["run_id"] == results[0]["run_id"] and status["vehicle_selection"]["simulated_vehicle"] == "v2"
    assert admit(system)["admission_status"] == "EXISTING"
    system[1].assert_called_once()


def test_worker_disappearance_keeps_v2_and_global_restriction_without_query_effects(system, monkeypatch):
    admitted = admit(system)
    before = {str(p): p.read_bytes() for p in locks.LOCK_ROOT.rglob("*") if p.is_file()}
    monkeypatch.setattr(jobs, "identity_alive", lambda identity: False)
    status = registered("get_virtual_preflight", {"request_key": "vehicle-test"})
    assert status["job_state"] == "INTERRUPTED" and status["result_status"] is None
    assert status["vehicle_restriction"]["vehicle"] == "v2"
    assert before == {str(p): p.read_bytes() for p in locks.LOCK_ROOT.rglob("*") if p.is_file()}
    assert admit(system, "drone_01", "after-loss")["admission_status"] == "VEHICLE_BUSY"
    system[1].assert_called_once()


def test_tampered_admission_vehicle_never_executes_or_releases(system, monkeypatch):
    spies, _ = controls(monkeypatch)
    admitted = admit(system); path = Path(admitted["paths"]["job_path"])
    job = json.loads(path.read_bytes()); job["vehicle_selection"] = resolve_vehicle("drone_01").as_dict()
    path.write_text(json.dumps(job))
    assert not finish(system, admitted)
    assert jobs.get_virtual_preflight(run_id=admitted["run_id"])["job_state"] == "ERROR"
    assert locks.restriction("v2")["owner_id"] == admitted["run_id"]
    for double in spies.values(): double.assert_not_called()


@pytest.mark.parametrize("damage", ["selection", "mission_id", "raw_vehicle", "identity_type"])
def test_final_v2_identity_corruption_is_a_read_error_without_effects(system, monkeypatch, damage):
    controls(monkeypatch)
    admitted = admit(system); assert finish(system, admitted)
    path = Path(admitted["paths"]["report_path"]); report = json.loads(path.read_bytes())
    if damage == "selection": report["vehicle_selection"] = resolve_vehicle("drone_01").as_dict()
    elif damage == "mission_id": report["mission_identity"]["mission_id"] = "different_mission"
    elif damage == "raw_vehicle": report["executor_result"]["vehicle"] = "v1"
    else: report["mission_identity"] = ["malformed"]
    path.write_text(json.dumps(report)); content = path.read_bytes()
    status = registered("get_virtual_preflight", {"run_id": admitted["run_id"]})
    assert status["job_state"] == "ERROR" and status["errors"]
    assert path.read_bytes() == content and locks.restriction() is None
    system[1].assert_called_once()


def test_analyzer_rejects_wrong_logical_or_interface_identity(system):
    mission = load_mission_json(str(system[0]["drone_02"]))
    raw = completed_result(mission); raw.update(vehicle="v2", vehicle_id="drone_02")
    assert analyze_executor_result(mission, raw, require_vehicle_identity=True)["passed"] is True
    for patch in ({"vehicle": "v1"}, {"vehicle_id": "drone_01"}, {"vehicle_id": None}):
        wrong = {**raw, **patch}
        analysis = analyze_executor_result(mission, wrong, require_vehicle_identity=True)
        assert analysis["passed"] is False and analysis["checks"]["identity"] is False


def test_new_v1_report_cannot_downgrade_to_legacy_identity_checks(system, monkeypatch):
    controls(monkeypatch)
    admitted = admit(system, "drone_01"); assert finish(system, admitted)
    path = Path(admitted["paths"]["report_path"]); report = json.loads(path.read_bytes())
    report["schema_version"] = "1.0"
    report["executor_result"].pop("vehicle_id")
    path.write_text(json.dumps(report)); content = path.read_bytes()
    assert jobs.get_virtual_preflight(run_id=admitted["run_id"])["job_state"] == "ERROR"
    with pytest.raises(ValueError, match="legacy downgrade"):
        verified_source(admitted["run_id"])
    assert path.read_bytes() == content and locks.restriction() is None
    system[1].assert_called_once()


def test_inconsistent_executor_identity_is_never_used_to_release_reservation(system, monkeypatch):
    def wrong_vehicle(path, **kwargs):
        raw = completed_result(load_mission_json(path))
        raw.update(vehicle="v1", vehicle_id="drone_01")
        return raw
    monkeypatch.setattr(graph, "execute_approved_mission", wrong_vehicle)
    admitted = admit(system)
    assert not finish(system, admitted)
    assert locks.restriction("v2")["state"] == "UNCONFIRMED"
    assert jobs.get_virtual_preflight(run_id=admitted["run_id"])["job_state"] == "ERROR"
    assert admit(system, "drone_01", "wrong-identity")["admission_status"] == "VEHICLE_BUSY"


@pytest.mark.parametrize("interface", ["v1", "v2"])
def test_same_os_mutex_is_used_for_both_interfaces(interface):
    locks.reserve("owner", "test", interface)
    with locks.file_mutex(locks.LOCK_ROOT / "v1.execution.lock"):
        with pytest.raises(locks.VehicleBusy, match="OS mutex"):
            with locks.execution_scope("owner", interface): pytest.fail("concurrent scope")


def test_v2_authority_cannot_be_borrowed_by_v1_or_reused_after_scope_exit():
    locks.reserve("scope", "test", "v2")
    invoked = Mock()
    with locks.execution_scope("scope", "v2"):
        expired = copy_context()
        result = locks.serialized_execution(invoked)("unused", vehicle="v1")
        assert result["stage"] == "VEHICLE_EXCLUSION"
    result = expired.run(locks.serialized_execution(invoked), "unused", vehicle="v2")
    assert result["stage"] == "VEHICLE_EXCLUSION"
    invoked.assert_not_called()


@pytest.mark.parametrize("content", ["null", "[]", "{}", "{bad"])
def test_malformed_reservation_is_not_treated_as_available(system, content):
    locks.LOCK_ROOT.mkdir()
    path = locks.LOCK_ROOT / "v2.json"; path.write_text(content)
    assert admit(system, "drone_01")["admission_status"] == "ERROR"
    assert path.read_text() == content
    system[1].assert_not_called()


@pytest.mark.parametrize("interface", ["v1", "v2"])
def test_actual_ros_builders_use_selected_namespace_and_original_ap_dds_constants(monkeypatch, interface):
    captured = []
    def run(command, **kwargs):
        captured.append(command)
        return ("armed: true\nmode: 4\nflying: true\nexternal_control: true\nfailsafe: []\n"
                "latitude: -35\nlongitude: 149\naltitude: 584\n"
                "status=True curr_mode=4 curr_mode=9 result=True publishing #1")
    monkeypatch.setattr(ros, "_run_ros_command", run)
    ros.get_vehicle_status(interface); ros.get_vehicle_geopose(interface); ros.get_vehicle_global_origin(interface)
    locks.reserve("ros", "test", interface)
    with locks.execution_scope("ros", interface):
        ros.switch_vehicle_mode(4, vehicle=interface); ros.arm_vehicle(vehicle=interface)
        ros.takeoff_vehicle(5, vehicle=interface); ros.send_global_position_target(-35, 149, 5, vehicle=interface)
        ros.land_vehicle(vehicle=interface)
    assert len(captured) == 8 and all(f"/ap/{interface}/" in text for text in captured)
    target = next(text for text in captured if "cmd_gps_pose" in text)
    assert "coordinate_frame: 6" in target and "type_mask: 3576" in target
    assert "--qos-reliability best_effort" in target


def test_ros_commands_require_matching_live_authority_and_reject_unknown_interface(monkeypatch):
    run = Mock(side_effect=AssertionError("no command allowed")); monkeypatch.setattr(ros, "_run_ros_command", run)
    with pytest.raises(locks.VehicleBusy): ros.arm_vehicle(vehicle="v2")
    with pytest.raises(ValueError): ros.get_vehicle_status("v2;echo bad")
    locks.reserve("v1-owner", "test")
    with locks.execution_scope("v1-owner"):
        with pytest.raises(locks.VehicleBusy): ros.land_vehicle(vehicle="v2")
    run.assert_not_called()


def test_actual_waypoint_observations_and_timeout_diagnostic_use_v2(monkeypatch):
    clock = Clock(); monkeypatch.setattr(executor.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(executor.time, "sleep", clock.sleep)
    status = Mock(return_value={"armed": True, "failsafe_active": False})
    pose = Mock(return_value={"latitude": 41.001, "longitude": 2., "altitude_amsl_m": 104.})
    monkeypatch.setattr(executor, "get_vehicle_status", status); monkeypatch.setattr(executor, "get_vehicle_geopose", pose)
    with pytest.raises(executor.WaypointWaitError) as failure:
        executor._wait_for_waypoint({"waypoint_id": "WP3", "latitude": 41., "longitude": 2., "altitude_m": 5.},
                                   vehicle="v2", launch_altitude_amsl_m=100., timeout_seconds=4)
    assert failure.value.diagnostic["vehicle"] == "v2"
    assert failure.value.diagnostic["position_outcome"] == "POSITION_NOT_REACHED"
    for double in (status, pose):
        assert double.called and all(call.kwargs == {"vehicle": "v2"} for call in double.call_args_list)


def test_historical_v1_query_and_reanalysis_preserve_report_bytes_and_hashes(system):
    # Use the preserved report via the historical evidence root, no runtime query or rewrite.
    historical = jobs.LEGACY_ROOT / "virtual_preflight_2026_10_17/passed_async_report.json"
    raw = historical.read_bytes(); saved = json.loads(raw); run_id = saved["run_id"]
    full = registered("get_virtual_preflight", {"run_id": run_id, "view": "detail"})
    assert full["result_status"] == "PASSED" and full["report"] == saved
    assert full["vehicle_selection"]["simulated_vehicle"] == "v1"
    assert full["vehicle_selection_basis"] == "LEGACY_RECORDED_V1"
    assert verified_source(run_id)["report_sha256"] == hashlib.sha256(raw).hexdigest()
    assert historical.read_bytes() == raw
    assert not jobs.RUN_ROOT.exists()
    system[1].assert_not_called()


@pytest.mark.parametrize("logical,interface", [("drone_01", "v1"), ("drone_02", "v2")])
def test_registered_sync_executor_resolves_mission_instead_of_forcing_v1(system, monkeypatch, logical, interface):
    controls(monkeypatch)
    result = registered("execute_approved_mission", {"mission_path": str(system[0][logical])})
    assert result["status"] == "COMPLETED" and result["vehicle"] == interface
    assert result["vehicle_id"] == logical


def test_registered_execution_gate_reports_v2_and_unknown_id_without_readiness(system, monkeypatch):
    import tools.mission_execution_gate as gate
    ready = Mock(return_value={"ready": True}); monkeypatch.setattr(gate, "check_simulation_ready", ready)
    result = registered("check_mission_execution_ready", {"mission_path": str(system[0]["drone_02"])})
    assert result["vehicle_id"] == "drone_02" and result["simulated_vehicle"] == "v2"
    assert result["execution_authorized"] is True
    path = system[0]["drone_02"]; data = json.loads(path.read_bytes()); data["vehicle"]["vehicle_id"] = "unknown_drone"
    path.write_text(json.dumps(data)); ready.reset_mock()
    result = registered("check_mission_execution_ready", {"mission_path": str(path)})
    assert result["stage"] == "VEHICLE_SELECTION" and result["execution_authorized"] is False
    ready.assert_not_called()
