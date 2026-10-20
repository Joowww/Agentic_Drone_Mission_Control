"""Bounded Docker *metadata* reads. No exec, starts, controls or configuration reads.

Only selected non-secret fields are collected. A missing name or a transport error
is not termination evidence. Callers must bind a STOPPED observation to prior
identity evidence and revalidate it under the project execution/registry mutexes.
"""
from datetime import datetime
import json
import re
import subprocess

from tools.ros2_flight_control import CONTAINER
from tools.vehicle_execution_lock import utc_now

COMMAND_TIMEOUT_SECONDS = 3
HEX_ID = re.compile(r"[0-9a-f]{64}\Z")
INSPECT_FORMAT = ('{"container_id":{{json .Id}},"name":{{json .Name}},'
                  '"created_at":{{json .Created}},"image_id":{{json .Image}},'
                  '"state":{{json .State}}}')


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing/invalid Docker wall timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.year < 1970:
        raise ValueError("Missing/invalid Docker wall timestamp")
    return result


def environment_identity(value):
    """Incarnation, including state/termination times, for exact application binding."""
    return {key: value.get(key) for key in (
        "engine_id", "container_id", "name", "created_at", "image_id", "state")}


def stopped_reasons(value):
    try:
        if value.get("status") != "STOPPED":
            return [f"Environment is {value.get('status', 'UNKNOWN')}, not verified STOPPED"]
        state = value["state"]
        if (not value["engine_id"] or not HEX_ID.fullmatch(value["container_id"])
                or value["name"] != "/" + CONTAINER or not value["image_id"]
                or state["Status"] != "exited" or state["Running"] is not False
                or type(state["Pid"]) is not int or state["Pid"] != 0
                or any(state[k] is not False for k in ("Paused", "Restarting", "Dead"))):
            raise ValueError("Contradictory stopped-container identity/state")
        if not _timestamp(value["created_at"]) <= _timestamp(state["StartedAt"]) < _timestamp(state["FinishedAt"]):
            raise ValueError("Missing/contradictory Docker creation/start/finish wall times")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return [str(exc)]
    return []


def inspect_environment():
    """At most five read-only CLI calls, each <=3 s; preserve partial observations."""
    result = {"status": "UNKNOWN", "expected_container_name": CONTAINER,
              "started_at_utc": utc_now(), "command_timeout_seconds": COMMAND_TIMEOUT_SECONDS,
              "reasons": [], "operations": [], "unknown_fields": [],
              "clock": "Docker daemon wall timestamps; not ROS/simulation time"}

    def read(operation, arguments):
        try:
            value = subprocess.run(["docker", *arguments], capture_output=True, text=True,
                                   timeout=COMMAND_TIMEOUT_SECONDS, check=False)
            result["operations"].append({"operation": operation, "return_code": value.returncode,
                                         "error": value.stderr[-1024:] if value.returncode else None})
            if value.returncode:
                raise RuntimeError(f"{operation} returned {value.returncode}: {value.stderr[-1024:]}")
            return value.stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["operations"].append({"operation": operation, "return_code": None,
                                         "error": f"{type(exc).__name__}: {exc}"})
            raise

    try:
        try:
            engine = json.loads(read("engine_identity", ["info", "--format", "{{json .ID}}"]))
            if not isinstance(engine, str) or not engine.strip():
                raise ValueError("Docker engine identity unavailable")
            result["engine_id"] = engine
        except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError):
            result["status"] = "DOCKER_UNAVAILABLE"
            raise
        list_arguments = ["ps", "--all", "--no-trunc", "--filter", f"name=^/{CONTAINER}$", "--format", "{{.ID}}"]
        identifier = read("resolve_exact_name", list_arguments)
        if not identifier:
            result["status"] = "CONTAINER_ABSENT"
            result["reasons"].append("Accessible Docker daemon resolved no exact named container; absence does not prove termination")
        else:
            if not HEX_ID.fullmatch(identifier):
                raise ValueError("Container name did not resolve to exactly one full identity")
            value = json.loads(read("container_metadata", ["inspect", "--type", "container", "--format", INSPECT_FORMAT, identifier]))
            result.update(value)
            if value["container_id"] != identifier or value["name"] != "/" + CONTAINER:
                raise ValueError("Container replaced/renamed during collection")
            if (not isinstance(value["image_id"], str) or not value["image_id"]
                    or _timestamp(value["created_at"]) > _timestamp(value["state"]["StartedAt"])):
                raise ValueError("Missing/contradictory container image, creation or start identity")
            if (read("recheck_name", list_arguments) != identifier
                    or json.loads(read("recheck_engine", ["info", "--format", "{{json .ID}}"])) != engine):
                raise ValueError("Docker engine/container changed during collection")
            state = value["state"]
            if (state["Status"] == "running" and state["Running"] is True
                    and type(state["Pid"]) is int and state["Pid"] > 0
                    and all(state[k] is False for k in ("Paused", "Restarting", "Dead"))):
                result["status"] = "ACTIVE"
            else:
                result["status"] = "STOPPED"
                reasons = stopped_reasons(result)
                if reasons:
                    result["status"] = "UNKNOWN"
                    result["reasons"].extend(reasons)
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError, TypeError, KeyError) as exc:
        if result["status"] not in {"DOCKER_UNAVAILABLE", "CONTAINER_ABSENT"}:
            result["status"] = "UNKNOWN"
        result["reasons"].append(f"{type(exc).__name__}: {exc}")
    result["finished_at_utc"] = utc_now()
    result["unknown_fields"] = [k for k in ("engine_id", "container_id", "name", "created_at", "image_id", "state") if k not in result]
    if isinstance(result.get("state"), dict):
        result["unknown_fields"].extend('state.'+k for k in (
            "Status", "Running", "Pid", "Paused", "Restarting", "Dead", "StartedAt", "FinishedAt") if k not in result["state"])
    return result
