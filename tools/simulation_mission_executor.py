from __future__ import annotations

import math
import time

from inputs.json_loader import load_mission_json
from tools.mission_execution_gate import (
    check_mission_execution_ready,
)
from tools.ros2_flight_control import (
    FlightControlError,
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

SUPPORTED_ACTIONS = {
    "navigate",
}


class MissionExecutionError(RuntimeError):
    """Raised when deterministic mission execution fails."""


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
    deadline = (
        time.monotonic()
        + timeout_seconds
    )

    target_latitude = float(
        waypoint["latitude"]
    )

    target_longitude = float(
        waypoint["longitude"]
    )

    target_altitude_amsl = (
        launch_altitude_amsl_m
        + float(
            waypoint["altitude_m"]
        )
    )

    while time.monotonic() < deadline:
        status = _check_vehicle_safe(
            vehicle
        )

        if not status["armed"]:
            raise MissionExecutionError(
                "Vehicle became disarmed while "
                "navigating to a waypoint."
            )

        pose = get_vehicle_geopose(
            vehicle=vehicle,
        )

        horizontal_error = (
            _horizontal_distance_metres(
                pose["latitude"],
                pose["longitude"],
                target_latitude,
                target_longitude,
            )
        )

        altitude_error = abs(
            pose["altitude_amsl_m"]
            - target_altitude_amsl
        )

        if (
            horizontal_error
            <= HORIZONTAL_TOLERANCE_M
            and altitude_error
            <= ALTITUDE_TOLERANCE_M
        ):
            return {
                "reached": True,
                "waypoint_id": (
                    waypoint["waypoint_id"]
                ),
                "horizontal_error_m": (
                    horizontal_error
                ),
                "altitude_error_m": (
                    altitude_error
                ),
                "final_position": pose,
            }

        time.sleep(
            POLL_INTERVAL_SECONDS
        )

    raise MissionExecutionError(
        "Waypoint "
        f"{waypoint['waypoint_id']} "
        "was not reached within "
        f"{timeout_seconds} seconds."
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


def execute_approved_mission(
    mission_path: str,
    *,
    vehicle: str = "v1",
) -> dict[str, object]:
    """Execute an approved waypoint mission in simulation.

    Safety authorization is always checked before any flight command.

    The current executor supports:
    - ArduPilot multirotor simulation
    - waypoint navigation
    - action='navigate'

    Unsupported mission semantics are blocked rather than ignored.
    """

    gate = check_mission_execution_ready(
        mission_path
    )

    if not gate.get(
        "execution_authorized",
        False,
    ):
        return {
            "success": False,
            "status": "BLOCKED",
            "stage": "EXECUTION_GATE",
            "mission_id": gate.get(
                "mission_id"
            ),
            "message": (
                "Mission execution was not authorized."
            ),
            "gate": gate,
        }

    mission = load_mission_json(
        mission_path
    )

    compatibility_errors = (
        _execution_compatibility_errors(
            mission
        )
    )

    if compatibility_errors:
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
            "errors": compatibility_errors,
        }

    origin = get_vehicle_global_origin(
        vehicle=vehicle,
    )

    launch_position = get_vehicle_geopose(
        vehicle=vehicle,
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

    events: list[dict[str, object]] = []

    vehicle_may_be_armed = False

    try:
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

        waypoint_results = []

        for waypoint in mapped_waypoints:
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
                        waypoint[
                            "waypoint_id"
                        ]
                    ),
                    "success": (
                        send_result[
                            "success"
                        ]
                    ),
                }
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

        land_vehicle(
            vehicle=vehicle,
        )

        events.append(
            {
                "event": "LAND_COMMAND",
                "success": True,
            }
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

        return {
            "success": True,
            "status": "COMPLETED",
            "stage": "MISSION_EXECUTION",
            "mission_id": (
                mission.mission_id
            ),
            "vehicle": vehicle,
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
        recovery: dict[str, object] = {
            "landing_attempted": False,
            "landing_completed": False,
        }

        if vehicle_may_be_armed:
            recovery[
                "landing_attempted"
            ] = True

            try:
                land_vehicle(
                    vehicle=vehicle,
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

            except Exception as recovery_exc:
                recovery[
                    "recovery_error"
                ] = str(
                    recovery_exc
                )

        return {
            "success": False,
            "status": "FAILED",
            "stage": "MISSION_EXECUTION",
            "mission_id": (
                mission.mission_id
            ),
            "vehicle": vehicle,
            "error": str(exc),
            "events": events,
            "recovery": recovery,
        }