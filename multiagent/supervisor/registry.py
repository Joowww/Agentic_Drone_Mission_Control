"""Shared vehicle registry: which vehicles exist, their class, actions, constraints, availability and executor.

Built ONLY from declared sources: the operating context (multiagent.contracts.OperatingContext, declared profiles),
the fleet (models.fleet.Fleet) and a capability-evidence file (fixtures/supervisor/capability_evidence.json). A
capability absent from the evidence file is NOT_IMPLEMENTED; a capability is never upgraded by this module.

Execution rule (``execution_capability``): a vehicle can be handed to a real executor only through a capability whose
status is DEMONSTRATED_SITL and whose evidence files exist with the recorded sha256. Everything else blocks real
execution; the offline test double may still exercise the flow, labelled TEST_DOUBLE.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "tfg.multiagent.vehicle-registry/1"
EVIDENCE_SCHEMA = "tfg.multiagent.capability-evidence/1"
STATUSES = ("DEMONSTRATED_SITL", "OFFLINE_VALIDATED", "PENDING_CONTROLLER", "NOT_IMPLEMENTED")
# which capability each vehicle class needs to execute its supervisor mission (a .plan or its bound mission)
EXECUTION_CAPABILITY = {"ArduCopter": "EXECUTE_GUIDED_WAYPOINT_MISSION_SITL", "ArduRover": "EXECUTE_PLAN_MISSION_SITL"}
SINGLE_GOAL_CAPABILITY = {"ArduRover": "EXECUTE_GUIDED_SINGLE_GOAL_SITL"}
FORBIDDEN_ACTIONS = {"ArduCopter": [], "ArduRover": ["TAKEOFF", "LAND"]}


def _sha_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def load_evidence(path: Path | str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != EVIDENCE_SCHEMA:
        raise ValueError(f"not a capability evidence file: {data.get('schema')!r}")
    for cls, caps in data["classes"].items():
        for name, cap in caps.items():
            if cap.get("status") not in STATUSES:
                raise ValueError(f"{cls}.{name}: unknown status {cap.get('status')!r}")
            if cap["status"] == "DEMONSTRATED_SITL" and not cap.get("evidence"):
                raise ValueError(f"{cls}.{name}: DEMONSTRATED_SITL without evidence")
    return data


def verify_evidence(cap: dict, root: Path = ROOT) -> list[str]:
    """Problems with a DEMONSTRATED_SITL claim: every evidence file must exist with its recorded sha256."""
    problems = []
    for item in cap.get("evidence") or []:
        got = _sha_file(root / item["path"])
        if got is None:
            problems.append(f"EVIDENCE_MISSING: {item['path']}")
        elif got != item.get("sha256"):
            problems.append(f"EVIDENCE_HASH_MISMATCH: {item['path']}")
    return problems


def vehicle_class(fleet_vehicle) -> str | None:
    if fleet_vehicle is None or fleet_vehicle.autopilot != "ArduPilot":
        return None
    return {"multirotor": "ArduCopter", "ugv": "ArduRover"}.get(fleet_vehicle.vehicle_type)


def build_registry(context, fleet, evidence: dict, *, overrides: dict | None = None, root: Path = ROOT) -> dict:
    """``overrides``: {vehicle_id: {"available": bool, "reason": str}} declared by the scenario (never measured)."""
    overrides = overrides or {}
    vehicles = []
    declared = [(d, "drone") for d in context.drones] + [(r, "rover") for r in context.rovers]
    for profile, role in declared:
        fv = fleet.vehicle(profile.vehicle_id)
        cls = vehicle_class(fv)
        caps = {}
        for name, cap in (evidence["classes"].get(cls) or {}).items():
            entry = {"status": cap["status"], **{k: cap[k] for k in ("executor", "implementation", "note", "limits",
                                                                      "contract", "boundary", "what", "date")
                                                  if k in cap}}
            if cap["status"] == "DEMONSTRATED_SITL":
                problems = verify_evidence(cap, root)
                entry["evidence"] = cap["evidence"]
                entry["evidence_check"] = problems or "VERIFIED_FILES_AND_HASHES"
            caps[name] = entry
        problems = []
        if fv is None:
            problems.append("NOT_IN_FLEET")
        elif cls is None:
            problems.append(f"UNSUPPORTED_CLASS: {fv.autopilot}/{fv.vehicle_type}")
        if role == "rover" and fv is not None and fv.category != "rover":
            problems.append("NOT_A_FLEET_ROVER")
        over = overrides.get(profile.vehicle_id) or {}
        available = bool(profile.available) and over.get("available", True) and not problems
        reason = over.get("reason") if over.get("available") is False else (
            "declared unavailable in the operating context" if not profile.available else None)
        constraints = {"provenance": profile.provenance}
        if role == "drone":
            constraints.update(takeoff_point=profile.takeoff_point, sensors=list(profile.sensors),
                               battery_percent=profile.battery_percent,
                               consumption_percent_per_minute=profile.consumption_percent_per_minute,
                               cruise_speed_kmh=profile.cruise_speed_kmh, max_wind_kmh=profile.max_wind_kmh,
                               survey_speed_kmh=profile.survey_speed_kmh,
                               minimum_battery_reserve_percent=context.minimum_battery_reserve_percent)
        else:
            constraints.update(start_point=profile.start_point)
        exec_cap = EXECUTION_CAPABILITY.get(cls)
        vehicles.append({
            "vehicle_id": profile.vehicle_id, "role": role, "vehicle_class": cls,
            "autopilot": fv.autopilot if fv else None, "platform": fv.platform if fv else None,
            "sim_binding": fv.sim_binding if fv else None, "physical_identity": "NOT_ESTABLISHED",
            "actions_forbidden": FORBIDDEN_ACTIONS.get(cls, []),
            "capabilities": caps, "constraints": constraints,
            "availability": {"status": "AVAILABLE_DECLARED" if available else "UNAVAILABLE",
                             "basis": "declared (context/scenario); not a live readiness check",
                             "reason": reason or ("; ".join(problems) if problems else None)},
            "executor": {"capability": exec_cap, "status": (caps.get(exec_cap) or {}).get("status", "NOT_IMPLEMENTED"),
                         "name": (caps.get(exec_cap) or {}).get("executor")},
            "problems": problems})
    return {"schema": SCHEMA, "context_id": context.context_id, "fleet": f"{fleet.fleet_id} v{fleet.version}",
            "evidence_id": evidence.get("evidence_id"), "vehicles": vehicles}


def vehicle(registry: dict, vehicle_id: str) -> dict | None:
    return next((v for v in registry["vehicles"] if v["vehicle_id"] == vehicle_id), None)


def available(registry: dict, role: str) -> list[dict]:
    return [v for v in registry["vehicles"] if v["role"] == role and v["availability"]["status"] == "AVAILABLE_DECLARED"]


def execution_capability(registry: dict, vehicle_id: str) -> dict:
    """{"capability", "status", "executable_real": bool, "reasons": [...]} for the vehicle's mission executor."""
    v = vehicle(registry, vehicle_id)
    if v is None:
        return {"capability": None, "status": "NOT_IMPLEMENTED", "executable_real": False,
                "reasons": [f"VEHICLE_NOT_REGISTERED: {vehicle_id}"]}
    name = v["executor"]["capability"]
    cap = v["capabilities"].get(name) or {"status": "NOT_IMPLEMENTED"}
    reasons = []
    if cap["status"] != "DEMONSTRATED_SITL":
        reasons.append(f"CAPABILITY_NOT_DEMONSTRATED: {name} is {cap['status']}")
    elif cap.get("evidence_check") != "VERIFIED_FILES_AND_HASHES":
        reasons.append(f"CAPABILITY_EVIDENCE_INVALID: {cap.get('evidence_check')}")
    if v["availability"]["status"] != "AVAILABLE_DECLARED":
        reasons.append(f"VEHICLE_UNAVAILABLE: {v['availability']['reason']}")
    return {"capability": name, "status": cap["status"], "executable_real": not reasons, "reasons": reasons}
