from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import math
import sys
import time

from tools.vehicle_execution_lock import serialized_execution
from tools.simulated_vehicle import resolve_mission_vehicle, logical_vehicle_for_interface as resolve_vehicle_id

from inputs.json_loader import load_mission_json
from tools.mission_execution_gate import (
    check_mission_execution_ready,
)
from tools.ros2_flight_control import (
    GUIDED_MODE,
    arm_vehicle,
    get_vehicle_geopose,
    get_vehicle_global_origin,
    get_vehicle_status,
    land_vehicle,
    send_global_position_target,
    switch_vehicle_mode,
    takeoff_vehicle,
)
from tools.simulation_mission_mapper import (
    map_mission_route_to_simulation,
)


EARTH_RADIUS_M = 6_371_000.0

HORIZONTAL_TOLERANCE_M = 1.0
ALTITUDE_TOLERANCE_M = 0.75

POLL_INTERVAL_SECONDS = 2.0

TAKEOFF_TIMEOUT_SECONDS = 180
WAYPOINT_TIMEOUT_SECONDS = 180
LAND_TIMEOUT_SECONDS = 180

WAYPOINT_DIAGNOSTIC_SAMPLES = 12

SUPPORTED_ACTIONS = {
    "navigate",
}


class MissionExecutionError(RuntimeError):
    """Raised when deterministic mission execution fails."""


class WaypointWaitError(MissionExecutionError):
    """A failed waypoint wait with bounded observation evidence."""

    def __init__(self, message: str, diagnostic: dict[str, object]):
        super().__init__(message)
        self.diagnostic = diagnostic


def _emit_progress(
    message: str,
    *,
    enabled: bool,
) -> None:
    """Write operator progress without touching stdout.

    stderr is intentionally used because this executor will also be
    called from an MCP stdio server. Writing progress to stdout could
    corrupt the MCP transport.
    """

    if not enabled:
        return

    print(
        message,
        file=sys.stderr,
        flush=True,
    )


def _horizontal_distance_metres(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    lat1 = math.radians(latitude_1)
    lat2 = math.radians(latitude_2)

    delta_lat = math.radians(
        latitude_2 - latitude_1
    )

    delta_lon = math.radians(
        longitude_2 - longitude_1
    )

    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2.0) ** 2
    )

    c = 2.0 * math.atan2(
        math.sqrt(a),
        math.sqrt(1.0 - a),
    )

    return EARTH_RADIUS_M * c


def _check_vehicle_safe(
    vehicle: str,
) -> dict[str, object]:
    status = get_vehicle_status(
        vehicle=vehicle,
    )

    if status["failsafe_active"]:
        raise MissionExecutionError(
            "ArduPilot reported an active failsafe."
        )

    return status


def _wait_for_takeoff(
    *,
    vehicle: str,
    launch_altitude_amsl_m: float,
    target_altitude_m: float,
    timeout_seconds: int = TAKEOFF_TIMEOUT_SECONDS,
) -> dict[str, object]:
    deadline = (
        time.monotonic()
        + timeout_seconds
    )

    target_amsl = (
        launch_altitude_amsl_m
        + target_altitude_m
    )

    while time.monotonic() < deadline:
        status = _check_vehicle_safe(
            vehicle
        )

        pose = get_vehicle_geopose(
            vehicle=vehicle,
        )

        altitude_error = abs(
            pose["altitude_amsl_m"]
            - target_amsl
        )

        if (
            status["armed"]
            and status["flying"]
            and altitude_error
            <= ALTITUDE_TOLERANCE_M
        ):
            return {
                "reached": True,
                "target_altitude_m": (
                    target_altitude_m
                ),
                "altitude_amsl_m": (
                    pose["altitude_amsl_m"]
                ),
                "altitude_error_m": (
                    altitude_error
                ),
            }

        time.sleep(
            POLL_INTERVAL_SECONDS
        )

    raise MissionExecutionError(
        "Takeoff altitude was not reached "
        f"within {timeout_seconds} seconds."
    )


