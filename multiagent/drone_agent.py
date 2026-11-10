"""Drone / Swarm Agent: aerial objectives -> one validated individual mission (and .plan) per drone.

Input: the aerial objectives of a brief plus the operating context (site, fleet, declared drone profiles).
Steps: resolve every objective to a declared site point; check requested drones exist; allocate with the
deterministic reference (multiagent.swarm) or, if an allocator is given, check ITS proposal with the same rules
and use it only when valid; build each mission's QGC ``.plan`` with the existing strict exporter.
Output: AgentResult with per-drone proposals, incompatible objectives (with reasons) and the decision evidence.
It never uploads, arms or flies anything.
"""
from __future__ import annotations

from contextlib import redirect_stdout
import io

from inputs.qgc_plan_export import ExportRefused, build_plan, plan_bytes
from models.fleet import QGC_PROFILE
from planning.scenario_instance import sha256

from multiagent.contracts import AgentResult, AerialObjective, OperatingContext
from multiagent.site_points import resolve_point
from multiagent.deconfliction import deconflict
from multiagent.swarm import Objective, SwarmProblem, allocate, evaluate_proposal, route_candidate

AGENT = "drone_swarm_agent"


def _quiet(fn, *args, **kw):
    """The project's flight-dynamics helper prints every leg; keep agent output clean."""
    with redirect_stdout(io.StringIO()):
        return fn(*args, **kw)


