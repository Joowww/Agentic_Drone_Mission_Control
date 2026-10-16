from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CHECK_SCRIPT = (
    PROJECT_ROOT
    / "simulation"
    / "ros2_gazebo"
    / "scripts"
    / "check_sim.sh"
)


def check_simulation_ready() -> dict[str, object]:
    """Check whether the ROS2/Gazebo/ArduPilot simulation is ready.

    This function is read-only with respect to vehicle execution:
    it does not arm, take off, or command any vehicle.
    """

    if not CHECK_SCRIPT.exists():
        return {
            "ready": False,
            "status": "ERROR",
            "return_code": None,
            "message": "Simulation check script not found.",
            "output": "",
        }

    result = subprocess.run(
        ["bash", str(CHECK_SCRIPT)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    output = "\n".join(
        part.strip()
        for part in (result.stdout, result.stderr)
        if part.strip()
    )

    return {
        "ready": result.returncode == 0,
        "status": "READY" if result.returncode == 0 else "NOT READY",
        "return_code": result.returncode,
        "message": (
            "Simulation is healthy and both drones are ready."
            if result.returncode == 0
            else "Simulation is not ready."
        ),
        "output": output,
    }