"""Strict QGroundControl ``.plan`` export for ONE ArduRover ground mission, with an independent verifier.

Profile ``QGC_PLAN_ARDUROVER_V1``. It is the ground counterpart of ``inputs.qgc_plan_export`` (ArduCopter,
``QGC_PLAN_ARDUCOPTER_V2``), which is not modified. The encoding follows the ArduPilot rover compatibility work of
commit 940a881cb (``inputs/qgroundcontrol_exporter.py``: firmwareType 3, vehicleType 10, no TAKEOFF, NAV_WAYPOINT
items at altitude 0, frame 3) and the SafeFlight Desktop importer's ArduRover whitelist (NAV_WAYPOINT,
DO_CHANGE_SPEED, ...; ``models/MissionPlan.py`` on ``feature/mission-plan-import``).

Items, in order:
  1. MAV_CMD_DO_CHANGE_SPEED (178), frame 2: param1 = 1 (ground speed), param2 = the AUTHORIZED speed limit in m/s;
  2. one MAV_CMD_NAV_WAYPOINT (16) per ground waypoint, frame 3 (relative), altitude 0, hold 0;
  3. when ``return_to_start``: a final NAV_WAYPOINT at the planned start coordinate. RTL is not used: Rover's RTL
     goes to the EFFECTIVE home (arming position), which equals the planned start only if armed there.
Never: NAV_TAKEOFF (22), NAV_LAND (21), a non-zero altitude, or a coordinate 0,0 (= "current position").

What the file does NOT establish: that ArduRover reaches each waypoint (WP_RADIUS, steering, obstacles), that the site
frame equals the simulator frame, or that any executor accepts the file. The multi-waypoint AUTO mission path has NO
executor in the repository today (see multiagent/supervisor/executors.py, ROVER_PLAN_EXECUTOR_CONTRACT).
"""
from __future__ import annotations

import json
import math

PROFILE = "QGC_PLAN_ARDUROVER_V1"
MAV_CMD_NAV_WAYPOINT, MAV_CMD_DO_CHANGE_SPEED = 16, 178
MAV_CMD_NAV_TAKEOFF, MAV_CMD_NAV_LAND, MAV_CMD_NAV_RETURN_TO_LAUNCH = 22, 21, 20
MAV_FRAME_MISSION, MAV_FRAME_GLOBAL_RELATIVE_ALT = 2, 3
MAV_AUTOPILOT_ARDUPILOTMEGA, MAV_TYPE_GROUND_ROVER = 3, 10
ALTITUDE_MODE_RELATIVE = 1
SPEED_TYPE_GROUND = 1
LATLON_DECIMALS, SPEED_DECIMALS, ALT_DECIMALS = 8, 3, 3
FORBIDDEN_COMMANDS = {MAV_CMD_NAV_TAKEOFF: "NAV_TAKEOFF", MAV_CMD_NAV_LAND: "NAV_LAND"}


class RoverExportRefused(ValueError):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def refusal_reasons(*, start: tuple, waypoints: list[dict], speed_mps, planned_home_amsl_m,
                    autopilot: str, vehicle_type: str) -> list[str]:
    reasons = []
    if autopilot != "ArduPilot" or vehicle_type != "ugv":
        reasons.append(f"{PROFILE} covers ArduPilot ground rovers only (vehicle: {autopilot}/{vehicle_type})")
    if not waypoints:
        reasons.append("at least one ground waypoint is required")
    if not (isinstance(start, (tuple, list)) and len(start) == 2 and _finite(*start)) or tuple(start) == (0, 0):
        reasons.append("the planned start coordinate must be explicit, finite and non-zero")
    for w in waypoints:
        if not _finite(w.get("latitude"), w.get("longitude")):
            reasons.append(f"{w.get('waypoint_id')}: latitude/longitude must be finite")
        elif w["latitude"] == 0 and w["longitude"] == 0:
            reasons.append(f"{w.get('waypoint_id')}: latitude/longitude 0,0 means 'current position'")
    if not _finite(speed_mps) or speed_mps <= 0:
        reasons.append("an authorized ground speed limit > 0 m/s is required (never invented)")
    if not _finite(planned_home_amsl_m):
        reasons.append("planned home AMSL altitude is required for plannedHomePosition (no placeholder)")
    return reasons


def _wp(jump_id: int, lat: float, lon: float) -> dict:
    return {"AMSLAltAboveTerrain": None, "Altitude": 0, "AltitudeMode": ALTITUDE_MODE_RELATIVE, "autoContinue": True,
            "command": MAV_CMD_NAV_WAYPOINT, "doJumpId": jump_id, "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
            "params": [0, 0, 0, None, round(lat, LATLON_DECIMALS), round(lon, LATLON_DECIMALS), 0],
            "type": "SimpleItem"}


