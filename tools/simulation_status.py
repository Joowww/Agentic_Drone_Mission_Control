from __future__ import annotations

import os
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from tools.simulation_profiles import get_profile, UnknownSimulationProfile
from tools.prearm_diagnostics import EVENT_PREFIX, SERVICE_TYPE


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CHECK_SCRIPT = (
    PROJECT_ROOT
    / "simulation"
    / "ros2_gazebo"
    / "scripts"
    / "check_sim.sh"
)
READINESS_TIMEOUT_S = 180


def _captured_text(value):
    # TimeoutExpired can carry bytes even when run(text=True) was requested.
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")


def _vehicle_checks(profile, stdout):
    """Only explicit script observations; a heading never completes a check."""
    observed = {}
    attempts = _prearm_attempts(profile, stdout)
    for line in stdout.splitlines():
        parts = line.strip().lstrip('.').strip().split()
        if (len(parts) == 4 and parts[0] == "TFG_READINESS_VEHICLE"
                and parts[2] in {"status", "prearm"} and parts[3] in {"PASS", "FAIL"}):
            observed[(parts[1], parts[2])] = parts[3]
    return [
        {"vehicle_id": v.vehicle_id, "interface": v.interface,
         "robot_name": v.robot_name, "sitl_executable": v.sitl_executable,
         "mission_executor_supported": v.mission_executor_supported,
         "status_topic": f"/ap/{v.interface}/status",
         "prearm_service": f"/ap/{v.interface}/prearm_check",
         "status_last_observed": observed.get((f"/ap/{v.interface}", "status"), "NOT_OBSERVED"),
         "prearm_last_observed": observed.get((f"/ap/{v.interface}", "prearm"), "NOT_OBSERVED")}
        | {"prearm_attempts": [a for a in attempts if a['interface'] == v.interface]}
        for v in profile.vehicles
    ]


def _prearm_attempts(profile, stdout):
    records = {}
    for line in stdout.splitlines():
        line = line.strip().lstrip('.').strip()
        if not line.startswith(EVENT_PREFIX):
            continue
        try:
            event = json.loads(line[len(EVENT_PREFIX):])
            service, attempt = event['service'], event['attempt']
            if (service not in profile.prearm_services or type(attempt) is not int
                    or not 1 <= attempt <= 18 or event.get('service_type') != SERVICE_TYPE
                    or event.get('interface') != service.split('/')[2]):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        key = service, attempt
        record = records.setdefault(key, {
            'interface': event['interface'], 'service': service, 'service_type': SERVICE_TYPE,
            'attempt': attempt, 'stdout': '', 'stderr': '', 'return_code': None,
            'timeout_s': event.get('timeout_s'), 'duration_wall_s': None,
            'outcome': 'INCOMPLETE_AT_CAPTURE', 'response': None,
            'started_at_utc': event.get('started_at_utc'),
            'started_monotonic_s': event.get('started_monotonic_s'),
            'timed_out': None, 'completed': False,
        })
        if event.get('event') == 'output' and event.get('stream') in ('stdout', 'stderr'):
            if isinstance(event.get('text'), str) and not record['completed']:
                record[event['stream']] += event['text']
                record['last_output_received_monotonic_s'] = event.get('received_monotonic_s')
        elif event.get('event') == 'completed':
            record.update(event)
            record['completed'] = True
    return list(records.values())


def check_simulation_ready(profile: str = "two_drones") -> dict[str, object]:
    """Check whether the ROS2/Gazebo/ArduPilot simulation is ready.

    This function is read-only with respect to vehicle execution:
    it does not arm, take off, or command any vehicle.
    """

    try:
        selected = get_profile(profile)
    except UnknownSimulationProfile as exc:
        return {"ready": False, "status": "BLOCKED", "return_code": None,
                "message": str(exc), "output": ""}

    if not CHECK_SCRIPT.exists():
        return {
            "ready": False,
            "status": "ERROR",
            "return_code": None,
            "message": "Simulation check script not found.",
            "output": "",
        }

    command = ["bash", str(CHECK_SCRIPT)]
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "TFG_SIM_PROFILE": selected.name},
            capture_output=True,
            text=True,
            timeout=READINESS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = _captured_text(exc.stdout), _captured_text(exc.stderr)
        return {
            "profile": selected.name, "ready": False, "status": "ERROR",
            "return_code": None, "timed_out": True, "partial_output": True,
            "error_type": type(exc).__name__, "error": str(exc),
            "message": "Readiness timed out; completion of checks is not confirmed.",
            "stdout": stdout, "stderr": stderr,
            "output": "\n".join(part.strip() for part in (stdout, stderr) if part.strip()),
            "command": command, "cwd": str(PROJECT_ROOT),
            "timeout_s": READINESS_TIMEOUT_S, "started_at_utc": started_at,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "duration_wall_s": time.monotonic() - started,
            "vehicles": _vehicle_checks(selected, stdout),
            "movement_authorized": False,
        }

    output = "\n".join(
        part.strip()
        for part in (result.stdout, result.stderr)
        if part.strip()
    )

    return {
        "profile": selected.name,
        "ready": result.returncode == 0,
        "status": "READY" if result.returncode == 0 else "NOT READY",
        "return_code": result.returncode,
        "message": (
            "Simulation infrastructure checks passed; no movement authorized."
            if result.returncode == 0
            else "Simulation is not ready."
        ),
        "output": output,
        "vehicles": _vehicle_checks(selected, result.stdout),
        "movement_authorized": False,
    }
