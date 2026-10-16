from __future__ import annotations

import tools.mission_execution_gate as execution_gate


def test_blocks_mission_not_approved(monkeypatch):
    simulation_called = False

    def fake_validate_mission_file(
        mission_path,
        export_qgc=False,
    ):
        return {
            "mission_id": "unsafe_mission",
            "mission_status": "NOT FEASIBLE",
            "execution_status": "BLOCKED",
            "failure_reasons": [
                "Battery reserve would be violated."
            ],
            "errors": [],
        }

    def fake_check_simulation_ready():
        nonlocal simulation_called
        simulation_called = True

        return {
            "ready": True,
        }

    monkeypatch.setattr(
        execution_gate,
        "validate_mission_file",
        fake_validate_mission_file,
    )

    monkeypatch.setattr(
        execution_gate,
        "check_simulation_ready",
        fake_check_simulation_ready,
    )

    result = execution_gate.check_mission_execution_ready(
        "unsafe.json"
    )

    assert result["execution_authorized"] is False
    assert result["status"] == "BLOCKED"
    assert result["stage"] == "MISSION_VALIDATION"

    # Important:
    # an unsafe mission never reaches the simulation gate.
    assert simulation_called is False


def test_blocks_approved_mission_when_simulation_not_ready(
    monkeypatch,
):
    def fake_validate_mission_file(
        mission_path,
        export_qgc=False,
    ):
        return {
            "mission_id": "safe_mission",
            "mission_status": "FEASIBLE",
            "execution_status": "APPROVED",
            "failure_reasons": [],
            "errors": [],
        }

    def fake_check_simulation_ready():
        return {
            "ready": False,
            "status": "NOT READY",
            "return_code": 1,
            "message": "Simulation is not ready.",
            "output": "Gazebo is not running.",
        }

    monkeypatch.setattr(
        execution_gate,
        "validate_mission_file",
        fake_validate_mission_file,
    )

    monkeypatch.setattr(
        execution_gate,
        "check_simulation_ready",
        fake_check_simulation_ready,
    )

    result = execution_gate.check_mission_execution_ready(
        "safe.json"
    )

    assert result["execution_authorized"] is False
    assert result["status"] == "BLOCKED"
    assert result["stage"] == "SIMULATION_READINESS"
    assert result["simulation_ready"] is False


def test_authorizes_approved_mission_when_simulation_ready(
    monkeypatch,
):
    def fake_validate_mission_file(
        mission_path,
        export_qgc=False,
    ):
        return {
            "mission_id": "safe_mission",
            "mission_status": "FEASIBLE",
            "execution_status": "APPROVED",
            "failure_reasons": [],
            "errors": [],
        }

    def fake_check_simulation_ready():
        return {
            "ready": True,
            "status": "READY",
            "return_code": 0,
            "message": (
                "Simulation is healthy and both drones are ready."
            ),
            "output": "SIMULATION HEALTHY",
        }

    monkeypatch.setattr(
        execution_gate,
        "validate_mission_file",
        fake_validate_mission_file,
    )

    monkeypatch.setattr(
        execution_gate,
        "check_simulation_ready",
        fake_check_simulation_ready,
    )

    result = execution_gate.check_mission_execution_ready(
        "safe.json"
    )

    assert result["execution_authorized"] is True
    assert result["status"] == "READY_FOR_EXECUTION"
    assert result["stage"] == "EXECUTION_GATE"
    assert result["mission_status"] == "FEASIBLE"
    assert result["execution_status"] == "APPROVED"
    assert result["simulation_ready"] is True