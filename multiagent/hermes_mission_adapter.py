"""Multi-agent drone plan -> the project's own mission contract (MissionDefinition, the one Hermes builds, validates,
exports and the H2 executor runs). No parallel planner: every mission is REBUILT with the code that produced it
(multiagent.swarm.route_candidate -> planning.scenario_instance via the scenario template) and must be byte-identical
to the one the Drone Agent validated (its recorded mission_sha256). Then the real checks run:

  tools.hermes_mission_validation.validate_mission     Hermes' deterministic validation (FEASIBLE / APPROVED)
  inputs.qgc_plan_export.build_plan                     the strict QGroundControl .plan profile
  tools.simulated_vehicle.resolve_mission_vehicle       logical drone -> SITL interface (drone_01->v1, drone_02->v2)

This package never imports vehicle-control or executor modules (tests/test_multiagent_agents.py enforces it). What
the H2 executor accepts (its compatibility check and the two-mission sequence admission) is checked at the boundary,
tools/multiagent_drone_sequence.py, in a separate process: multiagent.drone_execution_bridge.

Nothing here is executed, uploaded or authorized. States (EXECUTED is never produced here):

  PROPOSED                    the agents' proposal, before these checks
  PLANNING_VALID              every check passed; an execution request still needs an operator statement
  PENDING_PARAMETERS          something an executable mission needs is not declared (never invented)
  PENDING_AUTHORIZATION       planning-valid, waiting for the operator (set by the execution bridge)
  READY_TO_REQUEST_EXECUTION  planning-valid AND an operator statement exists (set by the execution bridge)
  REJECTED                    a check failed (reasons are structured)
  CANCELLED                   the mission was cancelled: nothing is prepared
"""
from __future__ import annotations

from contextlib import redirect_stdout
import copy
import hashlib
import io
import json

SCHEMA = "tfg.multiagent.drone-missions/1"
PLANNED = ("PROPOSED_PENDING_AUTHORIZATION", "PARTIAL_PENDING_AUTHORIZATION")


def _quiet(fn, *a, **kw):
    with redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _finding(kind, detail, action, task=None):
    return {"kind": kind, "detail": detail, "action": action, **({"task_id": task} if task else {})}


def adapt_proposal(proposal: dict, *, context, site, fleet, source: dict, cancelled: bool = False) -> dict:
    """``proposal``: a Mission Orchestrator proposal (live, or a sealed one read without modification).
    ``source``: where it comes from, e.g. {"kind": "REPLAY_OF_SEALED_RUN", "agents": "REAL_LOCAL_LLM", ...}."""
    from multiagent.swarm import Objective, SwarmProblem
    out = {"schema": SCHEMA, "mission_id": proposal.get("mission_id"), "proposal_sha256": proposal.get("proposal_sha256"),
           "source": source, "drones": [], "findings": [], "dependencies": copy.deepcopy(
               (proposal.get("template") or {}).get("dependencies") or []),
           "execution_order": list((proposal.get("template") or {}).get("execution_order") or []),
           "separation": copy.deepcopy(proposal.get("swarm_coordination")),
           "approval": {"status": "NOT_REQUESTED", "note": "a valid plan is never a flight authorization"},
           "commands": [], "movement_authorized": False}
    if cancelled or proposal.get("status") == "CANCELLED":
        out["status"] = "CANCELLED"
        out["findings"].append(_finding("MISSION_CANCELLED", "nothing is prepared for a cancelled mission", "STOP"))
        return out
    if proposal.get("status") not in PLANNED:
        out["status"] = "REJECTED"
        out["findings"].append(_finding("PROPOSAL_NOT_PLANNED", f"proposal status {proposal.get('status')!r}",
                                        "REJECTED"))
        return out
    aerial = (proposal.get("aerial") or {}).get("proposals") or []
    if not aerial:
        out["status"] = "REJECTED"
        out["findings"].append(_finding("NO_AERIAL_TASK", "the proposal assigns no drone", "REJECTED"))
        return out
    brief = proposal.get("brief") or {}
    wind = brief.get("wind_speed_kmh") if brief.get("wind_speed_kmh") is not None else context.wind_speed_kmh
    objectives = [Objective(o["objective_id"], o.get("point_id"), o.get("required_sensor"))
                  for o in brief.get("aerial_objectives", [])]
    problem = SwarmProblem(site, fleet, context, objectives, list(context.drones), wind,
                           dict(brief.get("battery_percent") or {}), brief.get("altitude_m"))
    # ------------------------------------------------------------------ plan-level checks
    for item in (proposal.get("aerial") or {}).get("incompatible") or []:   # never dropped silently
        out["findings"].append(_finding("UNASSIGNED_OBJECTIVE", f"{item.get('objective_id')}: "
                                        f"{(item.get('reasons') or [''])[0]}", "REPORTED"))
    seen = {}
    for t in aerial:
        for oid in t.get("objective_ids") or []:
            if oid in seen:
                out["findings"].append(_finding("DUPLICATE_OBJECTIVE", f"{oid} assigned to {seen[oid]} and "
                                                f"{t['vehicle_id']}", "REJECTED", t.get("task_id")))
            seen[oid] = t["vehicle_id"]
        for pid in t.get("poi_sequence") or []:
            others = [u["vehicle_id"] for u in aerial if u is not t and pid in (u.get("poi_sequence") or [])]
            if others and t["vehicle_id"] < min(others):
                out["findings"].append(_finding("DUPLICATE_POINT", f"{pid} visited by {t['vehicle_id']} and {others}",
                                                "REJECTED", t.get("task_id")))
    tasks = {t["task_id"] for t in proposal.get("tasks") or []} | {t["task_id"] for t in aerial}
    for dep in out["dependencies"]:
        if dep.get("after") not in tasks or dep.get("task_id") not in tasks:
            out["findings"].append(_finding("UNMET_DEPENDENCY", f"{dep.get('task_id')} after {dep.get('after')}: "
                                            "a task it names is not in the plan", "REJECTED"))
        elif dep.get("condition") == "POI_REACHED":
            owner = next((t for t in aerial if t["task_id"] == dep["after"]), None)
            if owner is not None and dep.get("point") not in (owner.get("poi_sequence") or []):
                out["findings"].append(_finding("UNMET_DEPENDENCY", f"{dep['after']} never visits {dep.get('point')}",
                                                "REJECTED"))
    sep = out["separation"] or {}
    if len(aerial) > 1:
        if sep.get("status") not in ("CLEAR", "DECONFLICTED_BY_START_DELAY"):
            out["findings"].append(_finding("SEPARATION_NOT_ESTABLISHED", f"swarm coordination {sep.get('status')}",
                                            "REJECTED"))
        for t in aerial:
            planned = ((sep.get("schedule") or {}).get(t["vehicle_id"]) or {}).get("start_delay_s")
            if planned != t.get("start_delay_s"):
                out["findings"].append(_finding("SCHEDULE_INCONSISTENT", f"{t['vehicle_id']}: task delay "
                                                f"{t.get('start_delay_s')} vs coordination {planned}", "REJECTED"))
    # ------------------------------------------------------------------ per drone
    for t in aerial:
        out["drones"].append(_drone_record(t, problem, site))
    for d in out["drones"]:
        out["findings"].extend(d["findings"])
    actions = {f["action"] for f in out["findings"]}
    out["status"] = ("REJECTED" if "REJECTED" in actions else "PENDING_PARAMETERS" if "PENDING_PARAMETERS" in actions
                     else "PLANNING_VALID")
    out["adapter_sha256"] = _sha({k: v for k, v in out.items() if k != "adapter_sha256"})
    return out


