"""Deterministic reference allocation of aerial objectives among several drones (offline, planning only).

This is the REFERENCE a model-generated allocation is scored against; it is not a swarm controller. Nothing here
coordinates vehicles in flight: the result is one individual mission per drone plus the declared order and the
pairwise separation of their routes, exactly what the existing scenario template can express.

Search (exhaustive, bounded by MAX_OBJECTIVES):
1. eligibility of each (objective, drone): drone requested and available, fleet entry exportable, sensor
   present, declared wind within the drone's limit;
2. for every subset of objectives a drone may take, the shortest visiting order whose route passes the site
   rules (planning.site_validation.validate_aerial_route: perimeter, exclusions, takeoff zone, altitude) and whose
   mission passes the existing deterministic validation (tools.hermes_mission_validation: battery reserve,
   wind) with that drone's DECLARED profile;
3. the assignment (each objective to one eligible drone, or unassigned) that covers most objectives, then has the
   smallest makespan (longest individual flight time), then the smallest total distance; ties broken by ids.

Every candidate's outcome is recorded as evidence. Flight times come from the project's own route analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations, product
import math
import time

from models.fleet import QGC_PROFILE, Fleet
from models.mission_definition import FailsafeDefinition, MissionDefinition
from models.scenario_template import AerialTask, MissionDefaults, ScenarioTemplate
from models.site import Site
from planning.artifact_store import fingerprint
from planning.scenario_instance import _mission, mission_bytes, sha256
from planning.site_geometry import local_to_geo
from planning.site_validation import validate_aerial_route, validate_site
from tools.hermes_mission_validation import validate_mission
from tools.route_flight_analysis import analyze_mission_flight

from multiagent.contracts import DroneProfile, OperatingContext

MAX_OBJECTIVES = 6  # exhaustive search bound: sum_k C(6,k)*k! = 1957 orders per drone
MAX_ROUTE_POINTS = 6  # per drone, in both modes: at most 6! = 720 visiting orders are tried
MAX_ASSIGNMENTS = 20000  # exhaustive only if prod_i (eligible_i + 1) <= this; otherwise greedy
TIME_BUDGET_S = 20.0  # wall-clock budget of one search; when exceeded the search stops and says so
MAX_ALTERNATIVES = 25  # ranked allocations kept for coordination-driven replanning
ALGORITHM = "tfg.multiagent.swarm-reference/1 exhaustive(coverage desc, makespan asc, distance asc, ids)"
GREEDY = "tfg.multiagent.swarm-greedy/1 most-constrained objective first, drone minimising makespan (NOT optimal)"
FAILSAFE = FailsafeDefinition(low_battery_action="RETURN_TO_HOME", unsafe_wind_action="RETURN_TO_HOME",
                              communication_loss_action="RETURN_TO_HOME")


@dataclass
class Objective:
    objective_id: str
    point_id: str
    required_sensor: str | None = None


@dataclass
class SwarmProblem:
    site: Site
    fleet: Fleet
    context: OperatingContext
    objectives: list[Objective]
    drones: list[DroneProfile]
    wind_speed_kmh: float
    battery_percent: dict = field(default_factory=dict)
    altitude_m: float | None = None
    _routes: dict = field(default_factory=dict, repr=False)

    def objective(self, objective_id):
        return next((o for o in self.objectives if o.objective_id == objective_id), None)

    def drone(self, vehicle_id):
        return next((d for d in self.drones if d.vehicle_id == vehicle_id), None)


def eligibility(problem: SwarmProblem, objective: Objective, drone: DroneProfile) -> list[str]:
    """Reasons why this drone cannot take this objective; [] when it can."""
    reasons = []
    vehicle = problem.fleet.vehicle(drone.vehicle_id)
    if vehicle is None:
        reasons.append(f"NOT_IN_FLEET: {drone.vehicle_id}")
    elif vehicle.export_profile != QGC_PROFILE and problem.context.export_policy != "SYNTHETIC_PLANNING_ONLY":
        reasons.append(f"NO_EXPORT_PROFILE: {drone.vehicle_id} ({vehicle.compatibility})")
    if not drone.available:
        reasons.append(f"NOT_AVAILABLE: {drone.vehicle_id} declared unavailable")
    if objective.required_sensor and objective.required_sensor not in drone.sensors:
        reasons.append(f"SENSOR_MISSING: {drone.vehicle_id} has no {objective.required_sensor} sensor")
    if problem.wind_speed_kmh > drone.max_wind_kmh:
        reasons.append(f"WIND_ABOVE_LIMIT: {problem.wind_speed_kmh} km/h > {drone.max_wind_kmh} km/h "
                       f"for {drone.vehicle_id}")
    return reasons


def _length(points) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _xy(site, point_id):
    p = site.point(point_id)
    return (p.x_m, p.y_m)


def drone_template(problem: SwarmProblem, drone: DroneProfile, sequence: list[str]) -> ScenarioTemplate:
    """A one-task template with this drone's DECLARED profile as mission defaults (existing contract)."""
    ctx, site = problem.context, problem.site
    defaults = MissionDefaults(
        cruise_speed_kmh=drone.cruise_speed_kmh,
        battery_percent=problem.battery_percent.get(drone.vehicle_id, drone.battery_percent),
        battery_consumption_percent_per_minute=drone.consumption_percent_per_minute,
        wind_speed_kmh=problem.wind_speed_kmh, wind_direction_from_deg=0.0,
        minimum_battery_reserve_percent=ctx.minimum_battery_reserve_percent,
        maximum_wind_speed_kmh=drone.max_wind_kmh,
        maximum_altitude_m=site.vertical_limits.max_altitude_m or 120.0, failsafe=FAILSAFE,
        source=f"declared profile of {drone.vehicle_id} ({drone.provenance}); wind direction not declared (0 deg)")
    task = AerialTask(task_id=f"AIR_{drone.vehicle_id}", vehicle_id=drone.vehicle_id, takeoff_point=drone.takeoff_point,
                      poi_sequence=sequence, altitude_m=problem.altitude_m or ctx.altitude_m,
                      requested_speed_kmh=drone.survey_speed_kmh or ctx.requested_speed_kmh)
    return ScenarioTemplate.model_validate({
        "schema": "tfg.scenario-template/1", "template_id": "multiagent_swarm", "version": 1,
        "description": "single-drone task proposed by the Drone/Swarm Agent", "provenance": "SYNTHETIC",
        "planning_margin_m": ctx.planning_margin_m, "mission_defaults": defaults.model_dump(),
        "aerial_tasks": [task.model_dump()], "execution_order": [task.task_id]})


