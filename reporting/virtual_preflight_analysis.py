"""Conservative analysis of the existing executor's returned event evidence."""
from __future__ import annotations

import math

from models.mission_definition import MissionDefinition
from tools.simulation_mission_executor import (
    ALTITUDE_TOLERANCE_M,
    HORIZONTAL_TOLERANCE_M,
    _horizontal_distance_metres,
)
from tools.simulation_mission_mapper import map_mission_route_to_simulation
from tools.simulated_vehicle import resolve_mission_vehicle


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _within(value: object, tolerance: float) -> bool:
    return _number(value) and 0 <= value <= tolerance


def _position(value: object) -> bool:
    return (
        isinstance(value, dict)
        and all(_number(value.get(key)) for key in (
            "latitude", "longitude", "altitude_amsl_m"))
        and -90 <= value["latitude"] <= 90
        and -180 <= value["longitude"] <= 180
    )


def analyze_executor_result(mission: MissionDefinition, raw: object, *, require_vehicle_identity=False,
                            legacy_v1=False) -> dict:
    """Missing, malformed or contradictory evidence fails closed.

    These are executor observations, not an independent telemetry recording.
    Recovery landing can never turn a failed mission into a successful rehearsal.
    """
    checks: dict[str, bool] = {}
    expected_ids = [wp.waypoint_id for wp in mission.route.waypoints]
    if not isinstance(raw, dict):
        return {"passed": False, "checks": {},
                "reasons": ["Executor did not return a result object."]}

    checks["completed"] = raw.get("status") == "COMPLETED" and raw.get("success") is True
    try:
        if legacy_v1:
            checks["identity"] = (raw.get("mission_id") == mission.mission_id
                                  and raw.get("vehicle") == "v1"
                                  and raw.get("stage") == "MISSION_EXECUTION")
        else:
            selected = resolve_mission_vehicle(mission)
            checks["identity"] = (
                raw.get("mission_id") == mission.mission_id and raw.get("vehicle") == selected.simulated_vehicle
                and raw.get("stage") == "MISSION_EXECUTION"
                and (not require_vehicle_identity and selected.simulated_vehicle == "v1"
                     or raw.get("vehicle_id") == selected.vehicle_id)
            )
    except ValueError:
        checks["identity"] = False
    checks["no_failure_or_recovery"] = not any(
        raw.get(key) for key in ("error", "errors", "recovery", "gate")
    )
    checks["count_and_return_flag"] = (
        type(raw.get("waypoints_completed")) is int
        and raw["waypoints_completed"] == len(expected_ids)
        and raw.get("return_to_home") is mission.route.return_to_home
    )
    events = raw.get("events")
    if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
        events = []
    names = [e.get("event") for e in events]
    expected = ["GUIDED_MODE", "ARM", "TAKEOFF_COMMAND", "TAKEOFF_REACHED"]
    for _ in expected_ids:
        expected.extend(["WAYPOINT_COMMAND", "WAYPOINT_REACHED"])
    if mission.route.return_to_home:
        expected.extend(["RETURN_HOME_COMMAND", "RETURN_HOME_REACHED"])
    expected.extend(["LAND_COMMAND", "LANDED"])
    checks["event_sequence"] = names == expected
    checks["commands_confirmed"] = bool(events) and all(
        e.get("success") is True for e in events
        if e.get("event") in {"GUIDED_MODE", "ARM", "TAKEOFF_COMMAND",
                              "WAYPOINT_COMMAND", "RETURN_HOME_COMMAND", "LAND_COMMAND"}
    )

    def reached(event: dict) -> bool:
        return (
            event.get("reached") is True
            and _within(event.get("horizontal_error_m"), HORIZONTAL_TOLERANCE_M)
            and _within(event.get("altitude_error_m"), ALTITUDE_TOLERANCE_M)
            and _position(event.get("final_position"))
        )

    waypoint_events = [e for e in events if e.get("event") == "WAYPOINT_REACHED"]
    command_events = [e for e in events if e.get("event") == "WAYPOINT_COMMAND"]
    checks["all_waypoints_reached"] = (
        [e.get("waypoint_id") for e in waypoint_events] == expected_ids
        and [e.get("waypoint_id") for e in command_events] == expected_ids
        and all(reached(e) for e in waypoint_events)
    )
    home_events = [e for e in events if e.get("event") == "RETURN_HOME_REACHED"]
    checks["return_home_reached"] = (
        len(home_events) == 1 and home_events[0].get("waypoint_id") == "SIMULATION_HOME"
        and reached(home_events[0])
        if mission.route.return_to_home else not home_events
    )
    takeoff = [e for e in events if e.get("event") == "TAKEOFF_REACHED"]
    takeoff_commands = [e for e in events if e.get("event") == "TAKEOFF_COMMAND"]
    checks["takeoff_reached"] = (
        len(takeoff_commands) == 1
        and takeoff_commands[0].get("altitude_m") == mission.route.waypoints[0].altitude_m
        and len(takeoff) == 1 and takeoff[0].get("reached") is True
        and _within(takeoff[0].get("altitude_error_m"), ALTITUDE_TOLERANCE_M)
        and takeoff[0].get("target_altitude_m") == mission.route.waypoints[0].altitude_m
        and _number(takeoff[0].get("altitude_amsl_m"))
    )
    landed = [e for e in events if e.get("event") == "LANDED"]
    checks["landed_and_disarmed"] = (
        len(landed) == 1 and landed[0].get("landed") is True
        and landed[0].get("armed") is False and landed[0].get("flying") is False
        and _position(landed[0].get("final_position"))
        and landed[0].get("final_position") == raw.get("final_position")
    )
    # Cross-check reported errors against returned positions and the same mapper
    # the executor uses; this still relies on the executor's telemetry samples.
    launch = raw.get("launch_position")
    consistent = _position(launch)
    if consistent:
        targets = map_mission_route_to_simulation(
            mission, simulation_home_latitude=launch["latitude"],
            simulation_home_longitude=launch["longitude"],
        )

        def matches_target(event: dict, target: dict) -> bool:
            pose = event.get("final_position")
            if not reached(event):
                return False
            horizontal = _horizontal_distance_metres(
                pose["latitude"], pose["longitude"], target["latitude"], target["longitude"],
            )
            altitude = abs(pose["altitude_amsl_m"] - launch["altitude_amsl_m"] - target["altitude_m"])
            return (
                horizontal <= HORIZONTAL_TOLERANCE_M and altitude <= ALTITUDE_TOLERANCE_M
                and math.isclose(horizontal, event["horizontal_error_m"], abs_tol=1e-6)
                and math.isclose(altitude, event["altitude_error_m"], abs_tol=1e-6)
            )

        consistent = len(waypoint_events) == len(targets) and all(
            matches_target(event, target) for event, target in zip(waypoint_events, targets)
        )
        if mission.route.return_to_home:
            home_target = {**launch, "altitude_m": mission.route.waypoints[-1].altitude_m}
            consistent = consistent and len(home_events) == 1 and matches_target(home_events[0], home_target)
        if checks["takeoff_reached"]:
            error = abs(takeoff[0]["altitude_amsl_m"] - launch["altitude_amsl_m"]
                        - mission.route.waypoints[0].altitude_m)
            consistent = consistent and math.isclose(error, takeoff[0]["altitude_error_m"], abs_tol=1e-6)
        else:
            consistent = False
    checks["position_evidence_consistent"] = bool(consistent)
    reasons = [f"Acceptance criterion failed: {name}" for name, ok in checks.items() if not ok]
    if raw.get("error"):
        reasons.insert(0, f"Executor error: {raw['error']}")
    return {
        "passed": all(checks.values()), "checks": checks,
        "expected_waypoint_ids": expected_ids,
        "observed_waypoint_ids": [e.get("waypoint_id") for e in waypoint_events],
        "tolerances": {"horizontal_m": HORIZONTAL_TOLERANCE_M,
                       "altitude_m": ALTITUDE_TOLERANCE_M},
        "reasons": reasons,
    }
