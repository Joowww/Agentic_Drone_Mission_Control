"""Supervisor side of ``tfg.rover.plan-mission-execution/1``, the rover controller's prepared contract for executing a
whole ArduRover ``.plan`` (defined in docs/rover-demo-supervisor-contract.md of the rover controller work; read on
24/11/2026, sha256 636d7bddefefdf2d4d95a0edc292612d15574149092b60c2ef01da3d51cc5114, not committed by its owner).

``build_request`` fills what the supervisor legitimately knows: request id, vehicle, plan (path, sha256 of the exact
bytes, firmware_type 3, vehicle_type 10), the complete route read back from the plan bytes (original item index,
command, frame, params), and the approved limits. It leaves ``execution_binding``, ``frame_evidence`` and
``authority`` as None: they come from the live session and from approvals the supervisor cannot create. A request
with them missing is never admissible.

``check_request`` applies the contract's admission rules offline (every rule listed in that document that can be
checked without a live system): mandatory fields, exact hash of the plan bytes, ArduPilot UGV, explicit
command/frame allowlist with no skipped or aerial items, route identical to the plan, importer without warnings,
speed within the approved limit. It returns the reasons; [] means "formally admissible", NEVER "authorized".
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid

SCHEMA = "tfg.rover.plan-mission-execution/1"
CONTRACT_SOURCE = {"document": "docs/rover-demo-supervisor-contract.md (rover controller work, main checkout)",
                   "sha256": "636d7bddefefdf2d4d95a0edc292612d15574149092b60c2ef01da3d51cc5114",
                   "read_at": "2026-11-24", "status": "PREPARED_BY_OWNER_NOT_COMMITTED_NO_HANDLER"}
MANDATORY = ("schema", "request_id", "vehicle_id", "plan", "execution_binding", "route", "frame_evidence", "limits",
             "authority")
BINDING_FIELDS = ("session_id", "engine_id", "container_id", "image_id", "container_created_at",
                  "container_started_at", "host_boot_id")
AUTHORITY_FIELDS = ("start", "sitl_policy", "motion", "stop_disarm", "restoration")
LIMIT_FIELDS = ("speed_mps", "distance_m", "lateral_m", "stop")
ALLOWED = {(16, 3): "NAV_WAYPOINT (relative frame)", (178, 2): "DO_CHANGE_SPEED (mission frame)"}
AERIAL = {21: "NAV_LAND", 22: "NAV_TAKEOFF", 84: "NAV_VTOL_TAKEOFF", 85: "NAV_VTOL_LAND"}


def route_from_plan(data: bytes) -> list[dict]:
    items = json.loads(data)["mission"]["items"]
    return [{"index": i, "doJumpId": it.get("doJumpId"), "command": it.get("command"), "frame": it.get("frame"),
             "params": it.get("params")} for i, it in enumerate(items)]


def build_request(*, vehicle: dict, plan_path: str, plan_bytes: bytes, ground: dict, manifest: dict) -> dict:
    plan = json.loads(plan_bytes)["mission"]
    legs = [leg["length_m"] for leg in ground.get("legs") or []]
    return {
        "schema": SCHEMA, "request_id": f"{manifest['mission_id']}.{vehicle['vehicle_id']}.{uuid.uuid4().hex[:8]}",
        "vehicle_id": vehicle["vehicle_id"],
        "plan": {"path": plan_path, "sha256": hashlib.sha256(plan_bytes).hexdigest(),
                 "firmware_type": plan.get("firmwareType"), "vehicle_type": plan.get("vehicleType")},
        "execution_binding": None,     # live session identity: only the protected lifecycle can provide it
        "route": route_from_plan(plan_bytes),
        "frame_evidence": None,        # verified geographic -> local odom transform: not accredited for this site
        "limits": {"speed_mps": ground.get("speed_limit_mps"),
                   "distance_m": round(sum(legs), 3) if legs else None,
                   "lateral_m": None,     # not declared by the scenario: never invented
                   "stop": None},
        "authority": None,             # START, SITL policy, motion, stop/disarm, restoration: human approvals
        "supervisor_context": {"mission_id": manifest["mission_id"], "manifest_sha256": manifest["manifest_sha256"],
                               "task_id": vehicle["task_id"],
                               "dependencies": [d for d in manifest["dependencies"]
                                                if d["task_id"] == vehicle["task_id"]],
                               "timeout_s": ground.get("timeout_s"), "contract_source": CONTRACT_SOURCE}}


def importer_warnings(plan_path: Path) -> list[str]:
    """The project importer (the one the contract says to reuse) must accept the plan without warnings."""
    from inputs.qgroundcontrol_adapter import load_qgroundcontrol_plan
    from models.qgc_import import QGroundControlImportContext
    ctx = QGroundControlImportContext(battery_percent=100, battery_consumption_percent_per_minute=1,
                                      wind_speed_kmh=0, wind_direction_from_deg=0,
                                      minimum_battery_reserve_percent=0, maximum_wind_speed_kmh=1,
                                      maximum_altitude_m=120)
    try:
        result = load_qgroundcontrol_plan(str(plan_path), ctx)
    except Exception as exc:  # noqa: BLE001 - reported as an admission reason
        return [f"IMPORT_FAILED: {type(exc).__name__}: {str(exc)[:200]}"]
    out = [f"IMPORT_WARNING: {w}" for w in result.warnings]
    if result.mission.vehicle.vehicle_type != "ugv":
        out.append(f"IMPORTED_AS_{result.mission.vehicle.vehicle_type}")
    return out


def check_request(req: dict, plan_bytes: bytes | None, *, plan_path: Path | None = None) -> dict:
    """Offline admission check. ``formal`` reasons concern the request and plan; ``pending`` are the live/authority
    fields the supervisor must leave empty. ADMISSIBLE needs both empty; the supervisor's requests are, by design,
    FORMALLY_VALID_PENDING_LIVE_EVIDENCE at most."""
    formal, pending = [], []
    if not isinstance(req, dict) or req.get("schema") != SCHEMA:
        return {"status": "REJECTED", "formal": [f"SCHEMA: expected {SCHEMA}"], "pending": []}
    for key in MANDATORY:
        if key not in req:
            formal.append(f"MISSING_FIELD: {key}")
    plan = req.get("plan") or {}
    if plan_bytes is None:
        formal.append("PLAN_BYTES_UNAVAILABLE")
    else:
        if hashlib.sha256(plan_bytes).hexdigest() != plan.get("sha256"):
            formal.append("PLAN_HASH_CHANGED: sha256 of the bytes differs from the request")
        header = json.loads(plan_bytes)["mission"]
        if (header.get("firmwareType"), header.get("vehicleType")) != (3, 10) or \
                (plan.get("firmware_type"), plan.get("vehicle_type")) != (3, 10):
            formal.append("INCOMPATIBLE_VEHICLE: firmware_type 3 and vehicle_type 10 required in plan and request")
        if req.get("route") != route_from_plan(plan_bytes):
            formal.append("ROUTE_DIFFERS_FROM_PLAN: skipped, reordered or altered items")
        cruise = header.get("cruiseSpeed")
        speed = (req.get("limits") or {}).get("speed_mps")
        if not isinstance(speed, (int, float)) or speed <= 0:
            formal.append("SPEED_LIMIT_MISSING")
        elif isinstance(cruise, (int, float)) and cruise > speed:
            formal.append(f"PLAN_SPEED_EXCEEDS_LIMIT: cruiseSpeed {cruise} > {speed} m/s (no silent rewrite)")
        for item in route_from_plan(plan_bytes):
            if item["command"] in AERIAL:
                formal.append(f"AERIAL_ITEM: index {item['index']} {AERIAL[item['command']]}")
            elif (item["command"], item["frame"]) not in ALLOWED:
                formal.append(f"UNSUPPORTED_ITEM: index {item['index']} command {item['command']} frame {item['frame']}")
            elif item["command"] == 16 and (item["params"][6] != 0 or not item["params"][4] or not item["params"][5]):
                formal.append(f"WAYPOINT_INVALID: index {item['index']} (altitude must be 0, lat/lon explicit)")
    if plan_path is not None:
        formal += importer_warnings(plan_path)
    binding = req.get("execution_binding")
    if not isinstance(binding, dict) or any(not binding.get(k) for k in BINDING_FIELDS):
        pending.append("EXECUTION_BINDING_MISSING: live session/engine/container/image/boot identity")
    if not isinstance(req.get("frame_evidence"), dict) or not (req["frame_evidence"] or {}).get("sha256"):
        pending.append("FRAME_EVIDENCE_MISSING: verified geographic -> local odom transform")
    limits = req.get("limits") or {}
    missing_limits = [k for k in LIMIT_FIELDS if limits.get(k) in (None, "")]
    if missing_limits:
        pending.append(f"LIMITS_INCOMPLETE: {missing_limits} must be approved for the complete route")
    auth = req.get("authority")
    if not isinstance(auth, dict) or any(not auth.get(k) for k in AUTHORITY_FIELDS):
        pending.append("AUTHORITY_MISSING: START, SITL policy, motion, stop/disarm and restoration approvals")
    status = "REJECTED" if formal else ("FORMALLY_VALID_PENDING_LIVE_EVIDENCE" if pending else "ADMISSIBLE")
    return {"status": status, "formal": formal, "pending": pending,
            "note": "ADMISSIBLE is a format verdict; it never authorizes motion"}