def build_rover_plan(*, start: tuple, waypoints: list[dict], speed_mps: float, planned_home_amsl_m: float,
                     return_to_start: bool, autopilot: str = "ArduPilot", vehicle_type: str = "ugv") -> tuple[dict, dict]:
    """(plan, conversion log). ``waypoints``: [{waypoint_id, latitude, longitude}] in visiting order."""
    reasons = refusal_reasons(start=start, waypoints=waypoints, speed_mps=speed_mps,
                              planned_home_amsl_m=planned_home_amsl_m, autopilot=autopilot, vehicle_type=vehicle_type)
    if reasons:
        raise RoverExportRefused(reasons)
    speed = round(float(speed_mps), SPEED_DECIMALS)
    items = [{"autoContinue": True, "command": MAV_CMD_DO_CHANGE_SPEED, "doJumpId": 1, "frame": MAV_FRAME_MISSION,
              "params": [SPEED_TYPE_GROUND, speed, 0, 0, 0, 0, 0], "type": "SimpleItem"}]
    log = [{"doJumpId": 1, "source": f"authorized speed limit {speed} m/s (DO_CHANGE_SPEED, ground speed)"}]
    for w in waypoints:
        items.append(_wp(len(items) + 1, w["latitude"], w["longitude"]))
        log.append({"doJumpId": len(items), "source": w.get("waypoint_id")})
    if return_to_start:
        items.append(_wp(len(items) + 1, start[0], start[1]))
        log.append({"doJumpId": len(items), "source": "return_to_start -> NAV_WAYPOINT at the planned start "
                                                      "coordinate (not RTL: RTL targets the effective home)"})
    plan = {"fileType": "Plan", "geoFence": {"circles": [], "polygons": [], "version": 2},
            "groundStation": "QGroundControl",
            "mission": {"cruiseSpeed": speed, "firmwareType": MAV_AUTOPILOT_ARDUPILOTMEGA,
                        "globalPlanAltitudeMode": ALTITUDE_MODE_RELATIVE, "hoverSpeed": speed, "items": items,
                        "plannedHomePosition": [round(start[0], LATLON_DECIMALS), round(start[1], LATLON_DECIMALS),
                                                round(float(planned_home_amsl_m), ALT_DECIMALS)],
                        "vehicleType": MAV_TYPE_GROUND_ROVER, "version": 2},
            "rallyPoints": {"points": [], "version": 2}, "version": 1}
    return plan, {"profile": PROFILE, "items": log,
                  "semantics": [
                      {"element": "takeoff/landing", "status": "NOT_IN_PLAN", "detail": "ground mission: never present"},
                      {"element": "waypoint coordinates", "status": "EXACT", "detail": "8 decimals of the site points"},
                      {"element": "speed", "status": "CONDITIONED", "detail": "DO_CHANGE_SPEED = authorized limit; "
                       "the autopilot may drive slower (WP_SPEED, turns)"},
                      {"element": "return", "status": "CONDITIONED" if return_to_start else "NOT_IN_PLAN",
                       "detail": "NAV_WAYPOINT at the planned start coordinate"},
                      {"element": "obstacle avoidance / path", "status": "NOT_IN_PLAN",
                       "detail": "straight legs validated offline against the declared drivable area only"}],
                  "geofence": "empty: the drivable area is NOT exported as a fence (FENCE_* not verified)"}


def plan_bytes(plan: dict) -> bytes:
    return (json.dumps(plan, indent=4, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def verify_rover_plan(data: bytes, *, start: tuple, waypoints: list[dict], speed_mps: float,
                      return_to_start: bool) -> dict:
    """Checks of the FILE BYTES against the ground mission, written from the profile rules (not from build)."""
    checks = []
    add = lambda name, ok, detail="": checks.append({"check": name, "ok": bool(ok), "detail": detail})  # noqa: E731
    try:
        plan = json.loads(data)
    except ValueError as exc:
        return {"status": "FAILED", "checks": [{"check": "readable JSON", "ok": False, "detail": str(exc)}]}
    m = plan.get("mission") or {}
    add("top level", plan.get("fileType") == "Plan" and plan.get("version") == 1
        and (plan.get("geoFence") or {}).get("version") == 2 and (plan.get("rallyPoints") or {}).get("version") == 2)
    add("firmwareType 3 (ArduPilot)", m.get("firmwareType") == MAV_AUTOPILOT_ARDUPILOTMEGA)
    add("vehicleType 10 (ground rover)", m.get("vehicleType") == MAV_TYPE_GROUND_ROVER)
    items = m.get("items") or []
    commands = [i.get("command") for i in items]
    add("no aerial command (TAKEOFF/LAND)", not set(commands) & set(FORBIDDEN_COMMANDS),
        str([FORBIDDEN_COMMANDS[c] for c in commands if c in FORBIDDEN_COMMANDS]))
    add("numbering", [i.get("doJumpId") for i in items] == list(range(1, len(items) + 1)))
    expected = [(w["latitude"], w["longitude"]) for w in waypoints] + ([tuple(start)] if return_to_start else [])
    navs = [i for i in items if i.get("command") == MAV_CMD_NAV_WAYPOINT]
    add("waypoint count", len(navs) == len(expected), f"{len(navs)} vs {len(expected)}")
    tol = 0.5 * 10 ** -LATLON_DECIMALS
    for item, (lat, lon) in zip(navs, expected):
        p = item.get("params") or [None] * 7
        ok = (item.get("frame") == MAV_FRAME_GLOBAL_RELATIVE_ALT and item.get("Altitude") == 0 and p[6] == 0
              and _finite(p[4], p[5]) and abs(p[4] - lat) <= tol and abs(p[5] - lon) <= tol and p[0] == 0)
        add(f"waypoint item {item.get('doJumpId')}", ok)
    speeds = [i for i in items if i.get("command") == MAV_CMD_DO_CHANGE_SPEED]
    add("speed limit item", len(speeds) == 1 and speeds[0].get("params", [None, None])[1] == round(speed_mps, SPEED_DECIMALS)
        and speeds[0].get("frame") == MAV_FRAME_MISSION)
    other = sorted(set(commands) - {MAV_CMD_NAV_WAYPOINT, MAV_CMD_DO_CHANGE_SPEED})
    add("only profile commands", not other, str(other))
    return {"status": "FILE_MATCHES_EXPECTATIONS" if all(c["ok"] for c in checks) else "FAILED", "checks": checks,
            "compatibility": "NOT_ESTABLISHED: not uploaded to ArduRover nor read back"}