def build_mission(problem: SwarmProblem, drone: DroneProfile, sequence: list[str], route_local) -> MissionDefinition:
    template = drone_template(problem, drone, sequence)
    site, geo, frame = problem.site, problem.site.geo_reference, problem.site.local_frame
    convert = lambda xy: local_to_geo(*xy, origin_latitude=geo.latitude, origin_longitude=geo.longitude,  # noqa: E731
                                      y_axis_bearing_deg=frame.y_axis_bearing_deg)
    task = template.aerial_tasks[0]
    waypoints = [{"waypoint_id": poi, "latitude": convert(xy)[0], "longitude": convert(xy)[1],
                  "altitude_m": task.altitude_m, "speed_kmh": task.requested_speed_kmh, "action": "navigate"}
                 for poi, xy in zip(sequence, route_local[1:-1])]
    return _mission(template, task, problem.fleet.vehicle(drone.vehicle_id), site, convert(route_local[0]), waypoints)


def route_candidate(problem: SwarmProblem, drone: DroneProfile, sequence: list[str]) -> dict:
    """Spatial + deterministic mission validation of one visiting order (point ids) for one drone."""
    ctx = problem.context
    vehicle = problem.fleet.vehicle(drone.vehicle_id)
    spatial = validate_aerial_route(problem.site, drone.takeoff_point, sequence, problem.altitude_m or ctx.altitude_m,
                                    ctx.planning_margin_m, vehicle)
    result = {"vehicle_id": drone.vehicle_id, "sequence": list(sequence), "spatial_status": spatial["status"]}
    if spatial["status"] != "PASS":
        result.update(status="ROUTE_REJECTED", reasons=[f"{c['check']}: {c['detail']}" for c in spatial["checks"]
                                                         if c["status"] == "FAIL"])
        return result
    if not validate_site(problem.site)["capabilities"]["sitl_geographic_export"]:
        result.update(status="ROUTE_REJECTED", reasons=["BLOCKED_MISSING_DATA: site has no geographic reference"])
        return result
    mission = build_mission(problem, drone, list(sequence), spatial["route_local"])
    validation = validate_mission(mission)
    result.update(route_local=spatial["route_local"], length_m=_length(spatial["route_local"]),
                  mission_status=validation.get("mission_status"))
    if validation.get("mission_status") != "FEASIBLE":
        result.update(status="MISSION_INFEASIBLE",
                      reasons=[str(r) for r in (validation.get("failure_reasons") or validation.get("errors") or
                                                ["mission not feasible"])])
        return result
    flight = analyze_mission_flight(mission)
    content = mission_bytes(mission)
    legs = [leg["flight_result"].get("flight_time_minutes_exact") for leg in flight["leg_results"]]
    result.update(status="FEASIBLE", reasons=[], flight_minutes=flight["total_flight_time_minutes_exact"],
                  leg_minutes=legs, labels=spatial["labels"],
                  obstacle_checks=[c for c in spatial["checks"] if c["check"].startswith("exclusion")],
                  mission=mission, mission_sha256=sha256(content),
                  deterministic_validation={k: validation.get(k) for k in ("mission_status", "execution_status",
                                                                           "failure_reasons", "errors")})
    return result


