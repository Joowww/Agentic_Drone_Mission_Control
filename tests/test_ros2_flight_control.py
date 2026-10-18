from __future__ import annotations

import pytest

import tools.ros2_flight_control as flight


STATUS_OUTPUT = """
vehicle_type: 2
armed: true
mode: 4
flying: true
external_control: true
failsafe: []
"""

GEOPOSE_OUTPUT = """
pose:
  position:
    latitude: -35.36323547363281
    longitude: 149.1652069091797
    altitude: 589.1900024414062
"""


@pytest.fixture
def authority():
    from tools.vehicle_execution_lock import reserve, execution_scope
    reserve("ros-test", "test")
    with execution_scope("ros-test"):
        yield


def test_status_parser(monkeypatch):
    monkeypatch.setattr(
        flight,
        "_run_ros_command",
        lambda *args, **kwargs: STATUS_OUTPUT,
    )

    result = flight.get_vehicle_status()

    assert result["armed"] is True
    assert result["mode"] == 4
    assert result["flying"] is True
    assert result["external_control"] is True
    assert result["failsafe_active"] is False


def test_geopose_parser(monkeypatch):
    monkeypatch.setattr(
        flight,
        "_run_ros_command",
        lambda *args, **kwargs: GEOPOSE_OUTPUT,
    )

    result = flight.get_vehicle_geopose()

    assert result["latitude"] == pytest.approx(
        -35.36323547363281
    )
    assert result["longitude"] == pytest.approx(
        149.1652069091797
    )
    assert result["altitude_amsl_m"] == pytest.approx(
        589.1900024414062
    )


def test_global_target_contains_required_ap_dds_fields(
    monkeypatch, authority,
):
    captured = {}

    def fake_run(
        command,
        *,
        timeout_seconds=30,
    ):
        captured["command"] = command
        return "publishing #1: test"

    monkeypatch.setattr(
        flight,
        "_run_ros_command",
        fake_run,
    )

    result = flight.send_global_position_target(
        -35.363235,
        149.165207,
        5.0,
    )

    command = captured["command"]

    assert "frame_id: map" in command
    assert "coordinate_frame: 6" in command
    assert "type_mask: 3576" in command
    assert "/ap/v1/cmd_gps_pose" in command

    assert result["success"] is True


def test_takeoff_rejects_invalid_altitude():
    with pytest.raises(ValueError):
        flight.takeoff_vehicle(0.0)


def test_guided_mode_acceptance(monkeypatch, authority):
    monkeypatch.setattr(
        flight,
        "_run_ros_command",
        lambda *args, **kwargs: (
            "ModeSwitch_Response("
            "status=True, curr_mode=4)"
        ),
    )

    result = flight.switch_vehicle_mode(
        flight.GUIDED_MODE
    )

    assert result["success"] is True
    assert result["mode"] == 4