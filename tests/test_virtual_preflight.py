"""Offline workflow tests: real validation/graph, fake readiness and executor."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import graph.virtual_preflight_graph as workflow
from inputs.json_loader import load_mission_json
from tools.simulation_mission_mapper import map_mission_route_to_simulation
import tools.virtual_preflight as preflight

EXAMPLE = Path(__file__).resolve().parents[1] / "missions/examples/simulation_navigation_3waypoint.json"
FULL_ROUTE = ["snapshot", "validate", "check_readiness", "compatibility", "execute", "analyze", "write_report"]


def completed_result(mission):
    launch = {"latitude": -35.0, "longitude": 149.0, "altitude_amsl_m": 584.0}
    altitude = mission.route.waypoints[0].altitude_m
    events = [
        {"event": "GUIDED_MODE", "success": True},
        {"event": "ARM", "success": True},
        {"event": "TAKEOFF_COMMAND", "success": True, "altitude_m": altitude},
        {"event": "TAKEOFF_REACHED", "reached": True, "target_altitude_m": altitude,
         "altitude_amsl_m": 584.0 + altitude, "altitude_error_m": 0.0},
    ]
    def reached(name, target):
        return {"event": name, "waypoint_id": target["waypoint_id"], "reached": True,
                "horizontal_error_m": 0.0, "altitude_error_m": 0.0,
                "final_position": {"latitude": target["latitude"], "longitude": target["longitude"],
                                   "altitude_amsl_m": 584.0 + target["altitude_m"]}}
    for target in map_mission_route_to_simulation(
        mission, simulation_home_latitude=-35.0, simulation_home_longitude=149.0,
    ):
        events.append({"event": "WAYPOINT_COMMAND", "waypoint_id": target["waypoint_id"], "success": True})
        events.append(reached("WAYPOINT_REACHED", target))
    if mission.route.return_to_home:
        events.append({"event": "RETURN_HOME_COMMAND", "success": True})
        events.append(reached("RETURN_HOME_REACHED", {
            **launch, "waypoint_id": "SIMULATION_HOME", "altitude_m": mission.route.waypoints[-1].altitude_m,
        }))
    events.extend([
        {"event": "LAND_COMMAND", "success": True},
        {"event": "LANDED", "landed": True, "armed": False, "flying": False, "final_position": launch},
    ])
    return {"status": "COMPLETED", "success": True, "stage": "MISSION_EXECUTION",
            "mission_id": mission.mission_id, "vehicle": "v1", "vehicle_id": mission.vehicle.vehicle_id, "launch_position": launch,
            "simulation_origin": launch, "events": events, "final_position": launch,
            "waypoints_completed": len(mission.route.waypoints), "return_to_home": mission.route.return_to_home}


@pytest.fixture
def environment(tmp_path, monkeypatch):
    # If a new path accidentally reaches subprocess/Docker, fail immediately.
    monkeypatch.setattr("subprocess.run", Mock(side_effect=AssertionError("No subprocess allowed")))
    monkeypatch.setattr(preflight, "PREFLIGHT_ROOT", tmp_path / "runs")
    source = tmp_path / "input.json"
    source.write_bytes(EXAMPLE.read_bytes())
    ready = Mock(return_value={"ready": True, "status": "READY"})
    execute = Mock(side_effect=lambda path, **kwargs: completed_result(load_mission_json(path)))
    monkeypatch.setattr(workflow, "check_simulation_ready", ready)
    monkeypatch.setattr(workflow, "execute_approved_mission", execute)
    return source, ready, execute


def nodes(report):
    return [event["node"] for event in report["transitions"]]


def persisted(report):
    assert report["report_persisted"] is True
    assert json.loads(Path(report["report_path"]).read_text()) == report
    assert datetime.fromisoformat(report["finished_at"]) >= datetime.fromisoformat(report["started_at"])


def edit(source, change):
    data = json.loads(source.read_text())
    change(data)
    source.write_text(json.dumps(data))


@pytest.mark.parametrize("content", [b"{bad", b'{}'])
def test_invalid_mission_blocked_before_readiness_or_execution(environment, content):
    source, ready, execute = environment
    source.write_bytes(content)
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "BLOCKED"
    assert nodes(report) == ["snapshot", "write_report"]
    assert report["mission_sha256"] == hashlib.sha256(content).hexdigest()
    assert source.read_bytes() == Path(report["snapshot_path"]).read_bytes() == content
    ready.assert_not_called()
    execute.assert_not_called()
    persisted(report)


def test_unsafe_mission_includes_replanner_proposals(environment):
    source, ready, execute = environment
    edit(source, lambda data: data["environment"].update(wind_speed_kmh=80))
    original = source.read_bytes()
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "BLOCKED"
    assert nodes(report) == ["snapshot", "validate", "write_report"]
    assert report["validation"]["mission_status"] == "NOT FEASIBLE"
    assert any("Delay mission" in proposal for proposal in report["replan_proposals"])
    assert source.read_bytes() == original
    ready.assert_not_called()
    execute.assert_not_called()
    persisted(report)


def test_simulation_not_ready_blocks_without_execution(environment):
    source, ready, execute = environment
    ready.return_value = {"ready": False, "message": "Gazebo is stopped"}
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "BLOCKED"
    assert "Gazebo is stopped" in report["reasons"]
    assert nodes(report) == FULL_ROUTE[:3] + ["write_report"]
    execute.assert_not_called()
    persisted(report)


@pytest.mark.parametrize("change", [
    lambda d: d["vehicle"].update(autopilot="PX4"),
    lambda d: d["vehicle"].update(vehicle_type="fixed_wing"),
    lambda d: d["route"]["waypoints"][0].update(action="take_photo"),
    lambda d: d["route"]["waypoints"][0].update(altitude_m=0),
])
def test_incompatible_mission_never_invokes_executor(environment, change):
    source, _, execute = environment
    edit(source, change)
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "BLOCKED"
    assert report["compatibility_errors"]
    assert nodes(report) == FULL_ROUTE[:4] + ["write_report"]
    execute.assert_not_called()
    persisted(report)


@pytest.mark.parametrize("return_home", [True, False])
def test_complete_rehearsal_passes_once_and_persists_identity_hash_times(environment, return_home):
    source, _, execute = environment
    edit(source, lambda d: d["route"].update(return_to_home=return_home))
    original = source.read_bytes()
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "PASSED"
    assert report["analysis"]["passed"] is True
    assert nodes(report) == FULL_ROUTE
    assert report["mission_identity"]["mission_id"] == json.loads(original)["mission_id"]
    assert report["mission_sha256"] == hashlib.sha256(original).hexdigest()
    assert Path(report["snapshot_path"]).read_bytes() == original == source.read_bytes()
    assert Path(report["run_directory"]).parent == preflight.PREFLIGHT_ROOT
    execute.assert_called_once_with(report["snapshot_path"], vehicle="v1", progress=False)
    assert report["execution_attempted"] is True
    assert datetime.fromisoformat(report["execution_finished_at"]) >= datetime.fromisoformat(report["execution_started_at"])
    assert report["hardware_authorized"] is report["subsequent_execution_authorized"] is False
    persisted(report)


def test_failure_with_recovery_is_failed_and_preserves_raw_result(environment):
    source, _, execute = environment
    raw = {"status": "FAILED", "success": False, "stage": "MISSION_EXECUTION", "error": "timeout",
           "events": [{"event": "ARM", "success": True}],
           "recovery": {"landing_attempted": True, "landing_completed": True,
                        "landing": {"landed": True, "armed": False, "flying": False}}}
    execute.side_effect = None
    execute.return_value = deepcopy(raw)
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "FAILED"
    assert report["executor_result"] == raw
    assert "Executor error: timeout" in report["reasons"]
    assert report["analysis"]["passed"] is False
    assert nodes(report) == FULL_ROUTE
    execute.assert_called_once()
    persisted(report)


@pytest.mark.parametrize("damage", [
    lambda r: r.pop("events"),
    lambda r: r.update(success=False),
    lambda r: r.update(waypoints_completed=2),
    lambda r: r.update(vehicle="v2"),
    lambda r: r.update(mission_id="different"),
    lambda r: r.update(return_to_home=False),
    lambda r: r["events"].pop(),  # no landing evidence
    lambda r: r["events"][-1].update(armed=True),
    lambda r: r["events"][-1].update(flying=True),
    lambda r: r["events"][5].update(horizontal_error_m=1.01),
    lambda r: r["events"][5].update(altitude_error_m=0.76),
    lambda r: r["events"][5].update(horizontal_error_m=float("nan")),
    lambda r: r["events"][5].update(waypoint_id="wrong"),
    lambda r: r["events"][5].update(reached=False),
    lambda r: r["events"][-3].update(reached=False),
    lambda r: r["events"][-1].pop("armed"),
    lambda r: r["events"][2].update(altitude_m=99),
    lambda r: r["events"][4].update(success=False),
    lambda r: r["events"][5]["final_position"].update(latitude=0),
    lambda r: r["events"].reverse(),
    lambda r: r["events"].append({"event": "LANDED", "landed": True}),
    lambda r: r["events"].pop(-3),  # return not reached
])
def test_incomplete_or_contradictory_result_never_passes(environment, damage):
    source, _, execute = environment
    raw = completed_result(load_mission_json(str(source)))
    damage(raw)
    execute.side_effect = None
    execute.return_value = raw
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "FAILED"
    assert report["reasons"]
    assert nodes(report) == FULL_ROUTE
    execute.assert_called_once()


@pytest.mark.parametrize("raw", [None, {}, "COMPLETED", {"status": "COMPLETED", "success": True}])
def test_missing_evidence_fails(environment, raw):
    source, _, execute = environment
    execute.side_effect = None
    execute.return_value = raw
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "FAILED"
    persisted(report)


def test_inner_gate_can_block_after_outer_checks(environment):
    source, _, execute = environment
    execute.side_effect = None
    execute.return_value = {"status": "BLOCKED", "success": False, "stage": "EXECUTION_GATE",
                            "gate": {"execution_authorized": False}, "message": "Simulation no longer ready"}
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "BLOCKED"
    assert nodes(report) == FULL_ROUTE
    assert report["executor_result"]["gate"]["execution_authorized"] is False
    persisted(report)


def test_unexpected_executor_exception_is_error_without_retry(environment):
    source, _, execute = environment
    execute.side_effect = RuntimeError("telemetry unavailable before arming")
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "ERROR"
    assert report["executor_result"] is None
    assert nodes(report) == FULL_ROUTE[:5] + ["write_report"]
    assert report["execution_attempted"] is True
    execute.assert_called_once()
    persisted(report)


def test_readiness_exception_is_error_and_does_not_execute(environment):
    source, ready, execute = environment
    ready.side_effect = TimeoutError("readiness timed out")
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "ERROR"
    assert nodes(report) == FULL_ROUTE[:3] + ["write_report"]
    execute.assert_not_called()
    persisted(report)


def test_missing_file_returns_persistent_error(environment):
    source, ready, execute = environment
    report = preflight.run_virtual_preflight(str(source.with_name("missing.json")))
    assert report["status"] == "ERROR"
    assert report["mission_sha256"] is None
    ready.assert_not_called()
    execute.assert_not_called()
    persisted(report)


def test_source_changes_do_not_change_the_snapshot_used_by_executor(environment):
    source, ready, execute = environment
    original = source.read_bytes()
    def ready_after_edit():
        source.write_text("{}")
        return {"ready": True}
    ready.side_effect = ready_after_edit
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "PASSED"
    assert Path(report["snapshot_path"]).read_bytes() == original
    assert report["mission_sha256"] == hashlib.sha256(original).hexdigest()
    assert source.read_bytes() != original
    execute.assert_called_once()
    persisted(report)


def test_snapshot_tamper_before_executor_is_error_and_does_not_execute(environment, monkeypatch):
    source, _, execute = environment
    def tamper(mission):
        snapshot = next(preflight.PREFLIGHT_ROOT.glob("*/mission.json"))
        snapshot.write_text("{}")
        return []
    monkeypatch.setattr(workflow, "_execution_compatibility_errors", tamper)
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "ERROR"
    assert nodes(report) == FULL_ROUTE[:5] + ["write_report"]
    execute.assert_not_called()
    persisted(report)


def test_snapshot_tamper_during_executor_cannot_pass(environment):
    source, _, execute = environment
    def tamper(path, **kwargs):
        raw = completed_result(load_mission_json(path))
        Path(path).write_text("{}")
        return raw
    execute.side_effect = tamper
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "ERROR"
    assert report["executor_result"]["status"] == "COMPLETED"
    persisted(report)


def test_run_directories_are_independent(environment):
    source, _, execute = environment
    first = preflight.run_virtual_preflight(str(source))
    before = Path(first["report_path"]).read_bytes()
    second = preflight.run_virtual_preflight(str(source))
    assert first["run_directory"] != second["run_directory"]
    assert first["mission_sha256"] == second["mission_sha256"]
    assert Path(first["report_path"]).read_bytes() == before
    assert execute.call_count == 2


def test_report_is_saved_as_running_before_executor_is_called(environment):
    source, _, execute = environment
    def inspect_running_report(path, **kwargs):
        interim = json.loads(Path(path).with_name("report.json").read_text())
        assert interim["status"] == "RUNNING"
        assert interim["execution_attempted"] is True
        assert interim["execution_started_at"]
        assert interim["executor_result"] is None
        return completed_result(load_mission_json(path))
    execute.side_effect = inspect_running_report
    assert preflight.run_virtual_preflight(str(source))["status"] == "PASSED"


def test_storage_failure_prevents_executor(environment, monkeypatch):
    source, _, execute = environment
    monkeypatch.setattr(workflow, "persist_report", Mock(side_effect=OSError("disk full")))
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "ERROR"
    assert report["report_persisted"] is False
    execute.assert_not_called()


def test_root_directory_failure_is_reported_without_executor(environment, monkeypatch):
    source, _, execute = environment
    monkeypatch.setattr(preflight, "PREFLIGHT_ROOT", source)
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "ERROR"
    assert report["report_persisted"] is False
    assert report["report_path"] is None
    execute.assert_not_called()


def test_failed_recovery_stays_failed_with_evidence(environment):
    source, _, execute = environment
    execute.side_effect = None
    execute.return_value = {"status": "FAILED", "success": False, "error": "waypoint timeout",
                            "events": [], "recovery": {"landing_attempted": True,
                            "landing_completed": False, "recovery_error": "landing timeout"}}
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "FAILED"
    assert report["executor_result"]["recovery"]["recovery_error"] == "landing timeout"
    execute.assert_called_once()
    persisted(report)


def test_nonfinite_evidence_never_passes_and_remains_standard_json(environment):
    source, _, execute = environment
    raw = completed_result(load_mission_json(str(source)))
    raw["events"][5]["altitude_error_m"] = float("inf")
    execute.side_effect = None
    execute.return_value = raw
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "FAILED"
    assert report["executor_result"]["events"][5]["altitude_error_m"] == {"non_finite_float": "inf"}
    json.dumps(report, allow_nan=False)
    persisted(report)


def test_finite_drift_within_executor_tolerance_can_pass(environment):
    source, _, execute = environment
    raw = completed_result(load_mission_json(str(source)))
    reached = raw["events"][5]
    reached["final_position"]["altitude_amsl_m"] += 0.5
    reached["altitude_error_m"] = 0.5
    execute.side_effect = None
    execute.return_value = raw
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "PASSED"
    persisted(report)


def test_waypoint_diagnostic_is_preserved_in_persistent_report(environment):
    source, _, execute = environment
    diagnostic = {
        "waypoint_id": "WP3", "failure_kind": "TIMEOUT", "position_outcome": "POSITION_NOT_REACHED",
        "last_observation": {"horizontal_error_m": 3.0, "altitude_error_m": 0.1},
        "samples": [{"attempt": 89}, {"attempt": 90}], "elapsed_seconds": 180,
    }
    execute.side_effect = None
    execute.return_value = {"status": "FAILED", "success": False, "error": "WP3 timeout", "events": [],
                            "waypoint_diagnostic": diagnostic,
                            "recovery": {"landing_completed": True}}
    report = preflight.run_virtual_preflight(str(source))
    assert report["status"] == "FAILED"
    assert report["executor_result"]["waypoint_diagnostic"] == diagnostic
    persisted(report)