def _wait_for_waypoint(
    waypoint: dict[str, object],
    *,
    vehicle: str,
    launch_altitude_amsl_m: float,
    timeout_seconds: int = WAYPOINT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    deadline = started + timeout_seconds
    target_latitude = float(waypoint["latitude"])
    target_longitude = float(waypoint["longitude"])
    target_altitude_amsl = launch_altitude_amsl_m + float(waypoint["altitude_m"])
    samples: deque[dict[str, object]] = deque(maxlen=WAYPOINT_DIAGNOSTIC_SAMPLES)
    attempts = 0
    observation_count = 0
    last_observation = None
    last_status = None
    failure_stage = "WAIT"

    def failure(message: str, kind: str, cause: Exception | None = None):
        finished = time.monotonic()
        return WaypointWaitError(message, {
            "waypoint_id": waypoint["waypoint_id"], "vehicle": vehicle,
            "failure_kind": kind, "failure_stage": failure_stage,
            "position_outcome": "POSITION_NOT_REACHED" if observation_count else "NO_POSITION_OBSERVATION",
            "target": {"latitude": target_latitude, "longitude": target_longitude,
                       "altitude_relative_m": float(waypoint["altitude_m"]),
                       "altitude_amsl_m": target_altitude_amsl},
            "tolerances": {"horizontal_m": HORIZONTAL_TOLERANCE_M, "altitude_m": ALTITUDE_TOLERANCE_M},
            "started_at": started_at, "finished_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": finished - started, "timeout_seconds": timeout_seconds,
            "deadline_overrun_seconds": max(0.0, finished - deadline),
            "poll_attempts": attempts, "position_observations": observation_count,
            "last_status": last_status, "last_observation": last_observation,
            "last_observation_age_seconds": (
                finished - started - last_observation["elapsed_seconds"] if last_observation else None
            ),
            "samples_limit": WAYPOINT_DIAGNOSTIC_SAMPLES, "samples": list(samples),
            "error": {"type": type(cause).__name__ if cause else "TimeoutError", "message": message},
        })

    try:
        while time.monotonic() < deadline:
            attempts += 1
            sample = {"attempt": attempts, "elapsed_seconds": time.monotonic() - started}
            samples.append(sample)
            failure_stage = "STATUS_OBSERVATION"
            call_started = time.monotonic()
            status = _check_vehicle_safe(vehicle)
            sample["status_read_seconds"] = time.monotonic() - call_started
            last_status = dict(status)
            sample["status"] = last_status
            if not status["armed"]:
                failure_stage = "VEHICLE_STATE"
                raise MissionExecutionError("Vehicle became disarmed while navigating to a waypoint.")

            failure_stage = "POSITION_OBSERVATION"
            call_started = time.monotonic()
            pose = get_vehicle_geopose(vehicle=vehicle)
            sample["position_read_seconds"] = time.monotonic() - call_started
            observation_count += 1
            last_observation = {
                "position": dict(pose), "elapsed_seconds": time.monotonic() - started,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "horizontal_error_m": None, "altitude_error_m": None,
            }
            sample["observation"] = last_observation
            failure_stage = "POSITION_ERRORS"
            horizontal_error = _horizontal_distance_metres(
                pose["latitude"], pose["longitude"], target_latitude, target_longitude,
            )
            altitude_error = abs(pose["altitude_amsl_m"] - target_altitude_amsl)
            last_observation.update(horizontal_error_m=horizontal_error, altitude_error_m=altitude_error)
            if horizontal_error <= HORIZONTAL_TOLERANCE_M and altitude_error <= ALTITUDE_TOLERANCE_M:
                return {"reached": True, "waypoint_id": waypoint["waypoint_id"],
                        "horizontal_error_m": horizontal_error, "altitude_error_m": altitude_error,
                        "final_position": pose}
            failure_stage = "WAIT"
            time.sleep(POLL_INTERVAL_SECONDS)
    except Exception as exc:
        if samples:
            if failure_stage in {"STATUS_OBSERVATION", "POSITION_OBSERVATION"}:
                duration_key = "status_read_seconds" if failure_stage == "STATUS_OBSERVATION" else "position_read_seconds"
                samples[-1][duration_key] = time.monotonic() - call_started
            samples[-1]["error"] = {"type": type(exc).__name__, "message": str(exc), "stage": failure_stage}
        raise failure(str(exc), "WAIT_ERROR", exc) from exc

    raise failure(
        f"Waypoint {waypoint['waypoint_id']} was not reached within {timeout_seconds} seconds.", "TIMEOUT",
    )


def _wait_for_landing(
    *,
    vehicle: str,
    timeout_seconds: int = LAND_TIMEOUT_SECONDS,
) -> dict[str, object]:
    deadline = (
        time.monotonic()
        + timeout_seconds
    )

    while time.monotonic() < deadline:
        status = get_vehicle_status(
            vehicle=vehicle,
        )

        if (
            not status["armed"]
            and not status["flying"]
        ):
            pose = get_vehicle_geopose(
                vehicle=vehicle,
            )

            return {
                "landed": True,
                "armed": False,
                "flying": False,
                "final_position": pose,
            }

        time.sleep(
            POLL_INTERVAL_SECONDS
        )

    raise MissionExecutionError(
        "Vehicle did not complete landing "
        f"within {timeout_seconds} seconds."
    )


def _execution_compatibility_errors(
    mission,
) -> list[str]:
    errors: list[str] = []

    if mission.vehicle.vehicle_type != "multirotor":
        errors.append(
            "The current simulation executor "
            "supports multirotor vehicles only."
        )

    if mission.vehicle.autopilot not in {
        "ArduPilot",
        "unknown",
    }:
        errors.append(
            "The current simulation backend uses "
            "ArduPilot, but the mission requests "
            f"{mission.vehicle.autopilot}."
        )

    if mission.route.mode != "waypoints":
        errors.append(
            "The current simulation executor "
            "supports waypoint missions only."
        )

    unsupported_actions = sorted(
        {
            waypoint.action
            for waypoint
            in mission.route.waypoints
            if waypoint.action
            not in SUPPORTED_ACTIONS
        }
    )

    if unsupported_actions:
        errors.append(
            "Unsupported waypoint actions: "
            + ", ".join(
                unsupported_actions
            )
        )

    if not mission.route.waypoints:
        errors.append(
            "The mission must contain at least "
            "one waypoint."
        )

    elif (
        mission.route.waypoints[0].altitude_m
        <= 0
    ):
        errors.append(
            "The first waypoint altitude must "
            "be greater than zero for takeoff."
        )

    return errors


@serialized_execution
def _execute_resolved_mission(
    mission_path: str,
    *,
    vehicle: str = "v1",
    progress: bool = True,
) -> dict[str, object]:
    """Execute an approved waypoint mission in simulation.

    Safety authorization is always checked before any flight command.

    The current executor supports:
    - ArduPilot multirotor simulation
    - waypoint navigation
    - action='navigate'

    Unsupported mission semantics are blocked rather than ignored.

    Progress messages are written to stderr so the function remains
    compatible with MCP stdio transport.
    """

    _emit_progress(
        "[GATE] Checking deterministic mission authorization...",
        enabled=progress,
    )

    gate = check_mission_execution_ready(
        mission_path
    )

    if not gate.get(
        "execution_authorized",
        False,
    ):
        _emit_progress(
            "[GATE] BLOCKED - mission execution was not authorized.",
            enabled=progress,
        )

        return {
            "success": False,
            "status": "BLOCKED",
            "stage": "EXECUTION_GATE",
            "vehicle": vehicle, "vehicle_id": resolve_vehicle_id(vehicle),
            "mission_id": gate.get(
                "mission_id"
            ),
            "message": (
                "Mission execution was not authorized."
            ),
            "gate": gate,
        }

    _emit_progress(
        "[GATE] APPROVED - simulation is ready.",
        enabled=progress,
    )

    _emit_progress(
        "[MISSION] Loading MissionDefinition...",
        enabled=progress,
    )

    mission = load_mission_json(
        mission_path
    )

    try:
        resolve_mission_vehicle(mission, vehicle)
    except ValueError as exc:
        return {"success": False, "status": "BLOCKED", "stage": "VEHICLE_SELECTION",
                "vehicle": vehicle, "vehicle_id": resolve_vehicle_id(vehicle), "errors": [str(exc)]}

    compatibility_errors = (
        _execution_compatibility_errors(
            mission
        )
    )

    if compatibility_errors:
        _emit_progress(
            "[COMPATIBILITY] BLOCKED - mission contains "
            "unsupported execution semantics.",
            enabled=progress,
        )

        return {
            "success": False,
            "status": "BLOCKED",
            "stage": (
                "EXECUTION_COMPATIBILITY"
            ),
            "mission_id": (
                mission.mission_id
            ),
            "message": (
                "Mission is safe but is not "
                "supported by the current "
                "simulation executor."
            ),
            "vehicle": vehicle, "vehicle_id": mission.vehicle.vehicle_id,
            "errors": compatibility_errors,
        }

    _emit_progress(
        "[SIMULATION] Reading SITL global origin...",
        enabled=progress,
    )

    origin = get_vehicle_global_origin(
        vehicle=vehicle,
    )

    _emit_progress(
        "[SIMULATION] Reading real launch position...",
        enabled=progress,
    )

    launch_position = get_vehicle_geopose(
        vehicle=vehicle,
    )

    _emit_progress(
        (
            "[SIMULATION] Launch position: "
            f"{launch_position['latitude']:.8f}, "
            f"{launch_position['longitude']:.8f}, "
            f"{launch_position['altitude_amsl_m']:.2f} m AMSL"
        ),
        enabled=progress,
    )

    _emit_progress(
        "[MAPPING] Mapping mission geometry to Gazebo/SITL...",
        enabled=progress,
    )

    mapped_waypoints = (
        map_mission_route_to_simulation(
            mission,
            simulation_home_latitude=(
                launch_position["latitude"]
            ),
            simulation_home_longitude=(
                launch_position["longitude"]
            ),
        )
    )

    takeoff_altitude_m = float(
        mapped_waypoints[0][
            "altitude_m"
        ]
    )

    _emit_progress(
        (
            "[MAPPING] "
            f"{len(mapped_waypoints)} waypoint(s) mapped."
        ),
        enabled=progress,
    )

    events: list[dict[str, object]] = []

    vehicle_may_be_armed = False

    try:
        _emit_progress(
            "[GUIDED] Switching vehicle to GUIDED mode...",
            enabled=progress,
        )

        mode_result = switch_vehicle_mode(
            GUIDED_MODE,
            vehicle=vehicle,
        )

        events.append(
            {
                "event": "GUIDED_MODE",
                "success": (
                    mode_result["success"]
                ),
            }
        )

        _emit_progress(
            "[GUIDED] Mode accepted.",
            enabled=progress,
        )

        _emit_progress(
            "[ARM] Arming vehicle...",
            enabled=progress,
        )

        arm_result = arm_vehicle(
            vehicle=vehicle,
        )

        vehicle_may_be_armed = True

        events.append(
            {
                "event": "ARM",
                "success": (
                    arm_result["success"]
                ),
            }
        )

        _emit_progress(
            "[ARM] Vehicle armed.",
            enabled=progress,
        )

        _emit_progress(
            (
                "[TAKEOFF] Commanding takeoff to "
                f"{takeoff_altitude_m:.1f} m..."
            ),
            enabled=progress,
        )

        takeoff_result = takeoff_vehicle(
            takeoff_altitude_m,
            vehicle=vehicle,
        )

        events.append(
            {
                "event": "TAKEOFF_COMMAND",
                "success": (
                    takeoff_result["success"]
                ),
                "altitude_m": (
                    takeoff_altitude_m
                ),
            }
        )

        _emit_progress(
            "[TAKEOFF] Waiting for target altitude...",
            enabled=progress,
        )

        takeoff_reached = _wait_for_takeoff(
            vehicle=vehicle,
            launch_altitude_amsl_m=(
                launch_position[
                    "altitude_amsl_m"
                ]
            ),
            target_altitude_m=(
                takeoff_altitude_m
            ),
        )

        events.append(
            {
                "event": "TAKEOFF_REACHED",
                **takeoff_reached,
            }
        )

        _emit_progress(
            (
                "[TAKEOFF] Target reached "
                f"(error "
                f"{takeoff_reached['altitude_error_m']:.2f} m)."
            ),
            enabled=progress,
        )

        waypoint_results = []

        for index, waypoint in enumerate(
            mapped_waypoints,
            start=1,
        ):
            waypoint_id = str(
                waypoint["waypoint_id"]
            )

            _emit_progress(
                (
                    f"[WAYPOINT {index}/{len(mapped_waypoints)}] "
                    f"Sending {waypoint_id}..."
                ),
                enabled=progress,
            )

            send_result = (
                send_global_position_target(
                    float(
                        waypoint[
                            "latitude"
                        ]
                    ),
                    float(
                        waypoint[
                            "longitude"
                        ]
                    ),
                    float(
                        waypoint[
                            "altitude_m"
                        ]
                    ),
                    vehicle=vehicle,
                )
            )

            events.append(
                {
                    "event": (
                        "WAYPOINT_COMMAND"
                    ),
                    "waypoint_id": (
                        waypoint_id
                    ),
                    "success": (
                        send_result[
                            "success"
                        ]
                    ),
                }
            )

            _emit_progress(
                (
                    f"[WAYPOINT {index}/{len(mapped_waypoints)}] "
                    f"Waiting for {waypoint_id}..."
                ),
                enabled=progress,
            )

            reached = _wait_for_waypoint(
                waypoint,
                vehicle=vehicle,
                launch_altitude_amsl_m=(
                    launch_position[
                        "altitude_amsl_m"
                    ]
                ),
            )

            waypoint_results.append(
                reached
            )

            events.append(
                {
                    "event": (
                        "WAYPOINT_REACHED"
                    ),
                    **reached,
                }
            )

            _emit_progress(
                (
                    f"[WAYPOINT {index}/{len(mapped_waypoints)}] "
                    f"{waypoint_id} reached "
                    f"(horizontal error "
                    f"{reached['horizontal_error_m']:.2f} m, "
                    f"altitude error "
                    f"{reached['altitude_error_m']:.2f} m)."
                ),
                enabled=progress,
            )

        if mission.route.return_to_home:
            return_altitude_m = float(
                mapped_waypoints[-1][
                    "altitude_m"
                ]
            )

            return_target = {
                "waypoint_id": (
                    "SIMULATION_HOME"
                ),
                "latitude": (
                    launch_position[
                        "latitude"
                    ]
                ),
                "longitude": (
                    launch_position[
                        "longitude"
                    ]
                ),
                "altitude_m": (
                    return_altitude_m
                ),
            }

            _emit_progress(
                "[RETURN HOME] Sending launch position...",
                enabled=progress,
            )

            send_global_position_target(
                float(
                    return_target[
                        "latitude"
                    ]
                ),
                float(
                    return_target[
                        "longitude"
                    ]
                ),
                return_altitude_m,
                vehicle=vehicle,
            )

            events.append(
                {
                    "event": (
                        "RETURN_HOME_COMMAND"
                    ),
                    "success": True,
                }
            )

            _emit_progress(
                "[RETURN HOME] Waiting for home position...",
                enabled=progress,
            )

            home_reached = (
                _wait_for_waypoint(
                    return_target,
                    vehicle=vehicle,
                    launch_altitude_amsl_m=(
                        launch_position[
                            "altitude_amsl_m"
                        ]
                    ),
                )
            )

            events.append(
                {
                    "event": (
                        "RETURN_HOME_REACHED"
                    ),
                    **home_reached,
                }
            )

            _emit_progress(
                (
                    "[RETURN HOME] Home reached "
                    f"(horizontal error "
                    f"{home_reached['horizontal_error_m']:.2f} m)."
                ),
                enabled=progress,
            )

        _emit_progress(
            "[LAND] Commanding LAND mode...",
            enabled=progress,
        )

        land_vehicle(
            vehicle=vehicle,
        )

        events.append(
            {
                "event": "LAND_COMMAND",
                "success": True,
            }
        )

        _emit_progress(
            "[LAND] Waiting for touchdown and auto-disarm...",
            enabled=progress,
        )

        landing = _wait_for_landing(
            vehicle=vehicle,
        )

        vehicle_may_be_armed = False

        events.append(
            {
                "event": "LANDED",
                **landing,
            }
        )

        _emit_progress(
            "[LAND] Touchdown confirmed. Vehicle disarmed.",
            enabled=progress,
        )

        _emit_progress(
            "[COMPLETE] Mission completed successfully.",
            enabled=progress,
        )

        return {
            "success": True,
            "status": "COMPLETED",
            "stage": "MISSION_EXECUTION",
            "mission_id": (
                mission.mission_id
            ),
            "vehicle": vehicle, "vehicle_id": mission.vehicle.vehicle_id,
            "simulation_origin": origin,
            "launch_position": (
                launch_position
            ),
            "waypoints_completed": len(
                waypoint_results
            ),
            "return_to_home": (
                mission.route.return_to_home
            ),
            "events": events,
            "final_position": (
                landing[
                    "final_position"
                ]
            ),
            "message": (
                "Mission completed and vehicle "
                "landed successfully."
            ),
        }

    except Exception as exc:
        _emit_progress(
            (
                "[ERROR] Mission execution failed: "
                f"{exc}"
            ),
            enabled=progress,
        )

        recovery: dict[str, object] = {
            "landing_attempted": False,
            "landing_completed": False,
        }

        if vehicle_may_be_armed:
            recovery[
                "landing_attempted"
            ] = True

            _emit_progress(
                "[RECOVERY] Vehicle may be armed. Attempting LAND...",
                enabled=progress,
            )

            try:
                land_vehicle(
                    vehicle=vehicle,
                )

                _emit_progress(
                    "[RECOVERY] Waiting for touchdown...",
                    enabled=progress,
                )

                landing = (
                    _wait_for_landing(
                        vehicle=vehicle,
                    )
                )

                recovery[
                    "landing_completed"
                ] = True

                recovery[
                    "landing"
                ] = landing

                _emit_progress(
                    "[RECOVERY] Emergency landing completed.",
                    enabled=progress,
                )

            except Exception as recovery_exc:
                recovery[
                    "recovery_error"
                ] = str(
                    recovery_exc
                )

                _emit_progress(
                    (
                        "[RECOVERY] Landing recovery failed: "
                        f"{recovery_exc}"
                    ),
                    enabled=progress,
                )

        return {
            "success": False,
            "status": "FAILED",
            "stage": "MISSION_EXECUTION",
            "mission_id": (
                mission.mission_id
            ),
            "vehicle": vehicle, "vehicle_id": mission.vehicle.vehicle_id,
            "error": str(exc),
            "waypoint_diagnostic": exc.diagnostic if isinstance(exc, WaypointWaitError) else None,
            "events": events,
            "recovery": recovery,
        }


def execute_approved_mission(mission_path: str, *, vehicle: str | None = None,
                             progress: bool = True) -> dict[str, object]:
    """Resolve the mission binding before reservation; an explicit override must match."""
    try:
        mission = load_mission_json(mission_path)
        selection = resolve_mission_vehicle(mission, vehicle)
    except (ValueError, OSError, AttributeError) as exc:
        return {"success": False, "status": "BLOCKED", "stage": "VEHICLE_SELECTION",
                "errors": [str(exc)], "message": "Cannot select a supported mission vehicle."}
    raw = _execute_resolved_mission(mission_path, vehicle=selection.simulated_vehicle, progress=progress)
    if isinstance(raw, dict) and raw.get("stage") == "VEHICLE_EXCLUSION":
        raw = {**raw, "vehicle_id": selection.vehicle_id}
    return raw
