from __future__ import annotations

import re
import shlex
import subprocess
import time
from datetime import datetime, timezone

from tools.execution_diagnostics import last_ros_call
from pathlib import Path

from tools.simulated_vehicle import validate_interface
from tools.vehicle_execution_lock import assert_execution_authority


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CONTAINER = "tfg-ardupilot-gazebo"

ROS_SETUP = """
source /opt/ros/humble/setup.bash
source /root/ardu_ws/install/setup.bash
"""

GLOBAL_RELATIVE_ALT_FRAME = 6
POSITION_ONLY_TYPE_MASK = 3576

GUIDED_MODE = 4
LAND_MODE = 9


class FlightControlError(RuntimeError):
    """Raised when a ROS2/ArduPilot command cannot be completed."""


def _run_ros_command(
    command: str,
    *,
    timeout_seconds: int = 30,
) -> str:
    full_command = f"""
{ROS_SETUP}
{command}
"""

    started = time.monotonic()
    diagnostic = {"command": command, "started_at_utc": datetime.now(timezone.utc).isoformat(),
                  "timeout_seconds": timeout_seconds, "return_code": None, "output": None,
                  "clock": "HOST_UTC_AND_MONOTONIC"}
    last_ros_call.set(diagnostic)
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER,
                "bash",
                "-lc",
                full_command,
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )

    except (subprocess.TimeoutExpired, OSError) as exc:
        diagnostic.update(error_type=type(exc).__name__, error=str(exc),
                          elapsed_wall_seconds=time.monotonic()-started,
                          finished_at_utc=datetime.now(timezone.utc).isoformat())
        error = FlightControlError(f"ROS2 command failed: {type(exc).__name__}: {exc}")
        error.diagnostic = diagnostic
        raise error from exc

    output = "\n".join(
        part.strip()
        for part in (
            result.stdout,
            result.stderr,
        )
        if part.strip()
    )

    diagnostic.update(return_code=result.returncode, output=output[-8192:],
                      output_truncated=len(output)>8192, elapsed_wall_seconds=time.monotonic()-started,
                      finished_at_utc=datetime.now(timezone.utc).isoformat())
    if result.returncode != 0:
        error = FlightControlError(f"ROS2 command failed with return code {result.returncode}:\n{output}")
        error.diagnostic = diagnostic
        raise error

    return output


def _extract_float(
    label: str,
    output: str,
) -> float:
    pattern = (
        rf"^\s*{re.escape(label)}:\s*"
        rf"([-+]?(?:\d+(?:\.\d*)?|\.\d+)"
        rf"(?:[eE][-+]?\d+)?)\s*$"
    )

    match = re.search(
        pattern,
        output,
        re.MULTILINE,
    )

    if match is None:
        raise FlightControlError(
            f"Could not parse '{label}' from ROS2 output."
        )

    return float(match.group(1))


def _extract_bool(
    label: str,
    output: str,
) -> bool:
    match = re.search(
        rf"^\s*{re.escape(label)}:\s*"
        r"(true|false)\s*$",
        output,
        re.MULTILINE,
    )

    if match is None:
        raise FlightControlError(
            f"Could not parse '{label}' from ROS2 output."
        )

    return match.group(1) == "true"


def _extract_int(
    label: str,
    output: str,
) -> int:
    match = re.search(
        rf"^\s*{re.escape(label)}:\s*"
        r"(\d+)\s*$",
        output,
        re.MULTILINE,
    )

    if match is None:
        raise FlightControlError(
            f"Could not parse '{label}' from ROS2 output."
        )

    return int(match.group(1))


def get_vehicle_status(
    vehicle: str = "v1",
) -> dict[str, object]:
    validate_interface(vehicle)
    output = _run_ros_command(
        (
            f"timeout 10 ros2 topic echo "
            f"/ap/{vehicle}/status --once"
        ),
        timeout_seconds=15,
    )

    return {
        "armed": _extract_bool(
            "armed",
            output,
        ),
        "mode": _extract_int(
            "mode",
            output,
        ),
        "flying": _extract_bool(
            "flying",
            output,
        ),
        "external_control": _extract_bool(
            "external_control",
            output,
        ),
        "failsafe_active": (
            "failsafe: []" not in output
        ),
        "raw_output": output,
    }


