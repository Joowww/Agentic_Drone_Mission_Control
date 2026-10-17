from datetime import datetime

import pytest

import tools.simulation_mission_executor as executor


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def observations(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(executor.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(executor.time, "sleep", clock.sleep)
    monkeypatch.setattr(executor, "_check_vehicle_safe", lambda vehicle: {
        "armed": True, "flying": True, "failsafe_active": False,
    })
    monkeypatch.setattr(executor, "get_vehicle_geopose", lambda **kwargs: {
        "latitude": 41.001, "longitude": 2.0, "altitude_amsl_m": 104.0,
    })
    return clock


TARGET = {"waypoint_id": "WP3", "latitude": 41.0, "longitude": 2.0, "altitude_m": 5.0}


def wait(timeout=30):
    return executor._wait_for_waypoint(TARGET, vehicle="v1", launch_altitude_amsl_m=100,
                                       timeout_seconds=timeout)


def test_timeout_has_target_last_position_errors_bounded_samples_and_timing(observations):
    with pytest.raises(executor.WaypointWaitError) as failure:
        wait()
    d = failure.value.diagnostic
    assert d["failure_kind"] == "TIMEOUT"
    assert d["position_outcome"] == "POSITION_NOT_REACHED"
    assert d["target"]["altitude_amsl_m"] == 105
    assert d["target"]["altitude_relative_m"] == 5
    assert d["position_observations"] == d["poll_attempts"] == 15
    assert len(d["samples"]) == d["samples_limit"] == executor.WAYPOINT_DIAGNOSTIC_SAMPLES
    assert d["samples"][0]["attempt"] == 4
    assert d["last_observation"]["horizontal_error_m"] > 100
    assert d["last_observation"]["altitude_error_m"] == 1
    assert d["last_observation_age_seconds"] == 2
    assert d["elapsed_seconds"] == d["timeout_seconds"] == 30
    assert d["deadline_overrun_seconds"] == 0
    assert datetime.fromisoformat(d["finished_at"]) >= datetime.fromisoformat(d["started_at"])
    assert d["tolerances"] == {"horizontal_m": 1.0, "altitude_m": 0.75}


def test_no_position_observation_is_distinct_from_not_reached(observations, monkeypatch):
    def unavailable(**kwargs):
        raise TimeoutError("geopose timed out")
    monkeypatch.setattr(executor, "get_vehicle_geopose", unavailable)
    with pytest.raises(executor.WaypointWaitError) as failure:
        wait()
    d = failure.value.diagnostic
    assert d["position_outcome"] == "NO_POSITION_OBSERVATION"
    assert d["position_observations"] == 0
    assert d["last_observation"] is None
    assert d["last_observation_age_seconds"] is None
    assert d["failure_stage"] == "POSITION_OBSERVATION"
    assert d["failure_kind"] == "WAIT_ERROR"
    assert d["samples"][0]["error"]["type"] == "TimeoutError"
    assert d["last_status"]["armed"] is True


def test_later_observation_failure_preserves_previous_sample(observations, monkeypatch):
    count = 0
    def read(**kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("telemetry failed")
        return {"latitude": 41.001, "longitude": 2.0, "altitude_amsl_m": 104}
    monkeypatch.setattr(executor, "get_vehicle_geopose", read)
    with pytest.raises(executor.WaypointWaitError) as failure:
        wait()
    d = failure.value.diagnostic
    assert d["position_outcome"] == "POSITION_NOT_REACHED"
    assert d["position_observations"] == 1 and d["poll_attempts"] == 2
    assert d["last_observation"]["position"]["latitude"] == 41.001
    assert d["last_observation_age_seconds"] == 2
    assert d["samples"][-1]["error"]["message"] == "telemetry failed"


def test_slow_position_read_records_duration_and_deadline_overrun(observations, monkeypatch):
    def slow(**kwargs):
        observations.now += 35
        return {"latitude": 41.001, "longitude": 2.0, "altitude_amsl_m": 104}
    monkeypatch.setattr(executor, "get_vehicle_geopose", slow)
    with pytest.raises(executor.WaypointWaitError) as failure:
        wait()
    d = failure.value.diagnostic
    assert d["samples"][0]["position_read_seconds"] == 35
    assert d["elapsed_seconds"] == 37
    assert d["deadline_overrun_seconds"] == 7


def test_disarmed_status_still_aborts_without_reading_position(observations, monkeypatch):
    monkeypatch.setattr(executor, "_check_vehicle_safe", lambda vehicle: {"armed": False})
    monkeypatch.setattr(executor, "get_vehicle_geopose", lambda **kwargs: pytest.fail("position read after disarm"))
    with pytest.raises(executor.WaypointWaitError) as failure:
        wait()
    assert failure.value.diagnostic["failure_stage"] == "VEHICLE_STATE"
    assert failure.value.diagnostic["last_status"]["armed"] is False


def test_success_shape_and_tolerances_are_preserved(observations, monkeypatch):
    pose = {"latitude": 41.0, "longitude": 2.0, "altitude_amsl_m": 105.75}
    monkeypatch.setattr(executor, "get_vehicle_geopose", lambda **kwargs: pose)
    assert wait() == {"reached": True, "waypoint_id": "WP3", "horizontal_error_m": 0,
                      "altitude_error_m": 0.75, "final_position": pose}


def test_executor_keeps_wait_diagnostic_and_existing_recovery(observations, monkeypatch):
    from pathlib import Path
    from inputs.json_loader import load_mission_json
    mission = load_mission_json(str(Path(__file__).resolve().parents[1] /
                                   "missions/examples/simulation_navigation_smoke.json"))
    with pytest.raises(executor.WaypointWaitError) as failed:
        wait(timeout=4)
    diagnostic = failed.value.diagnostic
    failure = failed.value
    monkeypatch.setattr(executor, "check_mission_execution_ready", lambda path: {"execution_authorized": True})
    monkeypatch.setattr(executor, "load_mission_json", lambda path: mission)
    monkeypatch.setattr(executor, "get_vehicle_global_origin", lambda **kwargs: {
        "latitude": 41, "longitude": 2, "altitude_amsl_m": 100,
    })
    for name in ("switch_vehicle_mode", "arm_vehicle", "takeoff_vehicle", "send_global_position_target"):
        monkeypatch.setattr(executor, name, lambda *args, **kwargs: {"success": True})
    monkeypatch.setattr(executor, "_wait_for_takeoff", lambda **kwargs: {"altitude_error_m": 0})
    def fail_wait(*args, **kwargs):
        raise failure
    monkeypatch.setattr(executor, "_wait_for_waypoint", fail_wait)
    landed = []
    monkeypatch.setattr(executor, "land_vehicle", lambda **kwargs: landed.append(kwargs))
    monkeypatch.setattr(executor, "_wait_for_landing", lambda **kwargs: {
        "landed": True, "armed": False, "flying": False, "final_position": {},
    })
    result = executor.execute_approved_mission("unused.json", vehicle="v1", progress=False)
    assert result["status"] == "FAILED"
    assert result["waypoint_diagnostic"] == diagnostic
    assert result["recovery"]["landing_attempted"] is True
    assert result["recovery"]["landing_completed"] is True
    assert landed == [{"vehicle": "v1"}]


def test_failed_slow_position_read_has_duration_without_invented_position(observations, monkeypatch):
    def slow_timeout(**kwargs):
        observations.now += 31
        raise TimeoutError("position read timed out")
    monkeypatch.setattr(executor, "get_vehicle_geopose", slow_timeout)
    with pytest.raises(executor.WaypointWaitError) as failure:
        wait()
    d = failure.value.diagnostic
    assert d["position_outcome"] == "NO_POSITION_OBSERVATION"
    assert d["samples"][0]["position_read_seconds"] == 31
    assert d["elapsed_seconds"] == 31 and d["deadline_overrun_seconds"] == 1
    assert d["last_observation"] is None


def test_active_failsafe_still_aborts_and_keeps_the_error(observations, monkeypatch):
    def failsafe(vehicle):
        raise executor.MissionExecutionError("ArduPilot reported an active failsafe.")
    monkeypatch.setattr(executor, "_check_vehicle_safe", failsafe)
    monkeypatch.setattr(executor, "get_vehicle_geopose", lambda **kwargs: pytest.fail("read after failsafe"))
    with pytest.raises(executor.WaypointWaitError) as failure:
        wait()
    assert failure.value.diagnostic["failure_stage"] == "STATUS_OBSERVATION"
    assert failure.value.diagnostic["error"]["message"] == "ArduPilot reported an active failsafe."
