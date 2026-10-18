from __future__ import annotations

from types import SimpleNamespace

import tools.simulation_mission_executor as executor


def test_blocked_gate_never_commands_vehicle(
    monkeypatch,
):
    commanded = False

    monkeypatch.setattr(
        executor,
        "check_mission_execution_ready",
        lambda mission_path: {
            "mission_id": "blocked",
            "execution_authorized": False,
        },
    )

    def fake_mode(*args, **kwargs):
        nonlocal commanded
        commanded = True

    monkeypatch.setattr(
        executor,
        "switch_vehicle_mode",
        fake_mode,
    )

    result = executor.execute_approved_mission(
        "blocked.json"
    )

    assert result["success"] is False
    assert result["status"] == "BLOCKED"
    assert commanded is False


def test_unsupported_action_is_blocked(
    monkeypatch,
):
    monkeypatch.setattr(
        executor,
        "check_mission_execution_ready",
        lambda mission_path: {
            "mission_id": "mission_1",
            "execution_authorized": True,
        },
    )

    waypoint = SimpleNamespace(
        waypoint_id="WP1",
        altitude_m=5.0,
        action="take_photo",
    )

    mission = SimpleNamespace(
        mission_id="mission_1",
        vehicle=SimpleNamespace(
            vehicle_id="drone_01",
            vehicle_type="multirotor",
            autopilot="ArduPilot",
        ),
        route=SimpleNamespace(
            mode="waypoints",
            waypoints=[waypoint],
            return_to_home=False,
        ),
    )

    monkeypatch.setattr(
        executor,
        "load_mission_json",
        lambda path: mission,
    )

    result = executor.execute_approved_mission(
        "mission.json"
    )

    assert result["success"] is False
    assert result["status"] == "BLOCKED"

    assert (
        result["stage"]
        == "EXECUTION_COMPATIBILITY"
    )


def test_successful_navigation_mission(
    monkeypatch,
):
    monkeypatch.setattr(
        executor,
        "check_mission_execution_ready",
        lambda mission_path: {
            "mission_id": "mission_1",
            "execution_authorized": True,
        },
    )

    waypoint = SimpleNamespace(
        waypoint_id="WP1",
        altitude_m=5.0,
        action="navigate",
    )

    mission = SimpleNamespace(
        mission_id="mission_1",
        vehicle=SimpleNamespace(
            vehicle_id="drone_01",
            vehicle_type="multirotor",
            autopilot="ArduPilot",
        ),
        route=SimpleNamespace(
            mode="waypoints",
            waypoints=[waypoint],
            return_to_home=False,
        ),
    )

    monkeypatch.setattr(
        executor,
        "load_mission_json",
        lambda path: mission,
    )

    monkeypatch.setattr(
        executor,
        "get_vehicle_global_origin",
        lambda vehicle="v1": {
            "latitude": -35.0,
            "longitude": 149.0,
            "altitude_amsl_m": 584.0,
        },
    )

    monkeypatch.setattr(
        executor,
        "get_vehicle_geopose",
        lambda vehicle="v1": {
            "latitude": -35.00002,
            "longitude": 148.99997,
            "altitude_amsl_m": 584.2,
        },
    )

    monkeypatch.setattr(
        executor,
        "map_mission_route_to_simulation",
        lambda *args, **kwargs: [
            {
                "waypoint_id": "WP1",
                "latitude": -35.00001,
                "longitude": 149.0,
                "altitude_m": 5.0,
                "action": "navigate",
            }
        ],
    )

    monkeypatch.setattr(
        executor,
        "switch_vehicle_mode",
        lambda *args, **kwargs: {
            "success": True
        },
    )

    monkeypatch.setattr(
        executor,
        "arm_vehicle",
        lambda **kwargs: {
            "success": True
        },
    )

    monkeypatch.setattr(
        executor,
        "takeoff_vehicle",
        lambda *args, **kwargs: {
            "success": True
        },
    )

    monkeypatch.setattr(
        executor,
        "_wait_for_takeoff",
        lambda **kwargs: {
            "reached": True,
            "target_altitude_m": 5.0,
            "altitude_amsl_m": 589.2,
            "altitude_error_m": 0.2,
        },
    )

    monkeypatch.setattr(
        executor,
        "send_global_position_target",
        lambda *args, **kwargs: {
            "success": True
        },
    )

    monkeypatch.setattr(
        executor,
        "_wait_for_waypoint",
        lambda *args, **kwargs: {
            "reached": True,
            "waypoint_id": "WP1",
            "horizontal_error_m": 0.4,
            "altitude_error_m": 0.1,
            "final_position": {
                "latitude": -35.00001,
                "longitude": 149.0,
                "altitude_amsl_m": 589.2,
            },
        },
    )

    monkeypatch.setattr(
        executor,
        "land_vehicle",
        lambda **kwargs: {
            "success": True
        },
    )

    monkeypatch.setattr(
        executor,
        "_wait_for_landing",
        lambda **kwargs: {
            "landed": True,
            "armed": False,
            "flying": False,
            "final_position": {
                "latitude": -35.00002,
                "longitude": 148.99997,
                "altitude_amsl_m": 584.2,
            },
        },
    )

    result = executor.execute_approved_mission(
        "mission.json"
    )

    assert result["success"] is True
    assert result["status"] == "COMPLETED"

    assert (
        result["waypoints_completed"]
        == 1
    )

    assert (
        result["launch_position"][
            "latitude"
        ]
        == -35.00002
    )


