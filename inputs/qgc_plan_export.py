"""Strict QGroundControl ``.plan`` export for ONE ArduCopter mission, with an independent verifier.

Profile ``QGC_PLAN_ARDUCOPTER_V2`` is the only destination implemented. Every ``.plan`` in the repository
(packages, interactive session, Hermes finalizations) goes through ``build_plan``.

Sources (consulted 27/10/2026):
- QGC plan format: https://docs.qgroundcontrol.com/master/en/qgc-dev-guide/file_formats/plan.html
  (plannedHomePosition = latitude, longitude, AMSL altitude; geoFence/rallyPoints required, version 2).
  Documentation of QGC master; the QGroundControl version that will import the file is not known.
- ArduCopter documentation (master): mission-command-list.html, common-mavlink-mission-command-messages-mav_cmd.html.
- ArduPilot SOURCE at the commit the SITL logs report (``ArduCopter V4.8.0-dev (755258db)``), local clean tree
  ``~/TFG/ardupilot_ros2_ws/src/ardupilot``: ``ArduCopter/mode_auto.cpp`` (do_takeoff, do_nav_wp, set_next_wp,
  do_land, do_change_speed) and ``libraries/AP_Mission/AP_Mission.cpp`` (sanity_check_params, speed fields).

Meaning preserved (``semantics`` in the conversion log lists every element as EXACT, CONDITIONED or NOT_IN_PLAN):
the repository's executor (H2, GUIDED) takes off to the first waypoint altitude, visits each waypoint, returns to
the launch COORDINATE at the last altitude when ``return_to_home`` is true, and always commands LAND. This profile
expresses that with an explicit ``NAV_LAND`` carrying the coordinate (ArduCopter flies there at the current altitude,
then lands); it does not use RTL, whose landing depends on RTL_ALT_FINAL_M and which climbs to RTL_ALT_M first.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from models.mission_definition import MissionDefinition

PROFILE = "QGC_PLAN_ARDUCOPTER_V2"
SUPERSEDED_PROFILES = {"QGC_PLAN_ARDUCOPTER_V1": "ended with NAV_RETURN_TO_LAUNCH (landing conditioned by "
                                                 "RTL_ALT_FINAL_M, climb to RTL_ALT_M) and DO_CHANGE_SPEED param3=-1"}
MAV_CMD_NAV_WAYPOINT, MAV_CMD_NAV_LAND, MAV_CMD_NAV_TAKEOFF = 16, 21, 22
MAV_CMD_NAV_RETURN_TO_LAUNCH, MAV_CMD_DO_CHANGE_SPEED = 20, 178
MAV_FRAME_MISSION, MAV_FRAME_GLOBAL_RELATIVE_ALT = 2, 3
MAV_AUTOPILOT_ARDUPILOTMEGA, MAV_TYPE_QUADROTOR = 3, 2
ALTITUDE_MODE_RELATIVE = 1
SPEED_TYPE_GROUND = 1
LATLON_DECIMALS, ALT_DECIMALS, SPEED_DECIMALS = 8, 3, 3
SUPPORTED_ACTIONS = ("navigate",)
SOURCE_CODE = "ArduPilot 755258db"
_DOCS = "ardupilot.org/copter mission-command-list + mav_cmd pages"

# What each exported MAVLink item must contain, written from the sources above and NOT from build_plan.
# "params" maps param index (0-based) -> required value (None = NaN/null in the .plan).
MAVLINK_EXPECTATIONS = {
    MAV_CMD_NAV_TAKEOFF: {
        "name": "MAV_CMD_NAV_TAKEOFF", "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
        "params": {0: 0, 1: 0, 2: 0, 3: None}, "position": "lat/lon not used by Copter; alt > 0 above home",
        "sources": [_DOCS, f"{SOURCE_CODE} ModeAuto::do_takeoff (climbs above current position); "
                    "AP_Mission::sanity_check_params (only param4 may be NaN)"]},
    MAV_CMD_NAV_WAYPOINT: {
        "name": "MAV_CMD_NAV_WAYPOINT", "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
        "params": {0: 0, 1: 0, 2: 0, 3: None},
        "position": "lat/lon non-zero (0 = current position); alt > 0 (0 = keep current altitude)",
        "sources": [_DOCS, f"{SOURCE_CODE} ModeAuto::get_loc_from_cmd, do_nav_wp (p1 = hold s), set_next_wp"]},
    MAV_CMD_DO_CHANGE_SPEED: {
        "name": "MAV_CMD_DO_CHANGE_SPEED", "frame": MAV_FRAME_MISSION,
        "params": {0: SPEED_TYPE_GROUND, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}, "position": "param2 = speed m/s > 0",
        "sources": [_DOCS, f"{SOURCE_CODE} AP_Mission (speed_type, target_ms, throttle_pct 0 = no change); "
                    "ModeAuto::do_change_speed (types 0/1 set horizontal speed)"]},
    MAV_CMD_NAV_LAND: {
        "name": "MAV_CMD_NAV_LAND", "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
        "params": {0: 0, 1: 0, 2: 0, 3: None, 6: 0},
        "position": "lat/lon non-zero: fly there at current altitude, then land; alt ignored (forced 0)",
        "sources": [_DOCS, f"{SOURCE_CODE} ModeAuto::do_land (location given -> FlyToLocation at current alt)"]},
}


class ExportRefused(ValueError):
    """The mission cannot be expressed faithfully in this profile; reasons are listed, nothing is dropped."""

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _item(command: int, jump_id: int, frame: int, params: list, altitude=None) -> dict:
    relative = frame == MAV_FRAME_GLOBAL_RELATIVE_ALT
    return {"AMSLAltAboveTerrain": None,
            "Altitude": altitude if relative else 0,
            "AltitudeMode": ALTITUDE_MODE_RELATIVE,
            "autoContinue": True, "command": command, "doJumpId": jump_id, "frame": frame,
            "params": params, "type": "SimpleItem"}


def refusal_reasons(mission: MissionDefinition, planned_home_amsl_m=None) -> list[str]:
    reasons = []
    if mission.vehicle.autopilot != "ArduPilot" or mission.vehicle.vehicle_type != "multirotor":
        reasons.append(f"{PROFILE} covers ArduPilot multirotors only (mission: "
                       f"{mission.vehicle.autopilot}/{mission.vehicle.vehicle_type})")
    if mission.route.mode != "waypoints" or not mission.route.waypoints:
        reasons.append("a waypoint route is required")
    if mission.route.home is None:
        reasons.append("a planned home position is required")
    elif mission.route.home.altitude_m != 0:
        reasons.append("mission altitudes must be relative to home (home altitude_m = 0); a non-zero home "
                       "altitude leaves the waypoint reference ambiguous")
    unsupported = sorted({w.action for w in mission.route.waypoints} - set(SUPPORTED_ACTIONS))
    if unsupported:
        reasons.append(f"unsupported waypoint action(s) {unsupported}: not exported as plain waypoints")
    if any(w.altitude_m <= 0 for w in mission.route.waypoints):
        reasons.append("waypoint altitude 0 means 'keep the current altitude' in ArduCopter; not exported")
    if any(w.latitude == 0 and w.longitude == 0 for w in mission.route.waypoints):
        reasons.append("latitude/longitude 0,0 means 'current position' in ArduCopter; not exported")
    if planned_home_amsl_m is None or isinstance(planned_home_amsl_m, bool) or \
            not isinstance(planned_home_amsl_m, (int, float)) or not math.isfinite(planned_home_amsl_m):
        reasons.append("planned home AMSL altitude is required for plannedHomePosition; the mission only has "
                       "altitudes relative to home and no placeholder is written")
    return reasons


LABEL_SCOPE = ("EXACT: the named element of the file equals the corresponding element of the mission (or of the H2 "
               "record where stated). It does not claim dynamic equivalence with H2, QGroundControl or vehicle "
               "compatibility, or any flight guarantee. CONDITIONED: the element is present but its effect depends on "
               "something outside the file (autopilot parameters, arming position). NOT_IN_PLAN: not expressed.")


def semantics(mission: MissionDefinition, *, return_coordinate_is_observed_launch: bool = False) -> list[dict]:
    """Element-by-element correspondence between the mission's intent (as the executor runs it) and the file.

    Labels follow LABEL_SCOPE: they compare one element each, never whole behaviour."""
    speeds = sorted({w.speed_kmh for w in mission.route.waypoints if w.speed_kmh is not None})
    rows = [
        ("takeoff", "CONDITIONED", "NAV_TAKEOFF to the first waypoint altitude, relative to the EFFECTIVE home (set "
         "at arming); equals the executor's launch-relative target only if armed at the planned takeoff position"),
        ("waypoint coordinate values", "EXACT", "item lat/lon/alt equal the mission waypoint values (8 decimals; "
         "degE7 transport quantization reported); says nothing about the flown path"),
        ("waypoint acceptance", "CONDITIONED", "ArduCopter accepts within WP_RADIUS_M and does not stop at a "
         "waypoint followed by another navigation item (hold 0); the H2 executor sent targets one by one and "
         "accepted at 1.0 m horizontal / 0.75 m vertical"),
        ("hold parameter", "EXACT", "param1 = 0, matching the mission model, which has no hold field; the "
         "vehicle's dwell is not implied (see waypoint acceptance)"),
        ("yaw", "CONDITIONED", "not specified by the mission (param4 NaN): WP_YAW_BEHAVIOR decides; the executor "
         "commanded no yaw either"),
        ("speed", "CONDITIONED" if speeds else "NOT_IN_PLAN",
         f"requested {speeds} km/h as DO_CHANGE_SPEED (maximum horizontal speed, bounded by the autopilot); the "
         "GUIDED executor did not apply speed_kmh" if speeds else "no speed requested: autopilot WP_SPD applies"),
        ("return coordinate", "EXACT" if return_coordinate_is_observed_launch else "CONDITIONED",
         ("NAV_LAND coordinate = the planned home coordinate"
          + (", which equals the launch coordinate recorded by H2" if return_coordinate_is_observed_launch else
             "; the executor returned to the OBSERVED launch position, equal only if the vehicle launches at the "
             "planned coordinate")
          + ". The motion differs: H2 sent a GUIDED target and waited within 1.0 m before LAND; ArduCopter flies "
            "the NAV_LAND leg at the current altitude, then descends (not RTL, not the effective home)")
         if mission.route.return_to_home else "no return: NAV_LAND coordinate = the last waypoint coordinate"),
        ("landing command", "EXACT", "an explicit NAV_LAND item is present, as H2 always commanded LAND; it does not "
         "depend on RTL_ALT_FINAL_M. Descent and touchdown behaviour depend on LAND_* parameters"),
        ("failsafe actions", "NOT_IN_PLAN", "low battery / wind / link loss actions are autopilot parameters "
         "(FS_*), not mission items; the mission's failsafe block is not expressed"),
        ("planning inputs", "NOT_IN_PLAN", "battery, wind and constraints are validation inputs only"),
    ]
    return [{"element": e, "status": s, "detail": d} for e, s, d in rows]


def build_plan(mission: MissionDefinition, *, planned_home_amsl_m: float, mav_type: int = MAV_TYPE_QUADROTOR,
               return_coordinate_is_observed_launch: bool = False) -> tuple[dict, dict]:
    """Return (plan, conversion log). Deterministic: the same mission and home AMSL give the same dict."""
    reasons = refusal_reasons(mission, planned_home_amsl_m)
    if reasons:
        raise ExportRefused(reasons)
    home, waypoints = mission.route.home, mission.route.waypoints
    ll = lambda v: round(v, LATLON_DECIMALS)  # noqa: E731
    alt = lambda v: round(v, ALT_DECIMALS)  # noqa: E731
    items, log = [], []
    takeoff_alt = alt(waypoints[0].altitude_m)
    items.append(_item(MAV_CMD_NAV_TAKEOFF, 1, MAV_FRAME_GLOBAL_RELATIVE_ALT,
                       [0, 0, 0, None, ll(home.latitude), ll(home.longitude), takeoff_alt], takeoff_alt))
    log.append({"doJumpId": 1, "source": "takeoff to the first waypoint altitude (as the SITL executor does)"})
    current_speed = None
    for waypoint in waypoints:
        if waypoint.speed_kmh is not None and waypoint.speed_kmh != current_speed:
            speed = round(waypoint.speed_kmh / 3.6, SPEED_DECIMALS)
            items.append(_item(MAV_CMD_DO_CHANGE_SPEED, len(items) + 1, MAV_FRAME_MISSION,
                               [SPEED_TYPE_GROUND, speed, 0, 0, 0, 0, 0]))
            log.append({"doJumpId": len(items), "source": f"{waypoint.waypoint_id}.speed_kmh={waypoint.speed_kmh}",
                        "note": "REQUESTED maximum speed; runs when the preceding NAV item completes; not validated"})
            current_speed = waypoint.speed_kmh
        altitude = alt(waypoint.altitude_m)
        items.append(_item(MAV_CMD_NAV_WAYPOINT, len(items) + 1, MAV_FRAME_GLOBAL_RELATIVE_ALT,
                           [0, 0, 0, None, ll(waypoint.latitude), ll(waypoint.longitude), altitude], altitude))
        log.append({"doJumpId": len(items), "source": waypoint.waypoint_id})
    target = (home.latitude, home.longitude) if mission.route.return_to_home else \
        (waypoints[-1].latitude, waypoints[-1].longitude)
    items.append(_item(MAV_CMD_NAV_LAND, len(items) + 1, MAV_FRAME_GLOBAL_RELATIVE_ALT,
                       [0, 0, 0, None, ll(target[0]), ll(target[1]), 0], 0))
    log.append({"doJumpId": len(items), "source": "return_to_home -> land at the planned home coordinate"
                if mission.route.return_to_home else "no return -> land at the last waypoint coordinate"})
    cruise = round(mission.vehicle.cruise_speed_kmh / 3.6, SPEED_DECIMALS)
    plan = {
        "fileType": "Plan",
        "geoFence": {"circles": [], "polygons": [], "version": 2},
        "groundStation": "QGroundControl",
        "mission": {"cruiseSpeed": cruise, "firmwareType": MAV_AUTOPILOT_ARDUPILOTMEGA,
                    "globalPlanAltitudeMode": ALTITUDE_MODE_RELATIVE, "hoverSpeed": cruise, "items": items,
                    "plannedHomePosition": [ll(home.latitude), ll(home.longitude), alt(planned_home_amsl_m)],
                    "vehicleType": mav_type, "version": 2},
        "rallyPoints": {"points": [], "version": 2},
        "version": 1,
    }
    return plan, {"profile": PROFILE, "items": log, "label_scope": LABEL_SCOPE,
                  "semantics": semantics(mission, return_coordinate_is_observed_launch=return_coordinate_is_observed_launch),
                  "speed_fields": {"hoverSpeed_cruiseSpeed_mps": cruise,
                                   "meaning": "QGC planning fields; not converted into a commanded speed"},
                  "precision": {"latlon_decimals": LATLON_DECIMALS, "altitude_decimals": ALT_DECIMALS,
                                "transport": "MISSION_ITEM_INT carries degE7 (~1.1 cm); see verifier"},
                  "geofence": "empty: site perimeter/exclusions are NOT exported as a fence (FENCE_* not verified)"}


def plan_bytes(plan: dict) -> bytes:
    return (json.dumps(plan, indent=4, ensure_ascii=False) + "\n").encode("utf-8")


def _close(a, b, tol=0.5 * 10 ** -LATLON_DECIMALS):
    return isinstance(a, (int, float)) and not isinstance(a, bool) and abs(a - b) <= tol


def check_mavlink_item(item: dict) -> list[str]:
    """Problems of ONE item against MAVLINK_EXPECTATIONS (command, frame, fixed params, position rules)."""
    expected = MAVLINK_EXPECTATIONS.get(item.get("command"))
    if expected is None:
        return [f"command {item.get('command')} is not part of {PROFILE}"]
    problems = []
    params = item.get("params")
    if not isinstance(params, list) or len(params) != 7:
        return [f"{expected['name']}: params must be a list of 7 values"]
    if item.get("frame") != expected["frame"]:
        problems.append(f"{expected['name']}: frame {item.get('frame')} != {expected['frame']}")
    for index, value in expected["params"].items():
        if params[index] != value or (value is None) != (params[index] is None):
            problems.append(f"{expected['name']}: param{index + 1} {params[index]!r} != {value!r}")
    numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)  # noqa: E731
    command = item["command"]
    if command in (MAV_CMD_NAV_WAYPOINT, MAV_CMD_NAV_LAND):
        if not (numeric(params[4]) and numeric(params[5])) or (params[4] == 0 and params[5] == 0):
            problems.append(f"{expected['name']}: lat/lon must be explicit and non-zero")
    if command in (MAV_CMD_NAV_WAYPOINT, MAV_CMD_NAV_TAKEOFF):
        if not numeric(params[6]) or params[6] <= 0 or item.get("Altitude") != params[6]:
            problems.append(f"{expected['name']}: altitude must be > 0 and equal to Altitude")
    if command == MAV_CMD_DO_CHANGE_SPEED and not (numeric(params[1]) and params[1] > 0):
        problems.append("MAV_CMD_DO_CHANGE_SPEED: speed must be > 0")
    if item.get("AltitudeMode") != ALTITUDE_MODE_RELATIVE or item.get("autoContinue") is not True \
            or item.get("type") != "SimpleItem":
        problems.append(f"{expected['name']}: AltitudeMode/autoContinue/type")
    return problems


def verify_plan(path: Path, mission: MissionDefinition, *, planned_home_amsl_m: float) -> dict:
    """Three separate results: MAVLink expectations, correspondence with the mission, and the project importer.

    ``status`` FILE_MATCHES_EXPECTATIONS covers only the first two. Compatibility with a QGroundControl version or
    with the vehicle is NOT established here: it requires importing, uploading and reading back.
    """
    checks = []
    add = lambda name, ok, detail="": checks.append({"check": name, "ok": bool(ok), "detail": detail})  # noqa: E731
    try:
        plan = json.loads(Path(path).read_bytes())
    except (OSError, ValueError) as exc:
        return {"status": "FAILED", "checks": [{"check": "readable JSON", "ok": False, "detail": str(exc)}],
                "importer_readback": {"status": "NOT_RUN"}, "compatibility": "NOT_ESTABLISHED"}
    m = plan.get("mission") or {}
    add("top level", plan.get("fileType") == "Plan" and plan.get("version") == 1
        and (plan.get("geoFence") or {}).get("version") == 2 and (plan.get("rallyPoints") or {}).get("version") == 2)
    add("mission header", m.get("version") == 2 and m.get("firmwareType") == MAV_AUTOPILOT_ARDUPILOTMEGA
        and m.get("globalPlanAltitudeMode") == ALTITUDE_MODE_RELATIVE)
    home = mission.route.home
    planned = m.get("plannedHomePosition") or [None, None, None]
    add("plannedHomePosition (lat, lon, AMSL)", _close(planned[0], home.latitude) and _close(planned[1], home.longitude)
        and isinstance(planned[2], (int, float)) and abs(planned[2] - planned_home_amsl_m) <= 0.0005)
    items = m.get("items") or []
    add("numbering", [i.get("doJumpId") for i in items] == list(range(1, len(items) + 1)), "doJumpId 1..n")
    for item in items:
        problems = check_mavlink_item(item)
        add(f"MAVLink item {item.get('doJumpId')} ({item.get('command')})", not problems, "; ".join(problems))
    # Expected sequence derived from the mission, independently of build_plan.
    expected = [(MAV_CMD_NAV_TAKEOFF, None, None, mission.route.waypoints[0].altitude_m)]
    current = None
    for w in mission.route.waypoints:
        if w.speed_kmh is not None and w.speed_kmh != current:
            expected.append((MAV_CMD_DO_CHANGE_SPEED, None, None, round(w.speed_kmh / 3.6, SPEED_DECIMALS)))
            current = w.speed_kmh
        expected.append((MAV_CMD_NAV_WAYPOINT, w.latitude, w.longitude, w.altitude_m))
    end = (home.latitude, home.longitude) if mission.route.return_to_home else \
        (mission.route.waypoints[-1].latitude, mission.route.waypoints[-1].longitude)
    expected.append((MAV_CMD_NAV_LAND, *end, 0))
    add("command sequence", [i.get("command") for i in items] == [e[0] for e in expected],
        f"{[i.get('command') for i in items]}")
    worst = 0.0
    for item, (command, lat, lon, value) in zip(items, expected):
        p = item.get("params") or [None] * 7
        if command == MAV_CMD_DO_CHANGE_SPEED:
            ok = p[1] == value
        else:
            ok = abs((p[6] or 0) - value) <= 0.0005 and (lat is None or (_close(p[4], lat) and _close(p[5], lon)))
            if lat is not None:
                for v, scale in ((p[4], 111_320.0), (p[5], 111_320.0 * math.cos(math.radians(home.latitude)))):
                    worst = max(worst, abs(round(v * 1e7) / 1e7 - v) * scale)
        add(f"item {item.get('doJumpId')} matches the mission", ok)
    add("degE7 transport quantization below 2 cm", worst < 0.02, f"max {worst * 100:.3f} cm")
    status = "FILE_MATCHES_EXPECTATIONS" if all(c["ok"] for c in checks) else "FAILED"
    return {"status": status, "checks": checks, "max_degE7_quantization_m": round(worst, 6),
            "importer_readback": _readback(path, mission),
            "compatibility": "NOT_ESTABLISHED: not imported in QGroundControl, not uploaded, not read back from a vehicle"}


def _readback(path: Path, mission: MissionDefinition) -> dict:
    """What the project importer recovers. It drops TAKEOFF and reduces LAND to a waypoint: reported, never hidden."""
    from inputs.qgroundcontrol_adapter import load_qgroundcontrol_plan
    from models.qgc_import import QGroundControlImportContext
    context = QGroundControlImportContext(
        battery_percent=mission.vehicle.battery_percent,
        battery_consumption_percent_per_minute=mission.vehicle.battery_consumption_percent_per_minute,
        wind_speed_kmh=mission.environment.wind_speed_kmh,
        wind_direction_from_deg=mission.environment.wind_direction_from_deg,
        minimum_battery_reserve_percent=mission.constraints.minimum_battery_reserve_percent,
        maximum_wind_speed_kmh=mission.constraints.maximum_wind_speed_kmh,
        maximum_altitude_m=mission.constraints.maximum_altitude_m)
    try:
        result = load_qgroundcontrol_plan(str(path), context)
    except Exception as exc:  # noqa: BLE001 - reported, never hidden
        return {"status": "FAILED", "detail": f"{type(exc).__name__}: {exc}"}
    got = [(w.latitude, w.longitude, w.altitude_m) for w in result.mission.route.waypoints]
    want = [(w.latitude, w.longitude, w.altitude_m) for w in mission.route.waypoints]
    geometry = len(got) >= len(want) and all(_close(a[0], b[0]) and _close(a[1], b[1]) and abs(a[2] - b[2]) <= 0.0005
                                             for a, b in zip(got, want))
    losses = [w for w in result.warnings]
    if len(got) == len(want) + 1:
        losses.append("NAV_LAND represented as an extra navigation waypoint; landing and return meaning lost")
    elif len(got) != len(want):
        geometry = False
    return {"status": "FAILED" if not geometry else "REDUCED" if losses else "FULL",
            "waypoint_geometry": "MATCH" if geometry else "MISMATCH", "losses": losses,
            "note": "our own importer; it is not QGroundControl and shares the project's assumptions"}