def _drone_record(t: dict, problem, site) -> dict:
    from inputs.qgc_plan_export import ExportRefused, build_plan, plan_bytes
    from multiagent.swarm import route_candidate
    from planning.scenario_instance import mission_bytes, sha256
    from tools.simulated_vehicle import VehicleSelectionError, resolve_mission_vehicle
    task, vid = t.get("task_id"), t["vehicle_id"]
    rec = {"task_id": task, "vehicle_id": vid, "objective_ids": list(t.get("objective_ids") or []),
           "poi_sequence": list(t.get("poi_sequence") or []), "takeoff_point": t.get("takeoff_point"),
           "start_delay_s": t.get("start_delay_s"), "recorded_mission_sha256": t.get("mission_sha256"),
           "findings": [], "state": "PROPOSED"}
    geo = site.geo_reference
    rec["georeference"] = None if geo is None else {"latitude": geo.latitude, "longitude": geo.longitude,
                                                    "verification": geo.verification, "source": geo.source}
    if geo is None or geo.latitude is None or geo.longitude is None:
        rec["findings"].append(_finding("GEOREFERENCE_MISSING", "waypoints cannot be placed geographically",
                                        "PENDING_PARAMETERS", task))
        rec["state"] = "PENDING_PARAMETERS"
        return rec
    try:
        drone = problem.drone(vid)
    except (KeyError, StopIteration, ValueError):
        drone = None
    if drone is None:
        rec["findings"].append(_finding("DRONE_NOT_DECLARED", vid, "REJECTED", task))
        rec["state"] = "REJECTED"
        return rec
    unknown = [p for p in rec["poi_sequence"] if site.point(p) is None]
    if unknown:
        rec["findings"].append(_finding("UNKNOWN_POINT", f"{unknown} are not declared site points", "REJECTED", task))
        rec["state"] = "REJECTED"
        return rec
    # sensors: every objective's required sensor must be on THIS drone
    for oid in rec["objective_ids"]:
        need = problem.objective(oid).required_sensor if any(o.objective_id == oid for o in problem.objectives) else None
        if need and need not in (drone.sensors or []):
            rec["findings"].append(_finding("SENSOR_NOT_AVAILABLE", f"{oid} needs {need}; {vid} has {drone.sensors}",
                                            "REJECTED", task))
    rec["sensors"] = {"drone": list(drone.sensors or []),
                      "required": {o.objective_id: o.required_sensor for o in problem.objectives
                                   if o.objective_id in rec["objective_ids"]}}
    cand = _quiet(route_candidate, problem, drone, rec["poi_sequence"])
    rec["route_status"] = cand["status"]
    if cand["status"] != "FEASIBLE":
        rec["findings"].append(_finding("ROUTE_NOT_FEASIBLE", "; ".join(cand.get("reasons") or [])[:300], "REJECTED", task))
        rec["state"] = "REJECTED"
        return rec
    mission = cand["mission"]
    # what the temporal coordinator needs to re-check separation (same inputs as the deconfliction)
    rec["timeline_inputs"] = {"route_local": [list(map(float, p)) for p in cand["route_local"]],
                              "labels": list(cand["labels"]), "leg_minutes": list(cand["leg_minutes"])}
    rec["mission_sha256"] = sha256(mission_bytes(mission))
    if rec["recorded_mission_sha256"] is not None and rec["mission_sha256"] != rec["recorded_mission_sha256"]:
        rec["findings"].append(_finding("PLAN_MODIFIED_AFTER_VALIDATION", "the rebuilt mission differs from the one "
                                        "the Drone Agent validated", "REJECTED", task))
    rec["mission"] = json.loads(mission_bytes(mission))
    rec["waypoints"] = [{"waypoint_id": w.waypoint_id, "latitude": w.latitude, "longitude": w.longitude,
                         "altitude_m": w.altitude_m, "speed_kmh": w.speed_kmh, "action": w.action}
                        for w in mission.route.waypoints]
    # speed: declared or not; never invented
    if drone.survey_speed_kmh is not None:
        rec["speed_source"] = f"DECLARED_DRONE_PROFILE ({drone.provenance})"
    elif problem.context.requested_speed_kmh is not None:
        rec["speed_source"] = "DECLARED_OPERATING_CONTEXT"
    elif mission.vehicle.cruise_speed_kmh is not None:
        rec["speed_source"] = "VEHICLE_CRUISE_SPEED (declared profile; no requested speed)"
    else:
        rec["speed_source"] = None
        rec["findings"].append(_finding("SPEED_NOT_DECLARED", "no requested, survey or cruise speed is declared",
                                        "PENDING_PARAMETERS", task))
    rec["altitude_m"] = sorted({w.altitude_m for w in mission.route.waypoints})
    rec["limits"] = {"maximum_altitude_m": mission.constraints.maximum_altitude_m,
                     "maximum_wind_speed_kmh": mission.constraints.maximum_wind_speed_kmh,
                     "minimum_battery_reserve_percent": mission.constraints.minimum_battery_reserve_percent}
    # the real downstream checks
    v = _quiet(_validate, mission)
    rec["hermes_validation"] = {k: v.get(k) for k in ("mission_status", "execution_status", "failure_reasons", "errors")}
    if v.get("mission_status") != "FEASIBLE" or v.get("execution_status") != "APPROVED":
        rec["findings"].append(_finding("HERMES_VALIDATION_FAILED", f"{v.get('mission_status')}/"
                                        f"{v.get('execution_status')}: {(v.get('failure_reasons') or v.get('errors'))}",
                                        "REJECTED", task))
    try:
        plan, _log = build_plan(mission, planned_home_amsl_m=_home_amsl(site))
        rec["qgc_plan"] = {"status": "GENERATED", "sha256": hashlib.sha256(plan_bytes(plan)).hexdigest(),
                           "items": len(plan["mission"]["items"])}
    except ExportRefused as exc:  # e.g. no declared home AMSL: the .plan is refused, the mission is still valid
        rec["qgc_plan"] = {"status": "REFUSED", "reasons": list(exc.args[0]) if exc.args else []}
    except ValueError as exc:
        rec["qgc_plan"] = {"status": "REFUSED", "reasons": [str(exc)]}
    if mission.route.home is None:   # the executor's own compatibility check runs at the boundary (bridge)
        rec["findings"].append(_finding("NO_MISSION_HOME", "simulation mapping requires a mission home", "REJECTED", task))
    try:
        rec["sitl_binding"] = resolve_mission_vehicle(mission).as_dict()
    except VehicleSelectionError as exc:
        rec["sitl_binding"] = None
        rec["findings"].append(_finding("NO_SITL_BINDING", str(exc), "REJECTED", task))
    actions = {f["action"] for f in rec["findings"]}
    rec["state"] = ("REJECTED" if "REJECTED" in actions else "PENDING_PARAMETERS" if "PENDING_PARAMETERS" in actions
                    else "PLANNING_VALID")
    return rec


def _validate(mission):
    from tools.hermes_mission_validation import validate_mission
    return validate_mission(mission)


def _home_amsl(site):
    """The planned home AMSL the .plan needs: only if the site declares it (never invented)."""
    vr = getattr(site, "vertical_reference", None)
    return getattr(vr, "origin_ground_amsl_m", None)


def mission_files(adapted: dict) -> dict:
    """{vehicle_id: exact mission bytes} of the planning-valid drones (the files the H2 sequence admits)."""
    from models.mission_definition import MissionDefinition
    from planning.scenario_instance import mission_bytes
    return {d["vehicle_id"]: mission_bytes(MissionDefinition.model_validate(d["mission"]))
            for d in adapted["drones"] if d.get("mission") is not None}