def best_route(problem: SwarmProblem, drone: DroneProfile, objective_ids: frozenset) -> dict:
    """Shortest feasible visiting order for this subset (cached); FEASIBLE or the reasons of the shortest order."""
    key = (drone.vehicle_id, objective_ids)
    if key in problem._routes:
        return problem._routes[key]
    points = sorted({problem.objective(o).point_id for o in objective_ids})
    if len(points) > MAX_ROUTE_POINTS:
        problem._routes[key] = {"vehicle_id": drone.vehicle_id, "sequence": points, "status": "ROUTE_REJECTED",
                                "reasons": [f"ROUTE_POINT_LIMIT: {len(points)} points > {MAX_ROUTE_POINTS}"],
                                "orders_tried": 0}
        return problem._routes[key]
    start = _xy(problem.site, drone.takeoff_point)
    orders = sorted(permutations(points), key=lambda seq: (round(_length([start, *(_xy(problem.site, p) for p in seq),
                                                                          start]), 9), seq))
    first_failure, tried = None, 0
    for order in orders:
        tried += 1
        candidate = route_candidate(problem, drone, list(order))
        if candidate["status"] == "FEASIBLE":
            candidate["orders_tried"] = tried
            problem._routes[key] = candidate
            return candidate
        first_failure = first_failure or candidate
    first_failure = dict(first_failure, orders_tried=tried)
    problem._routes[key] = first_failure
    return first_failure


def _score(plans: dict, covered: int):
    makespan = max((p["flight_minutes"] for p in plans.values()), default=0.0)
    distance = sum(p["length_m"] for p in plans.values())
    return (-covered, round(makespan, 9), round(distance, 9))


