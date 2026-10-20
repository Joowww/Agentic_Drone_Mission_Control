from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

START_SCRIPT = (
    PROJECT_ROOT
    / "simulation"
    / "ros2_gazebo"
    / "scripts"
    / "start_sim.sh"
)

STOP_SCRIPT = (
    PROJECT_ROOT
    / "simulation"
    / "ros2_gazebo"
    / "scripts"
    / "stop_sim.sh"
)


def _run_script(
    script: Path,
    *,
    action: str,
    timeout_seconds: int,
) -> dict[str, object]:
    if not script.exists():
        return {
            "success": False,
            "status": "ERROR",
            "return_code": None,
            "action": action,
            "message": f"Simulation {action} script not found.",
            "output": "",
        }

    try:
        result = subprocess.run(
            ["bash", str(script)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )

    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")

        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")

        output = "\n".join(
            part.strip()
            for part in (stdout, stderr)
            if part.strip()
        )

        return {
            "success": False,
            "status": "TIMEOUT",
            "return_code": None,
            "action": action,
            "message": (
                f"Simulation {action} timed out after "
                f"{timeout_seconds} seconds."
            ),
            "output": output,
        }

    output = "\n".join(
        part.strip()
        for part in (result.stdout, result.stderr)
        if part.strip()
    )

    success = result.returncode == 0

    return {
        "success": success,
        "status": "SUCCESS" if success else "FAILED",
        "return_code": result.returncode,
        "action": action,
        "message": (
            f"Simulation {action} completed successfully."
            if success
            else f"Simulation {action} failed."
        ),
        "output": output,
    }


def start_simulation(gui: bool = True) -> dict[str, object]:
    """Start the ROS2/Gazebo/ArduPilot simulation environment.

    This starts the simulation infrastructure only.
    It does not arm, take off, or command any vehicle.
    """

    from tools.simulation_lifecycle import run_lifecycle
    return run_lifecycle("start", gui=gui)


def stop_simulation() -> dict[str, object]:
    """Stop the ROS2/Gazebo/ArduPilot simulation environment.

    This stops simulation processes only.
    It does not issue flight commands to any vehicle.
    """

    from tools.simulation_lifecycle import run_lifecycle
    return run_lifecycle("stop")


def restart_simulation(gui: bool = True):
    """One authorized stop/start transaction, no admission gap and no retry loop."""
    from tools.simulation_lifecycle import run_lifecycle
    return run_lifecycle("restart", gui=gui)