def plan_aerial(objectives: list[AerialObjective], *, context: OperatingContext, site, fleet, wind_speed_kmh: float,
                battery_percent: dict, altitude_m: float | None, requested_drones: list[str], tracer=None,
                allocator=None) -> tuple[AgentResult, dict]:
    """(result, artifacts): artifacts = {"plans": {vehicle_id: .plan bytes}, "missions": {vehicle_id: mission}}."""
    incompatible, clarifications, resolved = [], [], []
    for objective in objectives:
        point, reasons = resolve_point(site, point_id=objective.point_id, coordinates=objective.coordinates, kind="poi",
                                       tolerance_m=context.coordinate_match_tolerance_m)
        if reasons:
            clarifications.extend(f"{objective.objective_id}: {r}" for r in reasons)
        else:
            resolved.append(Objective(objective.objective_id, point, objective.required_sensor))
    drones = list(context.drones)
    if requested_drones:
        unknown = sorted(set(requested_drones) - {d.vehicle_id for d in drones})
        drones = [d for d in drones if d.vehicle_id in requested_drones]
        if unknown and not drones:
            incompatible.extend({"objective_id": o.objective_id,
                                 "reasons": [f"REQUESTED_DRONE_NOT_DECLARED: {', '.join(unknown)}"]} for o in resolved)
            resolved = []
        elif unknown:
            clarifications.append(f"REQUESTED_DRONE_NOT_DECLARED: {', '.join(unknown)} (planning with the others)")
    for vehicle_id in battery_percent:
        if vehicle_id not in {d.vehicle_id for d in context.drones}:
            clarifications.append(f"BATTERY_FOR_UNKNOWN_DRONE: {vehicle_id}")
    problem = SwarmProblem(site, fleet, context, resolved, drones, wind_speed_kmh, dict(battery_percent), altitude_m)
    reference = _quiet(allocate, problem) if resolved else None
    if reference is not None and reference["status"] != "OK":
        incompatible.extend({"objective_id": o.objective_id, "reasons": [reference["reason"]]} for o in resolved)
        reference = None
    chosen, source, model_check = (reference["assignments"] if reference else {}), "DETERMINISTIC_REFERENCE", None
    if allocator is not None and reference is not None:
        proposal, meta = allocator(problem)
        model_check = _quiet(evaluate_proposal, problem, proposal, reference)
        model_check["allocator"] = meta
        if meta.get("contract_rejected"):  # e.g. an objective left out with a reason the context contradicts
            model_check["valid"] = False
            model_check.setdefault("violations", []).append("CONTRACT_REJECTED_BY_GATE: the model proposal is not used")
        if model_check["valid"]:
            chosen, source = {}, "MODEL_PROPOSAL_CHECKED"
            for vehicle_id, objective_ids in proposal["assignments"].items():
                points = []
                for objective_id in objective_ids:
                    point = problem.objective(objective_id).point_id
                    points.append(point) if point not in points else None
                if points:
                    candidate = _quiet(route_candidate, problem, problem.drone(vehicle_id), points)
                    chosen[vehicle_id] = {**candidate, "objective_ids": sorted(objective_ids)}
    coordination, attempts = None, []
    if reference is not None:
        alternatives = reference.get("_alternatives", [])
        if source == "DETERMINISTIC_REFERENCE":
            alternatives = alternatives[1:]  # the first one is the chosen allocation itself
        candidates = [("CHOSEN", chosen)] + [(f"ALTERNATIVE_{i}", a["assignments"]) for i, a in enumerate(alternatives, 1)]
        final = None
        for label, candidate in candidates:
            result = deconflict({v: {"route_local": a["route_local"], "labels": a["labels"],
                                     "leg_minutes": a["leg_minutes"]} for v, a in candidate.items()},
                                context.separation_policy)
            attempts.append({"candidate": label, "assignment": {v: a["objective_ids"] for v, a in sorted(candidate.items())},
                             "status": result["status"], "initial_conflicts": len(result["initial_conflicts"]),
                             "reason": result.get("reason")})
            if tracer is not None:
                tracer.validation(AGENT, f"deconfliction:{label}", result["status"],
                                  {"conflicts": result["initial_conflicts"][:5], "schedule": result.get("schedule")})
            if result["status"] != "UNRESOLVED":
                coordination, final = result, candidate
                break
        if final is None:  # cannot happen with the empty allocation last, kept as a guard
            coordination, final = {"status": "UNRESOLVED", "initial_conflicts": [], "residual_conflicts": [],
                                   "schedule": {}, "reason": "no candidate allocation could be deconflicted"}, {}
        before = {o for a in chosen.values() for o in a["objective_ids"]}
        chosen = final
        covered = {o for a in chosen.values() for o in a["objective_ids"]}
        for objective_id in sorted(before - covered):
            first = next((a for a in attempts if a["status"] == "UNRESOLVED"), None)
            incompatible.append({"objective_id": objective_id, "reasons": [
                "COORDINATION_CONFLICT: the allocation covering it could not be deconflicted"
                + (f" ({first['reason']})" if first else "")]})
        for item in reference["unassigned"]:
            if item["objective_id"] not in covered and item["objective_id"] not in before:
                incompatible.append({"objective_id": item["objective_id"], "reasons": item["reasons"]})
        # an objective nobody covers must never vanish (e.g. an accepted agent proposal that leaves it out)
        reported = {i["objective_id"] for i in incompatible}
        rounds = ((model_check or {}).get("allocator") or {}).get("rounds") or []
        separation_rejected = any(f.startswith("SEPARATION") for r in rounds[:-1] for f in r.get("findings") or [])
        verified = (rounds[-1].get("unassigned_verification") or {}) if rounds and source != "DETERMINISTIC_REFERENCE" else {}
        declared_reason = {"SEPARATION_CONFLICT": "COORDINATION_CONFLICT: left out by the drone agent (SEPARATION_CONFLICT), "
                                                  "verified: every eligible drone conflicts with the accepted plan",
                           "NO_ELIGIBLE_DRONE": "NO_ELIGIBLE_DRONE: declared by the drone agent and verified",
                           "ROUTE_INFEASIBLE": "ROUTE_INFEASIBLE: declared by the drone agent and verified"}
        for objective in problem.objectives:
            if objective.objective_id not in covered and objective.objective_id not in reported:
                v = verified.get(objective.objective_id)
                incompatible.append({"objective_id": objective.objective_id, "reasons": [
                    declared_reason[v["declared"]] if v and v["verified"] else
                    "COORDINATION_CONFLICT: left out by the drone agent after the gate rejected a separation conflict"
                    if separation_rejected else
                    "NOT_ASSIGNED_BY_DRONE_AGENT: the accepted allocation leaves it out"
                    + (f" ({source})" if source != "DETERMINISTIC_REFERENCE" else "")]})
    proposals, plans, missions = [], {}, {}
    amsl = site.vertical_reference.origin_ground_amsl_m if site.vertical_reference else None
    for vehicle_id, entry in sorted(chosen.items()):
        mission = entry["mission"]
        export = {"status": "REFUSED", "reasons": ["site has no ground AMSL"]}
        vehicle = fleet.vehicle(vehicle_id)
        if vehicle is not None and vehicle.export_profile != QGC_PROFILE:
            export = {"status": "NOT_EXPORTED", "reasons": [
                f"COMPATIBILITY_PENDING: {vehicle_id} has no export profile ({vehicle.provenance}); planned only"]}
        elif amsl is not None:
            try:
                plan, _ = build_plan(mission, planned_home_amsl_m=amsl)
                content = plan_bytes(plan)
                plans[vehicle_id] = content
                export = {"status": "GENERATED", "profile": "QGC_PLAN_ARDUCOPTER_V2", "plan_sha256": sha256(content),
                          "items": len(plan["mission"]["items"])}
            except ExportRefused as exc:
                export = {"status": "REFUSED", "reasons": [str(r) for r in exc.args[0]]}
        missions[vehicle_id] = mission
        proposals.append({"task_id": f"AIR_{vehicle_id}", "vehicle_id": vehicle_id,
                          "objective_ids": entry["objective_ids"], "poi_sequence": entry["sequence"],
                          "takeoff_point": problem.drone(vehicle_id).takeoff_point,
                          "length_m": round(entry["length_m"], 3), "flight_minutes": round(entry["flight_minutes"], 4),
                          "mission_id": mission.mission_id, "mission_sha256": entry["mission_sha256"],
                          "deterministic_validation": entry["deterministic_validation"], "export": export,
                          "route_local": entry["route_local"],
                          "start_delay_s": (coordination or {}).get("schedule", {}).get(vehicle_id, {}).get("start_delay_s"),
                          "state": "PENDING_AUTHORIZATION"})
        if tracer is not None:
            tracer.validation(AGENT, f"mission:{vehicle_id}", entry["deterministic_validation"]["mission_status"],
                              {"mission_sha256": entry["mission_sha256"], "export": export})
    status = _status(proposals, incompatible, clarifications, bool(objectives))
    if coordination is not None and coordination["status"] == "PENDING_MISSING_DATA" and len(proposals) > 1:
        status = "COORDINATION_PENDING"
    evidence = {"allocation_source": source, "reference": reference["evidence"] if reference else None,
                "model_proposal_check": model_check, "wind_speed_kmh": wind_speed_kmh,
                "coordination": coordination, "coordination_attempts": attempts,
                "replanned_for_coordination": bool(attempts) and attempts[-1]["candidate"] != "CHOSEN",
                "battery_percent_declared": battery_percent, "drones_considered": [d.vehicle_id for d in drones],
                "note": "allocation is offline planning; no coordination in flight is implied"}
    result = AgentResult(agent=AGENT, status=status, proposals=proposals, incompatible=incompatible,
                         clarifications=clarifications, evidence=evidence)
    return result, {"plans": plans, "missions": missions}


def _status(proposals, incompatible, clarifications, any_objective):
    if not any_objective:
        return "NO_TASKS"
    if clarifications and not proposals:
        return "NEEDS_CLARIFICATION"
    if not proposals:
        return "INFEASIBLE"
    if incompatible or clarifications:
        return "PARTIAL_PENDING_AUTHORIZATION"
    return "PROPOSED_PENDING_AUTHORIZATION"