def get_vehicle_geopose(
    vehicle: str = "v1",
) -> dict[str, float]:
    validate_interface(vehicle)
    output = _run_ros_command(
        (
            f"timeout 10 ros2 topic echo "
            f"/ap/{vehicle}/geopose/filtered --once"
        ),
        timeout_seconds=15,
    )

    return {
        "latitude": _extract_float(
            "latitude",
            output,
        ),
        "longitude": _extract_float(
            "longitude",
            output,
        ),
        "altitude_amsl_m": _extract_float(
            "altitude",
            output,
        ),
    }


def get_vehicle_global_origin(
    vehicle: str = "v1",
) -> dict[str, float]:
    validate_interface(vehicle)
    output = _run_ros_command(
        (
            f"timeout 10 ros2 topic echo "
            f"/ap/{vehicle}/gps_global_origin/filtered "
            f"--once"
        ),
        timeout_seconds=15,
    )

    return {
        "latitude": _extract_float(
            "latitude",
            output,
        ),
        "longitude": _extract_float(
            "longitude",
            output,
        ),
        "altitude_amsl_m": _extract_float(
            "altitude",
            output,
        ),
    }


def switch_vehicle_mode(
    mode: int,
    *,
    vehicle: str = "v1",
) -> dict[str, object]:
    assert_execution_authority(vehicle)
    output = _run_ros_command(
        (
            f"ros2 service call "
            f"/ap/{vehicle}/mode_switch "
            f"ardupilot_msgs/srv/ModeSwitch "
            f"'{{mode: {mode}}}'"
        )
    )

    success = (
        "status=True" in output
        and f"curr_mode={mode}" in output
    )

    if not success:
        raise FlightControlError(
            f"Mode switch to {mode} was not accepted:\n"
            f"{output}"
        )

    return {
        "success": True,
        "mode": mode,
        "output": output,
    }


def arm_vehicle(
    *,
    vehicle: str = "v1",
) -> dict[str, object]:
    assert_execution_authority(vehicle)
    output = _run_ros_command(
        (
            f"ros2 service call "
            f"/ap/{vehicle}/arm_motors "
            f"ardupilot_msgs/srv/ArmMotors "
            f"'{{arm: true}}'"
        )
    )

    if "result=True" not in output:
        raise FlightControlError(
            f"Vehicle arming was not accepted:\n"
            f"{output}"
        )

    return {
        "success": True,
        "armed": True,
        "output": output,
    }


def takeoff_vehicle(
    altitude_m: float,
    *,
    vehicle: str = "v1",
) -> dict[str, object]:
    if altitude_m <= 0:
        raise ValueError(
            "Takeoff altitude must be greater than zero."
        )

    assert_execution_authority(vehicle)
    output = _run_ros_command(
        (
            f"ros2 service call "
            f"/ap/{vehicle}/experimental/takeoff "
            f"ardupilot_msgs/srv/Takeoff "
            f"'{{alt: {altitude_m}}}'"
        )
    )

    if "status=True" not in output:
        raise FlightControlError(
            f"Takeoff command was not accepted:\n"
            f"{output}"
        )

    return {
        "success": True,
        "altitude_m": altitude_m,
        "output": output,
    }


def send_global_position_target(
    latitude: float,
    longitude: float,
    altitude_m: float,
    *,
    vehicle: str = "v1",
) -> dict[str, object]:
    assert_execution_authority(vehicle)
    payload = f"""
{{
  header: {{
    frame_id: map
  }},
  coordinate_frame: {GLOBAL_RELATIVE_ALT_FRAME},
  type_mask: {POSITION_ONLY_TYPE_MASK},
  latitude: {latitude},
  longitude: {longitude},
  altitude: {altitude_m}
}}
""".strip()

    output = _run_ros_command(
        (
            "ros2 topic pub --once "
            "--qos-reliability best_effort "
            f"/ap/{vehicle}/cmd_gps_pose "
            "ardupilot_msgs/msg/GlobalPosition "
            f"{shlex.quote(payload)}"
        ),
        timeout_seconds=20,
    )

    if "publishing #1" not in output:
        raise FlightControlError(
            "Global position target was not published:\n"
            f"{output}"
        )

    return {
        "success": True,
        "latitude": latitude,
        "longitude": longitude,
        "altitude_m": altitude_m,
        "coordinate_frame": (
            GLOBAL_RELATIVE_ALT_FRAME
        ),
        "type_mask": POSITION_ONLY_TYPE_MASK,
        "output": output,
    }


def land_vehicle(
    *,
    vehicle: str = "v1",
) -> dict[str, object]:
    assert_execution_authority(vehicle)
    result = switch_vehicle_mode(
        LAND_MODE,
        vehicle=vehicle,
    )

    return {
        "success": True,
        "mode": LAND_MODE,
        "output": result["output"],
    }