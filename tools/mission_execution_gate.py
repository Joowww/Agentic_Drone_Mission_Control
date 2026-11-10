from __future__ import annotations

from tools.hermes_mission_validation import (
    ERRORS,
    EXECUTION_STATUS,
    FAILURE_REASONS,
    MISSION_ID,
    MISSION_STATUS,
    validate_mission_file,
)
from tools.simulation_status import check_simulation_ready
from inputs.json_loader import load_mission_json
from tools.simulated_vehicle import resolve_mission_vehicle


def _check_mission_execution_ready(
    mission_path: str,
) -> dict[str, object]:
    """Check whether a mission is authorized for simulation execution.

    Authorization requires both:

    1. The deterministic mission validation pipeline must return APPROVED.
    2. The ROS2/Gazebo/ArduPilot simulation must be READY.

    This function does not arm, take off, or command any vehicle.
    """

    validation = validate_mission_file(
        mission_path,
        export_qgc=False,
    )

    mission_id = validation.get(MISSION_ID)
    mission_status = validation.get(MISSION_STATUS)
    execution_status = validation.get(EXECUTION_STATUS)

    if execution_status != "APPROVED":
        return {
            "mission_id": mission_id,
            "execution_authorized": False,
            "status": "BLOCKED",
            "stage": "MISSION_VALIDATION",
            "mission_status": mission_status,
            "execution_status": execution_status,
            "simulation_ready": None,
            "failure_reasons": validation.get(
                FAILURE_REASONS,
                [],
            ),
            "errors": validation.get(
                ERRORS,
                [],
            ),
            "message": (
                "Mission execution is blocked because "
                "the deterministic safety pipeline did "
                "not approve the mission."
            ),
        }

    simulation = check_simulation_ready()

    if not simulation.get("ready", False):
        return {
            "mission_id": mission_id,
            "execution_authorized": False,
            "status": "BLOCKED",
            "stage": "SIMULATION_READINESS",
            "mission_status": mission_status,
            "execution_status": execution_status,
            "simulation_ready": False,
            "failure_reasons": [],
            "errors": [],
            "message": (
                "Mission is approved, but execution is "
                "blocked because the simulation is not ready."
            ),
            "simulation": simulation,
        }

    return {
        "mission_id": mission_id,
        "execution_authorized": True,
        "status": "READY_FOR_EXECUTION",
        "stage": "EXECUTION_GATE",
        "mission_status": mission_status,
        "execution_status": execution_status,
        "simulation_ready": True,
        "failure_reasons": [],
        "errors": [],
        "message": (
            "Mission is deterministically approved and "
            "the simulation is ready for execution."
        ),
        "simulation": simulation,
    }

def check_mission_execution_ready(mission_path: str) -> dict[str, object]:
    """Keep deterministic validation/readiness; reject unsupported logical identities first."""
    try:
        selection = resolve_mission_vehicle(load_mission_json(mission_path))
    except (ValueError, OSError, AttributeError) as exc:
        return {"execution_authorized": False, "status": "BLOCKED", "stage": "VEHICLE_SELECTION",
                "errors": [str(exc)], "failure_reasons": [], "simulation_ready": None}
    return {**_check_mission_execution_ready(mission_path), **selection.as_dict()}