def reference_allocation(problem: SwarmProblem) -> dict:
    """Best assignment by (coverage, makespan, distance, ids), with the evidence of the decision."""
    if len(problem.objectives) > MAX_OBJECTIVES:
        return {"status": "REFUSED", "reason": f"REFERENCE_SEARCH_LIMIT: {len(problem.objectives)} objectives > "
                                               f"{MAX_OBJECTIVES}", "assignments": {}, "unassigned": []}
    eligible = {o.objective_id: [d.vehicle_id for d in problem.drones if not eligibility(problem, o, d)]
                for o in problem.objectives}
    matrix = {o.objective_id: {d.vehicle_id: eligibility(problem, o, d) or ["ELIGIBLE"] for d in problem.drones}
              for o in problem.objectives}
    ids = [o.objective_id for o in problem.objectives]
    best = runner_up = None
    evaluated = rejected = 0
    ranked, by_drone_set, truncated = [], {}, False
    deadline = time.perf_counter() + TIME_BUDGET_S
    for choice in product(*[[*eligible[i], None] for i in ids]):
        if time.perf_counter() > deadline:
            truncated = True
            break
        evaluated += 1
        groups = {}
        for objective_id, vehicle_id in zip(ids, choice):
            if vehicle_id is not None:
                groups.setdefault(vehicle_id, set()).add(objective_id)
        plans = {v: best_route(problem, problem.drone(v), frozenset(g)) for v, g in sorted(groups.items())}
        if any(p["status"] != "FEASIBLE" for p in plans.values()):
            rejected += 1
            continue
        covered = sum(len(g) for g in groups.values())
        key = (_score(plans, covered), tuple("" if c is None else c for c in choice))
        entry = {"key": key, "choice": dict(zip(ids, choice)), "plans": plans, "groups": groups}
        ranked = sorted([*ranked, entry], key=lambda e: e["key"])[:MAX_ALTERNATIVES]
        drone_set = tuple(sorted(groups))
        if drone_set not in by_drone_set or key < by_drone_set[drone_set]["key"]:
            by_drone_set[drone_set] = entry
        if best is None or key < best["key"]:
            best, runner_up = entry, best
        elif runner_up is None or key < runner_up["key"]:
            runner_up = entry
    unassigned = []
    for objective_id in ids:
        if best["choice"][objective_id] is not None:
            continue
        if not eligible[objective_id]:
            reasons = [f"{v}: {r}" for v, rs in matrix[objective_id].items() for r in rs]
        else:
            reasons = []
            for vehicle_id in eligible[objective_id]:
                alone = best_route(problem, problem.drone(vehicle_id), frozenset({objective_id}))
                reasons.extend(f"{vehicle_id}: {r}" for r in (alone.get("reasons") or
                               ["COMBINATION_INFEASIBLE: feasible alone, not together with the covered objectives"]))
        unassigned.append({"objective_id": objective_id, "point_id": problem.objective(objective_id).point_id,
                           "reasons": reasons})
    describe = lambda e: None if e is None else {  # noqa: E731
        "assignment": {v: sorted(g) for v, g in sorted(e["groups"].items())}, "covered": -e["key"][0][0],
        "makespan_min": e["key"][0][1], "total_distance_m": e["key"][0][2]}
    assignments = _as_assignments(best)["assignments"]
    alternatives = ranked + sorted((e for e in by_drone_set.values() if all(e is not r for r in ranked)),
                                   key=lambda e: e["key"])
    evidence = {"algorithm": ALGORITHM, "mode": "EXHAUSTIVE", "search_truncated": truncated,
                "optimality": "OPTIMAL_WITHIN_MODEL" if not truncated else "BEST_FOUND_BEFORE_TIME_BUDGET",
                "eligibility": matrix, "assignments_evaluated": evaluated,
                "assignments_rejected_infeasible": rejected, "routes_validated": len(problem._routes),
                "chosen": describe(best), "runner_up": describe(runner_up),
                "inputs_sha256": fingerprint({"objectives": [o.__dict__ for o in problem.objectives],
                                              "drones": [d.model_dump() for d in problem.drones],
                                              "wind_speed_kmh": problem.wind_speed_kmh,
                                              "battery_percent": problem.battery_percent,
                                              "altitude_m": problem.altitude_m, "site": problem.site.site_id,
                                              "site_version": problem.site.version})}
    return {"status": "OK", "assignments": assignments, "unassigned": unassigned, "evidence": evidence,
            "_alternatives": [_as_assignments(e) for e in alternatives]}


def _as_assignments(entry: dict) -> dict:
    """Public shape of one ranked allocation (also used for alternatives)."""
    assignments = {v: {"objective_ids": sorted(entry["groups"][v]), "sequence": p["sequence"],
                       "length_m": p["length_m"], "flight_minutes": p["flight_minutes"], "mission": p["mission"],
                       "mission_sha256": p["mission_sha256"], "deterministic_validation": p["deterministic_validation"],
                       "route_local": p["route_local"], "orders_tried": p["orders_tried"], "labels": p["labels"],
                       "leg_minutes": p["leg_minutes"], "obstacle_checks": p["obstacle_checks"]}
                   for v, p in entry["plans"].items()}
    return {"assignments": assignments, "covered": -entry["key"][0][0], "makespan_min": entry["key"][0][1],
            "total_distance_m": entry["key"][0][2]}