def test_failure_after_arm_attempts_landing(
    monkeypatch,
):
    landing_called = False

    monkeypatch.setattr(
        executor,
        "check_mission_execution_ready",
        lambda mission_path: {
            "mission_id": "mission_1",
            "execution_authorized": True,
        },
    )

    waypoint = SimpleNamespace(
        waypoint_id="WP1",
        altitude_m=5.0,
        action="navigate",
    )

    mission = SimpleNamespace(
        mission_id="mission_1",
        vehicle=SimpleNamespace(
            vehicle_id="drone_01",
            vehicle_type="multirotor",
            autopilot="ArduPilot",
        ),
        route=SimpleNamespace(
            mode="waypoints",
            waypoints=[waypoint],
            return_to_home=False,
        ),
    )

    monkeypatch.setattr(
        executor,
        "load_mission_json",
        lambda path: mission,
    )

    monkeypatch.setattr(
        executor,
        "get_vehicle_global_origin",
        lambda vehicle="v1": {
            "latitude": -35.0,
            "longitude": 149.0,
            "altitude_amsl_m": 584.0,
        },
    )

    monkeypatch.setattr(
        executor,
        "get_vehicle_geopose",
        lambda vehicle="v1": {
            "latitude": -35.00002,
            "longitude": 148.99997,
            "altitude_amsl_m": 584.2,
        },
    )

    monkeypatch.setattr(
        executor,
        "map_mission_route_to_simulation",
        lambda *args, **kwargs: [
            {
                "waypoint_id": "WP1",
                "latitude": -35.00001,
                "longitude": 149.0,
                "altitude_m": 5.0,
                "action": "navigate",
            }
        ],
    )

    monkeypatch.setattr(
        executor,
        "switch_vehicle_mode",
        lambda *args, **kwargs: {
            "success": True
        },
    )

    monkeypatch.setattr(
        executor,
        "arm_vehicle",
        lambda **kwargs: {
            "success": True
        },
    )

    monkeypatch.setattr(
        executor,
        "takeoff_vehicle",
        lambda *args, **kwargs: {
            "success": True
        },
    )

    def fail_takeoff(**kwargs):
        raise executor.MissionExecutionError(
            "takeoff failed"
        )

    monkeypatch.setattr(
        executor,
        "_wait_for_takeoff",
        fail_takeoff,
    )

    def fake_land(**kwargs):
        nonlocal landing_called

        landing_called = True

        return {
            "success": True
        }

    monkeypatch.setattr(
        executor,
        "land_vehicle",
        fake_land,
    )

    monkeypatch.setattr(
        executor,
        "_wait_for_landing",
        lambda **kwargs: {
            "landed": True,
            "armed": False,
            "flying": False,
            "final_position": {},
        },
    )

    result = executor.execute_approved_mission(
        "mission.json"
    )

    assert result["success"] is False
    assert result["status"] == "FAILED"

    assert landing_called is True

    assert (
        result["recovery"][
            "landing_completed"
        ]
        is True
    )