def exhaustive_size(problem: SwarmProblem) -> int:
    size = 1
    for o in problem.objectives:
        size *= 1 + sum(not eligibility(problem, o, d) for d in problem.drones)
    return size


def greedy_allocation(problem: SwarmProblem, drones: list | None = None) -> dict:
    """Bounded heuristic for fleets/objective sets beyond the exhaustive bound. NOT optimal.

    Objectives in order of fewest eligible drones (then id); each goes to the eligible drone whose resulting
    plan keeps the makespan smallest (then total distance, then id), if that plan is FEASIBLE. Cost:
    O(objectives x drones) route evaluations, each at most MAX_ROUTE_POINTS! orders (cached)."""
    drones = drones if drones is not None else problem.drones
    started = time.perf_counter()
    eligible = {o.objective_id: [d.vehicle_id for d in drones if not eligibility(problem, o, d)]
                for o in problem.objectives}
    order = sorted(problem.objectives, key=lambda o: (len(eligible[o.objective_id]), o.objective_id))
    groups, plans, unassigned = {}, {}, []
    for objective in order:
        options = []
        for vehicle_id in sorted(eligible[objective.objective_id]):
            group = frozenset(groups.get(vehicle_id, set()) | {objective.objective_id})
            plan = best_route(problem, problem.drone(vehicle_id), group)
            if plan["status"] != "FEASIBLE":
                continue
            trial = {**plans, vehicle_id: plan}
            options.append((round(max(p["flight_minutes"] for p in trial.values()), 9),
                            round(sum(p["length_m"] for p in trial.values()), 9), vehicle_id, plan))
        if not options:
            reasons = [f"{d.vehicle_id}: {r}" for d in drones for r in eligibility(problem, objective, d)]
            for vehicle_id in sorted(eligible[objective.objective_id]):
                alone = best_route(problem, problem.drone(vehicle_id), frozenset({objective.objective_id}))
                reasons.extend(f"{vehicle_id}: {r}" for r in (alone.get("reasons") or [
                    "NO_FEASIBLE_INSERTION: feasible alone, not together with the objectives already on its route"]))
            unassigned.append({"objective_id": objective.objective_id, "point_id": objective.point_id,
                               "reasons": reasons})
            continue
        _, _, vehicle_id, plan = min(options, key=lambda o: o[:3])
        groups.setdefault(vehicle_id, set()).add(objective.objective_id)
        plans[vehicle_id] = plan
    entry = {"groups": groups, "plans": plans,
             "key": (_score(plans, sum(len(g) for g in groups.values())), ())}
    shaped = _as_assignments(entry)
    evidence = {"algorithm": GREEDY, "mode": "GREEDY", "optimality": "NOT_GUARANTEED",
                "eligibility": {o.objective_id: {d.vehicle_id: eligibility(problem, o, d) or ["ELIGIBLE"] for d in drones}
                                for o in problem.objectives},
                "drones_used_for_search": [d.vehicle_id for d in drones],
                "routes_validated": len(problem._routes), "elapsed_s": round(time.perf_counter() - started, 3),
                "chosen": {"assignment": {v: sorted(g) for v, g in sorted(groups.items())}, "covered": shaped["covered"],
                           "makespan_min": shaped["makespan_min"], "total_distance_m": shaped["total_distance_m"]},
                "runner_up": None}
    return {"status": "OK", "assignments": shaped["assignments"], "unassigned": unassigned, "evidence": evidence}


def allocate(problem: SwarmProblem) -> dict:
    """Exhaustive reference when within bounds, otherwise the greedy heuristic (each result says which)."""
    size = exhaustive_size(problem)
    if len(problem.objectives) <= MAX_OBJECTIVES and size <= MAX_ASSIGNMENTS:
        result = reference_allocation(problem)
    else:
        result = greedy_allocation(problem)
        alternatives = []
        used = sorted(result["assignments"], key=lambda v: (result["assignments"][v]["flight_minutes"], v))
        remaining = [d for d in problem.drones]
        for vehicle_id in used[:-1]:  # replanning candidates with fewer drones (fewer conflicts, less coverage)
            remaining = [d for d in remaining if d.vehicle_id != vehicle_id]
            alternative = greedy_allocation(problem, remaining)
            alternatives.append({"assignments": alternative["assignments"], "covered": alternative["evidence"]["chosen"]["covered"],
                                 "makespan_min": alternative["evidence"]["chosen"]["makespan_min"],
                                 "total_distance_m": alternative["evidence"]["chosen"]["total_distance_m"]})
        result["_alternatives"] = [{"assignments": result["assignments"], **{k: result["evidence"]["chosen"][k] for k in
                                    ("covered", "makespan_min", "total_distance_m")}}, *alternatives]
    result["evidence"]["exhaustive_assignments"] = size
    result["evidence"]["bounds"] = {"max_objectives_exhaustive": MAX_OBJECTIVES, "max_assignments": MAX_ASSIGNMENTS,
                                    "max_route_points": MAX_ROUTE_POINTS, "time_budget_s": TIME_BUDGET_S}
    return result


def evaluate_proposal(problem: SwarmProblem, proposal: dict, reference: dict | None = None) -> dict:
    """Score an allocation proposed by someone else (e.g. a model) with the SAME checks as the reference.

    ``proposal``: {"assignments": {vehicle_id: [objective_id, ...] in visiting order}}. Nothing proposed is
    trusted: unknown ids, duplicates, ineligible drones, invalid routes and infeasible missions are violations.
    """
    reference = reference or reference_allocation(problem)
    violations, plans = [], {}
    raw = proposal.get("assignments") if isinstance(proposal, dict) else None
    if not isinstance(raw, dict):
        return {"structurally_valid": False, "valid": False, "violations": ["PROPOSAL_NOT_AN_ASSIGNMENT_MAP"],
                "coverage_ratio": 0.0, "makespan_ratio": None, "same_assignment_as_reference": False}
    seen = []
    for vehicle_id, objective_ids in sorted(raw.items()):
        drone = problem.drone(vehicle_id)
        if drone is None or not isinstance(objective_ids, list):
            violations.append(f"UNKNOWN_DRONE_OR_LIST: {vehicle_id}")
            continue
        sequence = []
        for objective_id in objective_ids:
            objective = problem.objective(objective_id)
            if objective is None:
                violations.append(f"UNKNOWN_OBJECTIVE: {objective_id}")
                continue
            if objective_id in seen:
                violations.append(f"DUPLICATE_OBJECTIVE: {objective_id}")
            seen.append(objective_id)
            violations.extend(f"INELIGIBLE: {objective_id} -> {r}" for r in eligibility(problem, objective, drone))
            if objective.point_id not in sequence:
                sequence.append(objective.point_id)
        if sequence:
            candidate = route_candidate(problem, drone, sequence)
            plans[vehicle_id] = candidate
            violations.extend(f"{candidate['status']}: {vehicle_id}: {r}" for r in candidate.get("reasons", []))
    covered = len(set(seen) & {o.objective_id for o in problem.objectives})
    ref_covered = sum(len(a["objective_ids"]) for a in reference["assignments"].values())
    valid = not violations
    makespan = max((p.get("flight_minutes", 0.0) for p in plans.values()), default=0.0)
    ref_makespan = reference["evidence"]["chosen"]["makespan_min"] if reference.get("evidence") else None
    same = valid and {v: sorted(o) for v, o in raw.items() if o} == {
        v: a["objective_ids"] for v, a in reference["assignments"].items()}
    return {"structurally_valid": True, "valid": valid, "violations": violations,
            "coverage_ratio": (covered / ref_covered) if ref_covered else (1.0 if covered == 0 else 0.0),
            "makespan_ratio": (ref_makespan / makespan) if valid and makespan > 0 and ref_makespan else None,
            "same_assignment_as_reference": bool(same), "proposed_makespan_min": makespan if valid else None,
            "reference_makespan_min": ref_makespan}
