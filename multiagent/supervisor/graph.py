r"""Hermes Supervisor orchestrated with LangGraph: natural-language mission -> agents -> .plan files -> validation ->
approval -> authorized execution through existing executors -> observed results.

Two compiled LangGraph StateGraphs share one mission directory (the persistent state between processes):

PLANNING   intake -> screen -> registry -> decompose -> delegate_drones -> assign --(replan)--> delegate_drones
                                                                         \-> delegate_rover --(replan)--> delegate_rover
           -> joint_check -> assemble -> generate_plans -> validate -> manifest -> finalize
EXECUTION  load -> gate -> dispatch (loop over the execution order, honouring dependencies) -> results

It reuses, rather than duplicates: the brief/rules interpreter and unsafe-phrase screen (multiagent.interpreters),
the Drone Agent and its deconfliction (multiagent.drone_agent), the strict ArduCopter exporter and verifier
(inputs.qgc_plan_export), the Hermes mission validation + SITL binding (multiagent.hermes_mission_adapter), the H2
request boundary (multiagent.drone_execution_bridge), the rover request bridge (multiagent.rover_executor_bridge),
the tracer and the Opik dry run (multiagent.tracing). The Mission Orchestrator graph (multiagent.orchestrator) stays
the single-target planner for the earlier prototypes; this graph is the multi-vehicle supervisor over the same agents.

The supervisor never authorizes and never commands: approvals are separate human records (approval.py), and the
execution graph only calls adapters (executors.py) after the gate passes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from inputs import qgc_plan_export as copter_export
from inputs import qgc_rover_plan_export as rover_export
from models.fleet import Fleet
from models.site import Site
from planning.scenario_instance import mission_bytes

from multiagent.contracts import load_context
from multiagent.orchestrator import _swarm_summary
from multiagent.supervisor import approval as appr
from multiagent.supervisor import executors as ex
from multiagent.supervisor import plans as pl
from multiagent.supervisor import registry as reg
from multiagent.supervisor import results as res
from multiagent.supervisor import scenario as sc
from multiagent.supervisor import validation as val
from multiagent.supervisor.agents import DroneAgent, RoverAgent, joint_aerial_plan, split_sectors
from multiagent.tracing import Tracer, opik_dry_run

SUPERVISOR = "hermes_supervisor"
MAX_REPLANS = 3
PRODUCER = {"name": "tfg-multiagent-supervisor", "version": "1"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


class PlanState(TypedDict, total=False):
    text: str
    model_intent: dict | None
    mission_id: str
    intent: dict
    decisions: list
    stop: str | None
    reasons: list
    sectors: list
    ground_points: list
    drones: list               # selected drone ids
    rover: str | None
    drone_proposals: list
    assignment: dict | None
    replans: int
    rover_ordering: str
    ground: dict | None
    aerial: dict | None
    plan: dict
    files: dict
    vehicle_validation: dict
    global_validation: dict
    manifest: dict | None
    status: str


class ExecState(TypedDict, total=False):
    mission_dir: str
    mode: str
    executor: str
    session_id: str | None
    now: datetime
    double: object
    approvals: dict | None
    receipt_key: bytes | None
    vehicle_id: str | None
    manifest: dict | None
    proposal: dict
    prior: dict
    obs: dict
    gates: dict
    events: list
    blocked: list
    queue: list
    global_: dict


class Supervisor:
    """One supervisor per scenario. ``plan`` -> mission dir; ``execute`` and ``ingest_report`` act on that dir."""

    def __init__(self, scenario_path: Path | str, *, out_root: Path | str):
        self.scenario_path = Path(scenario_path)
        self.scenario = sc.load_scenario(self.scenario_path)
        self.context = load_context(sc.resolve(self.scenario.context_path))
        self.site = Site.model_validate_json(Path(self.context.resolve(self.context.site_path)).read_text())
        self.fleet = Fleet.model_validate_json(Path(self.context.resolve(self.context.fleet_path)).read_text())
        self.evidence = reg.load_evidence(sc.resolve(self.scenario.evidence_path))
        self.registry = reg.build_registry(self.context, self.fleet, self.evidence, overrides={
            k: v.model_dump() for k, v in self.scenario.availability_overrides.items()})
        self.out_root = Path(out_root)
        self.planning_graph = self._build_planning_graph()
        self.execution_graph = self._build_execution_graph()

    # ================================================================== planning graph
    def _build_planning_graph(self):
        g = StateGraph(PlanState)
        for n in ("intake", "screen", "registry", "decompose", "delegate_drones", "assign", "delegate_rover",
                  "joint_check", "assemble", "generate_plans", "validate", "manifest", "finalize"):
            g.add_node(n, getattr(self, "_" + n))
        g.add_edge(START, "intake")
        g.add_edge("intake", "screen")
        stop = lambda nxt: (lambda s: "finalize" if s.get("stop") else nxt)  # noqa: E731
        g.add_conditional_edges("screen", stop("registry"))
        g.add_conditional_edges("registry", stop("decompose"))
        g.add_conditional_edges("decompose", stop("delegate_drones"))
        g.add_edge("delegate_drones", "assign")
        g.add_conditional_edges("assign", lambda s: "finalize" if s.get("stop") else
                                ("delegate_drones" if s.get("assignment") is None else "delegate_rover"))
        g.add_conditional_edges("delegate_rover", lambda s: "finalize" if s.get("stop") else
                                ("delegate_rover" if (s.get("ground") or {}).get("_replan") else "joint_check"))
        g.add_conditional_edges("joint_check", stop("assemble"))
        g.add_edge("assemble", "generate_plans")
        g.add_conditional_edges("generate_plans", stop("validate"))
        g.add_edge("validate", "manifest")
        g.add_edge("manifest", "finalize")
        g.add_edge("finalize", END)
        return g.compile()

    def _decide(self, state, stage, decision, detail=None):
        entry = {"stage": stage, "decision": decision, "detail": detail, "at": _iso(_now())}
        self.tracer.validation(SUPERVISOR, f"{stage}:{decision}", "INFO", detail)
        return [*(state.get("decisions") or []), entry]

    def _intake(self, state):
        with self.tracer.span(SUPERVISOR, "agent", "intake", inputs={"text": state["text"],
                                                                     "model_intent": state.get("model_intent")}) as span:
            intent, decisions, clarifications = sc.reconcile(state["text"], state.get("model_intent"), self.scenario)
            self.tracer.output(span, intent.model_dump(by_alias=True))
        decisions = [{**d, "stage": "intake", "at": _iso(_now())} for d in decisions]
        out = {"intent": intent.model_dump(by_alias=True), "decisions": decisions, "reasons": [], "replans": 0,
               "rover_ordering": "AS_GIVEN"}
        if clarifications:
            out.update(stop="NEEDS_CLARIFICATION", reasons=clarifications)
        return out

    def _screen(self, state):
        if state.get("stop"):
            return {}
        intent = state["intent"]
        unsafe = intent["unsafe_requests"]
        self.tracer.validation(SUPERVISOR, "unsafe_request_screen", "FAIL" if unsafe else "PASS", unsafe)
        if unsafe:
            return {"stop": "REFUSED_UNSAFE", "reasons": [f"UNSAFE_REQUEST: {u}" for u in unsafe],
                    "decisions": self._decide(state, "screen", "REFUSED_UNSAFE", unsafe)}
        problems = [f"CONTRADICTION: {c}" for c in intent["contradictions"]]
        if not intent["aerial_scope"] and not intent["ground_point_count"] and not intent["ground_points"]:
            problems.append("NO_OBJECTIVES: the request names no aerial area/points and no ground points")
        if intent["wind_speed_kmh"] is None:
            # wind is never invented: the context's declared default applies and is shown to the operator
            state = {**state, "decisions": self._decide(state, "screen", "WIND_FROM_DECLARED_CONTEXT",
                                                        {"wind_speed_kmh": self.context.wind_speed_kmh,
                                                         "provenance": self.context.provenance})}
        if problems:
            return {"stop": "NEEDS_CLARIFICATION", "reasons": problems, "decisions": state.get("decisions")}
        return {"decisions": state.get("decisions")}

    def _registry(self, state):
        intent, decisions, reasons = state["intent"], state.get("decisions") or [], []
        drones_av = [v["vehicle_id"] for v in reg.available(self.registry, "drone")]
        rovers_av = [v["vehicle_id"] for v in reg.available(self.registry, "rover")]
        declared = {v["vehicle_id"] for v in self.registry["vehicles"]}
        unknown = [n for n in intent["named_vehicles"] if n not in declared]
        if unknown:
            return {"stop": "NEEDS_CLARIFICATION", "reasons": [f"VEHICLE_NOT_REGISTERED: {unknown}"]}
        wants_air = bool(intent["aerial_scope"])
        n_drones = intent["drones_requested"] if intent["drones_requested"] is not None else (
            (intent["aerial_sectors"] or 1) if wants_air else 0)
        named = [n for n in intent["named_vehicles"] if n.startswith("drone_")]
        pool = [d for d in (named or [v["vehicle_id"] for v in self.registry["vehicles"] if v["role"] == "drone"])]
        unavailable = [d for d in pool if d not in drones_av]
        for d in unavailable:
            v = reg.vehicle(self.registry, d)
            decisions = self._decide({"decisions": decisions}, "registry", "VEHICLE_UNAVAILABLE",
                                     {"vehicle_id": d, "reason": v["availability"]["reason"]})
        selected = [d for d in pool if d in drones_av][:n_drones] if wants_air else []
        if wants_air and len(selected) < n_drones:
            decisions = self._decide({"decisions": decisions}, "registry", "FEWER_DRONES_THAN_REQUESTED",
                                     {"requested": n_drones, "available": selected,
                                      "action": "replan the sectors over the available drones; shown at approval"})
        if wants_air and not selected:
            reasons.append(f"NO_DRONE_AVAILABLE: requested {n_drones}, available {drones_av}")
        wants_ground = bool(intent["ground_point_count"] or intent["ground_points"] or intent["rovers_requested"])
        rover = None
        if wants_ground:
            named_r = [n for n in intent["named_vehicles"] if n.startswith("rover_")]
            candidates = [r for r in (named_r or [v["vehicle_id"] for v in self.registry["vehicles"]
                                                  if v["role"] == "rover"])]
            rover = next((r for r in candidates if r in rovers_av), None)
            if rover is None:
                why = {r: (reg.vehicle(self.registry, r) or {}).get("availability") for r in candidates}
                reasons.append(f"NO_ROVER_AVAILABLE: {why or 'no rover declared'}")
        self.tracer.validation(SUPERVISOR, "registry", "FAIL" if reasons else "PASS",
                               {"drones": selected, "rover": rover})
        out = {"drones": selected, "rover": rover, "decisions": decisions}
        if reasons:
            out.update(stop="BLOCKED", reasons=reasons + ["no replanning can create a vehicle: execution blocked"])
        return out

    def _decompose(self, state):
        intent, parcel = state["intent"], self.scenario.parcel
        reasons = []
        air_points = intent["aerial_points"] if intent["aerial_scope"] == "POINTS" else (
            list(parcel.aerial_survey_points) if intent["aerial_scope"] == "PARCEL" else [])
        undeclared = [p for p in air_points if self.site.point(p) is None or self.site.point(p).kind != "poi"]
        if undeclared:
            reasons.append(f"AERIAL_POINT_NOT_DECLARED: {undeclared}")
        k = intent["aerial_sectors"] or len(state["drones"]) or 1
        if air_points and k > len(air_points):
            reasons.append(f"MORE_SECTORS_THAN_POINTS: {k} sectors, {len(air_points)} declared points")
        sectors = split_sectors(self.site, air_points, k) if air_points and not reasons else []
        ground = list(intent["ground_points"])
        count = intent["ground_point_count"]
        if not ground and count:
            if count > len(parcel.ground_visit_points):
                reasons.append(f"GROUND_POINTS_NOT_DECLARED: {count} requested, the scenario declares "
                               f"{len(parcel.ground_visit_points)} ({parcel.ground_visit_points})")
            ground = list(parcel.ground_visit_points)[:count]
        elif ground and count and len(ground) != count:
            reasons.append(f"GROUND_POINT_COUNT_MISMATCH: {count} stated, {len(ground)} named")
        decisions = self._decide(state, "decompose", "SECTORS_AND_GROUND_POINTS",
                                 {"sectors": sectors, "ground_points": ground,
                                  "source": "declared scenario points" if intent["aerial_scope"] == "PARCEL"
                                  else "explicit points in the request"})
        if reasons:
            return {"stop": "NEEDS_CLARIFICATION", "reasons": reasons, "decisions": decisions}
        return {"sectors": sectors, "ground_points": ground, "decisions": decisions}

    def _wind(self, state):
        w = state["intent"]["wind_speed_kmh"]
        return w if w is not None else self.context.wind_speed_kmh

    def _delegate_drones(self, state):
        props = []
        with self.tracer.span(SUPERVISOR, "agent", "delegate_drones",
                              inputs={"drones": state["drones"], "sectors": state["sectors"]}):
            for vid in state["drones"]:
                agent = DroneAgent(vid)
                for sector in state["sectors"]:
                    props.append(agent.propose(sector, context=self.context, site=self.site, fleet=self.fleet,
                                               wind_speed_kmh=self._wind(state),
                                               battery_percent=state["intent"]["battery_percent"],
                                               altitude_m=state["intent"]["altitude_m"], tracer=self.tracer))
        return {"drone_proposals": props, "assignment": None}

    def _assign(self, state):
        sectors, drones = state["sectors"], state["drones"]
        if not sectors:
            return {"assignment": {}}
        ok = {(p["vehicle_id"], p["sector_id"]): p for p in state["drone_proposals"] if p["status"] == "FEASIBLE"}
        best = None
        if len(drones) >= len(sectors):
            for perm in itertools.permutations(drones, len(sectors)):
                pairs = list(zip(perm, sectors))
                if all((d, s["sector_id"]) in ok for d, s in pairs):
                    times = [ok[(d, s["sector_id"])]["flight_minutes"] for d, s in pairs]
                    key = (max(times), sum(times), perm)
                    if best is None or key < best[0]:
                        best = (key, {d: s["points"] for d, s in pairs})
        if best is not None:
            decisions = self._decide(state, "assign", "SECTORS_ASSIGNED", {
                "assignment": best[1], "criterion": "feasible for each drone agent; minimum makespan, then total time",
                "makespan_min": best[0][0]})
            return {"assignment": best[1], "decisions": decisions}
        refusals = [{k: p[k] for k in ("agent", "sector_id", "reasons")} for p in state["drone_proposals"]
                    if p["status"] != "FEASIBLE"]
        replans = state.get("replans", 0)
        if replans >= MAX_REPLANS:
            return {"stop": "INFEASIBLE", "reasons": ["NO_FEASIBLE_SECTOR_ASSIGNMENT after replanning"]
                    + [f"{r['agent']} {r['sector_id']}: {r['reasons'][0]}" for r in refusals]}
        # replan: (1) fewer drones than sectors -> merge sectors; (2) otherwise split into more, smaller sectors
        # when another available drone exists; else merge infeasible pairs is impossible -> infeasible
        points = [p for s in sectors for p in s["points"]]
        capable = [d for d in drones if any(k[0] == d for k in ok)]
        if capable and len(capable) < len(drones):
            dropped = sorted(set(drones) - set(capable))
            drones, k = capable, min(len(capable), len(sectors))
            action = f"DROP_DRONE_WITHOUT_FEASIBLE_SECTOR {dropped} AND_RESPLIT"
        elif len(drones) < len(sectors):
            k = len(drones)
            action = "MERGE_SECTORS_TO_AVAILABLE_DRONES"
        else:
            spare = [v["vehicle_id"] for v in reg.available(self.registry, "drone") if v["vehicle_id"] not in drones]
            if spare and len(points) > len(sectors):
                drones = drones + spare[:1]
                k = len(sectors) + 1
                action = "ADD_AVAILABLE_DRONE_AND_SPLIT_SECTORS"
            else:
                return {"stop": "INFEASIBLE", "reasons": ["NO_FEASIBLE_SECTOR_ASSIGNMENT: every alternative fails"]
                        + [f"{r['agent']} {r['sector_id']}: {r['reasons'][0]}" for r in refusals],
                        "decisions": self._decide(state, "assign", "INFEASIBLE_NO_ALTERNATIVE", refusals)}
        new = split_sectors(self.site, points, k)
        decisions = self._decide(state, "replan", action, {"refusals": refusals, "new_sectors": new,
                                                          "drones": drones, "attempt": replans + 1,
                                                          "deviates_from_request": True})
        return {"sectors": new, "drones": drones, "replans": replans + 1, "assignment": None,
                "decisions": decisions}

    def _delegate_rover(self, state):
        if not state["ground_points"]:
            return {"ground": None}
        ordering = state.get("rover_ordering", "AS_GIVEN")
        ret = state["intent"]["return_to_start"]
        with self.tracer.span(SUPERVISOR, "agent", "delegate_rover",
                              inputs={"rover": state["rover"], "points": state["ground_points"], "ordering": ordering}):
            route = RoverAgent(state["rover"]).propose(state["ground_points"], context=self.context, site=self.site,
                                                       fleet=self.fleet, limits=self.scenario.rover_limits,
                                                       return_to_start=bool(ret), ordering=ordering,
                                                       tracer=self.tracer)
        decisions = state.get("decisions")
        if ret is None:
            decisions = self._decide({"decisions": decisions}, "delegate_rover", "RETURN_NOT_REQUESTED",
                                     "the rover ends at its last point; no return is invented")
        kinds = {f["kind"] for f in route["findings"]}
        geometric = kinds & {"ROUTE_NOT_FEASIBLE", "LEG_TOO_LONG", "ROUTE_TOO_LONG", "BATTERY_INSUFFICIENT"}
        if route["status"] == "INFEASIBLE" and geometric and ordering == "AS_GIVEN" and \
                not state["intent"]["ground_points"]:
            decisions = self._decide({"decisions": decisions}, "replan", "ROVER_REORDER_MIN_MAX_LEG",
                                     {"findings": route["findings"]})
            return {"ground": {"_replan": True}, "rover_ordering": "MIN_MAX_LEG", "decisions": decisions}
        if route["status"] in ("INFEASIBLE", "NEEDS_CLARIFICATION"):
            return {"ground": route, "decisions": decisions,
                    "stop": "INFEASIBLE" if route["status"] == "INFEASIBLE" else "NEEDS_CLARIFICATION",
                    "reasons": [f"{state['rover']}: {f['kind']}: {f['detail']}" for f in route["findings"]]}
        return {"ground": route, "decisions": decisions}

    def _joint_check(self, state):
        assignment = state.get("assignment") or {}
        if not assignment:
            return {"aerial": None}
        aerial, artifacts, objectives = joint_aerial_plan(
            assignment, context=self.context, site=self.site, fleet=self.fleet, wind_speed_kmh=self._wind(state),
            battery_percent=state["intent"]["battery_percent"], altitude_m=state["intent"]["altitude_m"],
            tracer=self.tracer)
        self._artifacts, self._objectives = artifacts, objectives
        covered = {o for p in aerial["proposals"] for o in p["objective_ids"]}
        if aerial["incompatible"] or covered != {o.objective_id for o in objectives} or \
                aerial["status"] not in ("PROPOSED_PENDING_AUTHORIZATION",):
            return {"aerial": aerial, "stop": "INFEASIBLE",
                    "reasons": [f"JOINT_AERIAL_CHECK: {aerial['status']}"]
                    + [f"{i['objective_id']}: {r}" for i in aerial["incompatible"] for r in i["reasons"]]}
        sw = _swarm_summary(aerial)
        decisions = self._decide(state, "joint_check", "AERIAL_PLAN_DECONFLICTED",
                                 {"coordination": (sw or {}).get("status"), "schedule": (sw or {}).get("schedule")})
        return {"aerial": aerial, "decisions": decisions}

    def _assemble(self, state):
        aerial, ground = state.get("aerial"), state.get("ground")
        air_tasks = []
        for p in (aerial or {}).get("proposals", []):
            air_tasks.append({k: p[k] for k in ("task_id", "vehicle_id", "objective_ids", "poi_sequence",
                                                "takeoff_point", "length_m", "flight_minutes", "mission_sha256",
                                                "start_delay_s", "route_local")})
        deps, decisions = [], state.get("decisions")
        if ground and air_tasks:
            # timing of the rover is not modelled: any proximity is resolved by ordering (rover after drones)
            policy = self.context.separation_policy
            required = policy.required_distance_m() if policy else None
            rover_route = [(w["x_m"], w["y_m"]) for w in [ground["start"], *ground["waypoints"]]]
            for t in air_tasks:
                d = val.min_distance([tuple(x) for x in t["route_local"]], rover_route)
                if required is None or d is None or d < required:
                    deps.append({"task_id": ground["task_id"], "after": t["task_id"], "condition": "COMPLETED",
                                 "reason": f"air-ground proximity {d:.2f} m < {required} m: sequential"
                                 if required is not None and d is not None else "no separation policy declared"})
            decisions = self._decide({"decisions": decisions}, "assemble", "AIR_GROUND_ORDERING", deps)
        order = [t["task_id"] for t in sorted(air_tasks, key=lambda t: (t["start_delay_s"] or 0, t["vehicle_id"]))]
        if ground:
            order.append(ground["task_id"])
        plan = {"sectors": state["sectors"], "ground_points": state["ground_points"], "aerial_tasks": air_tasks,
                "ground_task": ground, "dependencies": deps, "execution_order": order,
                "swarm_coordination": _swarm_summary(aerial) if aerial else None,
                "assignment": state.get("assignment")}
        return {"plan": plan, "decisions": decisions}

    def _generate_plans(self, state):
        plan, mdir = state["plan"], self.mission_dir
        files = {}
        amsl = self.site.vertical_reference.origin_ground_amsl_m if self.site.vertical_reference else None
        try:
            for t in plan["aerial_tasks"]:
                vid = t["vehicle_id"]
                data = self._artifacts["plans"].get(vid)
                if data is None:
                    raise ValueError(f"{vid}: the drone agent produced no .plan (export refused or not profiled)")
                name = pl.plan_filename(vid, "drone")
                mission = self._artifacts["missions"][vid]
                mbytes = mission_bytes(mission)
                files[vid] = {"role": "drone", "plan_path": f"plans/{name}",
                              "plan_sha256": pl.write_once(mdir / "plans" / name, data),
                              "mission_path": f"plans/{name.replace('.plan', '.mission.json')}",
                              "mission_sha256": pl.write_once(mdir / "plans" / name.replace(".plan", ".mission.json"),
                                                              mbytes)}
                if files[vid]["mission_sha256"] != t["mission_sha256"]:
                    raise ValueError(f"{vid}: PLAN_MODIFIED_AFTER_VALIDATION (mission bytes differ)")
                files[vid]["verify"] = copter_export.verify_plan(mdir / "plans" / name, mission,
                                                                 planned_home_amsl_m=amsl)
            g = plan["ground_task"]
            if g is not None:
                if g["status"] != "PROPOSED_PENDING_AUTHORIZATION":
                    raise ValueError(f"{g['vehicle_id']}: ground route {g['status']}: "
                                     + "; ".join(f["kind"] for f in g["findings"]))
                start = (g["start"]["latitude"], g["start"]["longitude"])
                body, _log = rover_export.build_rover_plan(start=start, waypoints=g["waypoints"],
                                                           speed_mps=g["speed_limit_mps"], planned_home_amsl_m=amsl,
                                                           return_to_start=g["return_to_start"])
                data = rover_export.plan_bytes(body)
                name = pl.plan_filename(g["vehicle_id"], "rover")
                files[g["vehicle_id"]] = {"role": "rover", "plan_path": f"plans/{name}",
                                          "plan_sha256": pl.write_once(mdir / "plans" / name, data),
                                          "verify": rover_export.verify_rover_plan(
                                              data, start=start, waypoints=g["waypoints"],
                                              speed_mps=g["speed_limit_mps"], return_to_start=g["return_to_start"])}
        except (ValueError, pl.WriteOnceError, copter_export.ExportRefused, rover_export.RoverExportRefused) as exc:
            return {"stop": "BLOCKED", "reasons": [f"PLAN_GENERATION: {exc}"], "files": files}
        for vid, f in files.items():
            f["header"] = pl.plan_header((mdir / f["plan_path"]).read_bytes())
            self.tracer.validation(SUPERVISOR, f"plan_file:{vid}", f["verify"]["status"],
                                   {"sha256": f["plan_sha256"], "header": f["header"]})
        return {"files": files}

    def orchestrator_proposal(self, state) -> dict:
        """The Mission Orchestrator proposal shape the existing drone adapter (adapt_proposal) consumes."""
        plan, aerial = state["plan"], state.get("aerial") or {"proposals": [], "incompatible": []}
        brief = {"aerial_objectives": [{"objective_id": o.objective_id, "point_id": o.point_id, "required_sensor": None}
                                       for o in getattr(self, "_objectives", [])],
                 "wind_speed_kmh": self._wind(state), "battery_percent": state["intent"]["battery_percent"],
                 "altitude_m": state["intent"]["altitude_m"]}
        body = {"mission_id": state["mission_id"], "status": "PROPOSED_PENDING_AUTHORIZATION",
                "aerial": aerial, "brief": brief,
                "template": {"dependencies": [], "execution_order": [t["task_id"] for t in plan["aerial_tasks"]]},
                "swarm_coordination": plan["swarm_coordination"],
                "tasks": [{"task_id": t["task_id"], "vehicle_id": t["vehicle_id"], "state": "PENDING_AUTHORIZATION"}
                          for t in plan["aerial_tasks"]]}
        return {**body, "proposal_sha256": pl.digest(body)}

    def _validate(self, state):
        files, plan = state["files"], state["plan"]
        per = {}
        drones = [t for t in plan["aerial_tasks"]]
        adapted = None
        if drones:
            from multiagent.hermes_mission_adapter import adapt_proposal
            adapted = adapt_proposal(self.orchestrator_proposal(state), context=self.context, site=self.site,
                                     fleet=self.fleet, source={"kind": "SUPERVISOR_PLAN"})
            self._adapted = adapted
        for vid, f in files.items():
            problems = [] if f["verify"]["status"] == "FILE_MATCHES_EXPECTATIONS" else [
                f"PLAN_FILE: {c['check']}" for c in f["verify"]["checks"] if not c["ok"]]
            if f["role"] == "drone":
                rec = next((d for d in adapted["drones"] if d["vehicle_id"] == vid), None)
                if rec is None or rec["state"] != "PLANNING_VALID":
                    problems += [f"{x['kind']}: {x['detail']}" for x in (rec or {}).get("findings", [])] or \
                        ["HERMES_VALIDATION_MISSING"]
                elif rec["mission_sha256"] != f["mission_sha256"] or rec["qgc_plan"].get("sha256") != f["plan_sha256"]:
                    problems.append("PLAN_MODIFIED_AFTER_VALIDATION: rebuilt mission/.plan differ from the files")
                f["hermes_validation"] = (rec or {}).get("hermes_validation")
                f["sitl_binding"] = (rec or {}).get("sitl_binding")
            per[vid] = {"status": "PASS" if not problems else "FAIL", "problems": problems}
            self.tracer.validation(SUPERVISOR, f"vehicle_validation:{vid}", per[vid]["status"], problems)
        glob = val.validate_global(plan=plan, registry=self.registry,
                                   separation_policy=self.context.separation_policy, files=files)
        self.tracer.validation(SUPERVISOR, "global_validation", glob["status"],
                               [c for c in glob["checks"] if c["status"] != "PASS"])
        return {"vehicle_validation": per, "global_validation": glob, "files": files}

    def _manifest(self, state):
        plan, files = state["plan"], state["files"]
        entries = []
        tasks = {t["vehicle_id"]: t["task_id"] for t in plan["aerial_tasks"]}
        if plan["ground_task"]:
            tasks[plan["ground_task"]["vehicle_id"]] = plan["ground_task"]["task_id"]
        for vid, f in sorted(files.items()):
            v = reg.vehicle(self.registry, vid)
            entries.append({"vehicle_id": vid, "role": f["role"], "vehicle_class": v["vehicle_class"],
                            "task_id": tasks[vid], "mandatory": True,
                            "plan": {"path": f["plan_path"], "sha256": f["plan_sha256"],
                                     "profile": copter_export.PROFILE if f["role"] == "drone" else rover_export.PROFILE,
                                     "firmwareType": f["header"]["firmwareType"],
                                     "vehicleType": f["header"]["vehicleType"], "items": f["header"]["items"]},
                            **({"mission_json": {"path": f["mission_path"], "sha256": f["mission_sha256"]}}
                               if f["role"] == "drone" else {}),
                            "sitl_binding": f.get("sitl_binding"), "executor": v["executor"],
                            "validation": state["vehicle_validation"][vid]["status"]
                            if state["global_validation"]["status"] == "PASS" else "FAIL"})
        manifest = pl.build_manifest(
            mission_id=state["mission_id"], scenario_id=self.scenario.scenario_id, data_kind=self.context.provenance,
            intent_sha256=pl.digest(state["intent"]), proposal_sha256=pl.digest(plan), entries=entries,
            dependencies=plan["dependencies"], execution_order=plan["execution_order"], created_at=_iso(_now()))
        pl.write_json_once(self.mission_dir / "manifest.json", manifest)
        return {"manifest": manifest}

    def _finalize(self, state):
        mdir = self.mission_dir
        status = state.get("stop") or ("PLANNED" if state.get("global_validation", {}).get("status") == "PASS"
                                       and all(v["status"] == "PASS" for v in state["vehicle_validation"].values())
                                       else "BLOCKED")
        reasons = list(state.get("reasons") or [])
        if status == "BLOCKED" and not reasons:
            reasons = [f"VALIDATION: {c['check']}: {c['detail']}" for c in state["global_validation"]["checks"]
                       if c["status"] != "PASS"] + [f"{vid}: {p}" for vid, v in state["vehicle_validation"].items()
                                                    for p in v["problems"]]
        deviations = [d for d in state.get("decisions") or [] if (d.get("detail") or {}) and isinstance(d["detail"], dict)
                      and d["detail"].get("deviates_from_request")] + \
            [d for d in state.get("decisions") or [] if d.get("decision") == "MODEL_INFERRED"]
        plan = state.get("plan")
        proposal = {"schema": "tfg.multiagent.supervisor-plan/1", "mission_id": state["mission_id"], "status": status,
                    "reasons": reasons, "text": state["text"], "intent": state.get("intent"),
                    "scenario_id": self.scenario.scenario_id, "data_kind": self.context.provenance,
                    "plan": plan, "vehicle_validation": state.get("vehicle_validation"),
                    "global_validation": state.get("global_validation"), "deviations_from_request": deviations,
                    "orchestrator_proposal": self.orchestrator_proposal(state) if plan else None,
                    "authorization": {"required": True, "granted": False,
                                      "how": "per vehicle: python -m multiagent.supervisor approve"},
                    "movement_authorized": False, "commands_sent": 0}
        pl.write_json(mdir / "proposal.json", proposal)
        pl.write_json(mdir / "decisions.json", state.get("decisions") or [])
        pl.write_json(mdir / "registry.json", self.registry)
        manifest = state.get("manifest")
        vresults = []
        for v in (manifest or {}).get("vehicles") or []:
            vr = res.vehicle_result(v, validation=v["validation"], approval=None, gate=None, obs=None,
                                    errors=state["vehicle_validation"][v["vehicle_id"]]["problems"], safeflight=None)
            res.write_vehicle(mdir / "results", vr)
            vresults.append(vr)
        self.tracer.validation(SUPERVISOR, "finalize", status, reasons[:10])
        self._write_trace(mdir)
        glob = res.global_result(manifest=manifest, mission_id=state["mission_id"],
                                 planning_status="PLANNED" if status == "PLANNED" else status, vehicles=vresults,
                                 reasons=reasons, decisions_sha256=pl.digest(state.get("decisions") or []),
                                 trace_sha256=self.tracer.summary()["trace_sha256"])
        pl.write_json(mdir / "results" / "global_result.json", glob)
        return {"status": status, "reasons": reasons}

    def _write_trace(self, mdir: Path):
        self.tracer.write(mdir / "trace" / "trace.jsonl")
        try:
            dry = opik_dry_run(self.tracer.records, "tfg-multiagent-supervisor")
        except Exception as exc:  # noqa: BLE001 - Opik is optional; the local trace is the record
            dry = {"status": "OPIK_DRY_RUN_UNAVAILABLE", "error": f"{type(exc).__name__}: {exc}"[:300]}
        pl.write_json(mdir / "trace" / "opik_dry_run.json", dry)

    def plan(self, text: str, *, model_intent: dict | None = None, intent_provenance: dict | None = None) -> dict:
        """``intent_provenance``: where a model intent came from (providers.model_intent records: provider, model,
        run id, latency, status, hashes). Stored with the request; credentials never reach it."""
        stamp = _now().strftime("%Y%m%dT%H%M%SZ")
        import uuid
        mission_id = f"SUP-{stamp}-" + pl.digest({"text": text, "scenario": self.scenario.scenario_id,
                                                  "intent": model_intent, "nonce": uuid.uuid4().hex})[:10]
        self.mission_dir = self.out_root / mission_id
        if self.mission_dir.exists():
            raise FileExistsError(f"{self.mission_dir} exists: a mission directory is never reused")
        self.mission_dir.mkdir(parents=True)
        pl.write_json_once(self.mission_dir / "request.json", {"text": text, "model_intent": model_intent,
                                                                "scenario_path": str(self.scenario_path),
                                                                "scenario_id": self.scenario.scenario_id,
                                                                "intent_provenance": intent_provenance})
        self.tracer = Tracer(mission_id=mission_id, data_kind="SYNTHETIC")
        self._artifacts, self._objectives, self._adapted = {"plans": {}, "missions": {}}, [], None
        with self.tracer.span(SUPERVISOR, "agent", "mission", inputs={"text": text}) as span:
            final = self.planning_graph.invoke({"text": text, "model_intent": model_intent, "mission_id": mission_id},
                                               {"recursion_limit": 60})
            self.tracer.output(span, {"status": final["status"]})
        self._write_trace(self.mission_dir)
        return {"mission_id": mission_id, "mission_dir": str(self.mission_dir), "status": final["status"],
                "reasons": final.get("reasons") or []}

    # ================================================================== execution graph
    def _build_execution_graph(self):
        g = StateGraph(ExecState)
        for n in ("load", "gate", "dispatch", "results"):
            g.add_node(n, getattr(self, "_x_" + n))
        g.add_edge(START, "load")
        g.add_conditional_edges("load", lambda s: "results" if s.get("blocked") else "gate")
        g.add_edge("gate", "dispatch")
        g.add_conditional_edges("dispatch", lambda s: "dispatch" if s.get("queue") else "results")
        g.add_edge("results", END)
        return g.compile()

    def _x_load(self, s):
        mdir = Path(s["mission_dir"])
        manifest, problems = pl.check_manifest(mdir)
        proposal = json.loads((mdir / "proposal.json").read_bytes())
        state_path = mdir / "execution" / "state.json"
        prior = json.loads(state_path.read_bytes()) if state_path.exists() else {"vehicles": {}}
        out = {"manifest": manifest, "proposal": proposal, "prior": prior, "obs": dict(prior.get("obs") or {}),
               "gates": {}, "events": list(prior.get("events") or [])}
        if proposal["status"] != "PLANNED":
            problems.append(f"MISSION_NOT_PLANNED: {proposal['status']}")
        if problems:
            out["blocked"] = problems
        return out

    def _x_gate(self, s):
        manifest, mdir, now = s["manifest"], Path(s["mission_dir"]), s["now"]
        gates = {}
        for v in manifest["vehicles"]:
            vid = v["vehicle_id"]
            reasons = []
            if v["validation"] != "PASS":
                reasons.append("PLAN_NOT_VALIDATED")
            rec = (s.get("approvals") or {}).get(vid)
            if rec is None:
                p = mdir / "approvals" / f"{vid}.approval.json"
                rec = json.loads(p.read_bytes()) if p.exists() else None
            plan_sha = pl.sha256_file(mdir / v["plan"]["path"])
            mj = pl.sha256_file(mdir / v["mission_json"]["path"]) if v.get("mission_json") else None
            found = appr.check(rec, manifest, vid, now=now, mode=s["mode"], session_id=s.get("session_id"),
                               plan_sha256_on_disk=plan_sha, mission_json_sha256_on_disk=mj) if rec else \
                ["NOT_APPROVED: no approval record for this vehicle"]
            reasons += found
            want = s.get("vehicle_id")
            if want is not None and want != vid:
                continue
            cap = reg.execution_capability(self.registry, vid)
            identity = (v.get("sitl_binding") or {}).get("vehicle_id")
            if v["role"] == "drone" and identity != vid:
                reasons.append(f"VEHICLE_IDENTITY_MISMATCH: sim binding {identity!r} for {vid}")
            reg_v = reg.vehicle(self.registry, vid)
            if reg_v is None or reg_v["vehicle_class"] != v["vehicle_class"]:
                reasons.append("VEHICLE_CLASS_MISMATCH with the registry")
            executor = s["executor"]
            if executor == "test-double":
                if s["mode"] != "OFFLINE_TEST":
                    reasons.append("TEST_DOUBLE_ONLY_IN_OFFLINE_TEST")
            elif not cap["executable_real"]:
                reasons += cap["reasons"]
            gates[vid] = {"status": "PASS" if not reasons else "REFUSED", "reasons": reasons,
                          "capability": cap, "approval_id": (rec or {}).get("approval_id"),
                          "safety_checks": "DEFERRED_TO_PROTECTED_ENTRY (readiness, failsafes, lock)"
                          if executor != "test-double" else "NOT_APPLICABLE_TEST_DOUBLE", "checked_at": _iso(now),
                          "_approval": rec}
            self.tracer.validation(SUPERVISOR, f"execution_gate:{vid}", gates[vid]["status"], reasons)
        order = [t for t in manifest["execution_order"]]
        by_task = {v["task_id"]: v["vehicle_id"] for v in manifest["vehicles"]}
        queue = [by_task[t] for t in order if by_task.get(t) in gates]
        return {"gates": gates, "queue": queue}

    def _x_dispatch(self, s):
        queue, manifest, mdir = list(s["queue"]), s["manifest"], Path(s["mission_dir"])
        vid = queue.pop(0)
        v = appr.entry(manifest, vid)
        obs, gate = dict(s["obs"]), s["gates"][vid]
        state_of = lambda t: next((o["execution_status"] for o in obs.values() if o["task_id"] == t), None)  # noqa: E731
        preds = [d for d in manifest["dependencies"] if d["task_id"] == v["task_id"]]
        failed = [d["after"] for d in preds if state_of(d["after"]) in ("FAILED", "ABORTED", "TIMEOUT",
                                                                        "CANCELLED_DEPENDENCY")]
        pending = [d["after"] for d in preds if state_of(d["after"]) != "COMPLETED"]
        events = list(s["events"])
        if obs.get(vid, {}).get("execution_status") in ex.EXECUTED_STATES:
            events.append({"vehicle_id": vid, "event": "ALREADY_EXECUTED_NOT_REPEATED", "at": _iso(s["now"])})
            return {"queue": queue, "events": events}
        if gate["status"] != "PASS":
            request = None
            if v["role"] == "rover" and gate.get("_approval") and s["executor"] == "real" and \
                    all(r.startswith("CAPABILITY_NOT_DEMONSTRATED") for r in gate["reasons"]):
                data = (mdir / v["plan"]["path"]).read_bytes()  # the request the missing executor would receive
                request = self._dispatch_rover(s, v, data, pl.sha256_bytes(data), gate)["request"]
            obs[vid] = ex.observation(vid, v["task_id"], data_kind="NONE", status="BLOCKED",
                                      plan_sha256=v["plan"]["sha256"], failure_reason="; ".join(gate["reasons"]),
                                      executor="supervisor_gate", request=request)
        elif failed:
            obs[vid] = ex.observation(vid, v["task_id"], data_kind="NONE", status="CANCELLED_DEPENDENCY",
                                      plan_sha256=v["plan"]["sha256"],
                                      failure_reason=f"predecessor(s) did not complete: {failed}",
                                      executor="supervisor_gate")
        elif pending and s["executor"] == "test-double":
            obs[vid] = ex.observation(vid, v["task_id"], data_kind="NONE", status="BLOCKED",
                                      plan_sha256=v["plan"]["sha256"],
                                      failure_reason=f"DEPENDENCY_NOT_COMPLETED: {pending}", executor="supervisor_gate")
        else:
            data = (mdir / v["plan"]["path"]).read_bytes()
            sha = pl.sha256_bytes(data)
            with self.tracer.span(SUPERVISOR, "tool", f"dispatch:{vid}", inputs={"executor": s["executor"]}) as span:
                if s["executor"] == "test-double":
                    obs[vid] = s["double"].execute(v, plan_bytes=data, plan_sha256=sha, mode=s["mode"])
                elif v["role"] == "drone":
                    obs.update(self._dispatch_drone(s, v, sha, pending, obs))
                else:
                    obs[vid] = self._dispatch_rover(s, v, data, sha, gate)
                self.tracer.output(span, {"status": obs[vid]["execution_status"], "data_kind": obs[vid]["data_kind"]})
        events.append({"vehicle_id": vid, "event": obs[vid]["execution_status"], "at": _iso(s["now"]),
                       "data_kind": obs[vid]["data_kind"]})
        return {"queue": queue, "obs": obs, "events": events}

    def _dispatch_drone(self, s, v, sha, pending, obs):
        """All gated drones not yet handled are prepared TOGETHER: two drones -> the H2 sequence (the path that flew
        on 24/10/2026, second only after the first PASSED), one drone -> the single-vehicle preflight."""
        if pending:
            return {v["vehicle_id"]: ex.observation(v["vehicle_id"], v["task_id"], data_kind="NONE", status="BLOCKED",
                                                    plan_sha256=sha, failure_reason=f"DEPENDENCY_NOT_COMPLETED: {pending}",
                                                    executor=ex.DroneH2RequestAdapter.kind)}
        group = [x for x in s["manifest"]["vehicles"] if x["role"] == "drone" and x["vehicle_id"] not in obs
                 and (s["gates"].get(x["vehicle_id"]) or {}).get("status") == "PASS"]
        proposal = s["proposal"]["orchestrator_proposal"]
        statement = " | ".join(s["gates"][x["vehicle_id"]]["_approval"]["statement"] for x in group)
        out = ex.DroneH2RequestAdapter().prepare(
            group, orchestrator_proposal=proposal, context=self.context, site=self.site, fleet=self.fleet,
            request_dir=Path(s["mission_dir"]) / "execution" / "h2_request",
            request_key=f"{s['manifest']['mission_id']}-drones", statement=statement, mode=s["mode"])
        status = out.get("status")
        ready = status == "READY_TO_REQUEST_EXECUTION"
        why = None if ready else "; ".join((out.get("boundary") or {}).get("problems") or
                                           [f["detail"] for f in out.get("findings", [])] or [str(status)])
        request = {k: out[k] for k in out if k != "findings"}
        return {x["vehicle_id"]: ex.observation(
            x["vehicle_id"], x["task_id"], data_kind="NONE", status="READY_TO_REQUEST_EXECUTION" if ready else "BLOCKED",
            plan_sha256=x["plan"]["sha256"], failure_reason=why, executor=ex.DroneH2RequestAdapter.kind,
            request=request) for x in group}

    def _dispatch_rover(self, s, v, data, sha, gate):
        proposal = s["proposal"]
        out = ex.RoverPlanAdapter().prepare(v, ground=proposal["plan"]["ground_task"], site=self.site, plan_bytes=data,
                                            plan_sha256=sha, manifest=s["manifest"], approval=gate["_approval"],
                                            session_id=s.get("session_id"),
                                            plan_path=Path(s["mission_dir"]) / v["plan"]["path"])
        return ex.observation(v["vehicle_id"], v["task_id"], data_kind="NONE", status="BLOCKED", plan_sha256=sha,
                              failure_reason=out["reasons"][0], executor=ex.RoverPlanAdapter.kind, request=out)

    def _x_results(self, s):
        mdir = Path(s["mission_dir"])
        manifest, obs, gates = s.get("manifest"), dict(s.get("obs") or {}), s.get("gates") or {}
        clean_gates = {k: {x: y for x, y in g.items() if x != "_approval"} for k, g in gates.items()}
        pl.write_json(mdir / "execution" / "state.json", {"obs": obs, "gates": clean_gates, "events": s.get("events"),
                                                          "blocked": s.get("blocked"), "updated_at": _iso(_now())})
        vresults = []
        for v in (manifest or {}).get("vehicles") or []:
            vid = v["vehicle_id"]
            o = obs.get(vid)
            sf = None
            run_dir = mdir / "results" / vid
            if o is not None and o["execution_status"] in res.SF_STATUS:
                evidence = res.copy_evidence(o, run_dir) if o["data_kind"] == "REAL_SITL" else \
                    [res.write_synthetic_log(run_dir, o)]
                run_id = f"{manifest['mission_id']}.{vid}.{o['data_kind'].lower()}"
                env = {"simulator": "gazebo" if o["data_kind"] == "REAL_SITL" else "synthetic",
                       "ardupilot_version": "reported by the executor report" if o["data_kind"] == "REAL_SITL"
                       else "synthetic"}
                result = res.safeflight_result(o, v, plan_name=v["plan"]["path"].split("/")[-1], run_id=run_id,
                                               group_id=manifest["mission_id"], created_at=_iso(_now()),
                                               producer=PRODUCER, environment=env, evidence=evidence)
                pl.write_json(run_dir / "result.json", result)
                if s.get("receipt_key") is not None and not result["synthetic"]:
                    res.write_receipt(run_dir, result, s["receipt_key"])
                sf = {"path": f"results/{vid}/result.json", "synthetic": result["synthetic"],
                      "verdict": result["verdict"]["result"],
                      "receipt": (run_dir / "result.receipt.json").exists()}
            g = gates.get(vid) or (s.get("prior", {}).get("gates") or {}).get(vid)
            errors = list((g or {}).get("reasons") or []) + list(s.get("blocked") or [])
            if o and o.get("failure_reason") and o["failure_reason"] != "; ".join(errors):
                errors.append(o["failure_reason"])
            vr = res.vehicle_result(v, validation=v["validation"], approval=(g or {}).get("_approval") or (
                {"approval_id": g.get("approval_id"), "source": None} if g and g.get("approval_id") else None),
                gate={k: x for k, x in (g or {}).items() if k != "_approval"} or None, obs=o, errors=errors,
                safeflight=sf)
            res.write_vehicle(mdir / "results", vr)
            vresults.append(vr)
        proposal = s.get("proposal") or {}
        reasons = list(s.get("blocked") or [])
        glob = res.global_result(manifest=manifest, mission_id=(manifest or {}).get("mission_id"),
                                 planning_status="PLANNED" if proposal.get("status") == "PLANNED" else
                                 proposal.get("status", "BLOCKED"), vehicles=vresults, reasons=reasons,
                                 decisions_sha256=None, trace_sha256=self.tracer.summary()["trace_sha256"])
        pl.write_json(mdir / "results" / "global_result.json", glob)
        return {"global_": glob}

    def execute(self, mission_dir: Path | str, *, mode: str, executor: str, session_id: str | None,
                now: datetime | None = None, double: ex.OfflineTestDouble | None = None,
                approvals: dict | None = None, receipt_key: bytes | None = None, vehicle_id: str | None = None) -> dict:
        """``executor``: "test-double" (OFFLINE_TEST) or "real" (prepares the protected requests; never submits)."""
        if executor not in ("test-double", "real"):
            raise ValueError(f"unknown executor {executor!r}")
        mission_dir = Path(mission_dir)
        self.tracer = Tracer(mission_id=mission_dir.name, data_kind="SYNTHETIC")
        final = self.execution_graph.invoke({"mission_dir": str(mission_dir), "mode": mode, "executor": executor,
                                             "session_id": session_id, "now": now or _now(),
                                             "double": double or ex.OfflineTestDouble(), "approvals": approvals,
                                             "receipt_key": receipt_key, "vehicle_id": vehicle_id},
                                            {"recursion_limit": 40})
        self.tracer.write(mission_dir / "trace" / f"execution_{_now().strftime('%Y%m%dT%H%M%SZ')}.jsonl")
        return final["global_"]

    def ingest_report(self, mission_dir: Path | str, *, vehicle_id: str, report_path: Path,
                      receipt_key: bytes | None = None) -> dict:
        """Bring a REAL protected-entry report back: bound to the approved mission bytes, else refused."""
        mission_dir = Path(mission_dir)
        manifest, problems = pl.check_manifest(mission_dir)
        if problems:
            raise ValueError(f"manifest problems: {problems}")
        v = appr.entry(manifest, vehicle_id)
        if v is None or v["role"] != "drone":
            raise ValueError("only drone preflight reports can be ingested (no rover plan executor exists)")
        state_path = mission_dir / "execution" / "state.json"
        prior = json.loads(state_path.read_bytes()) if state_path.exists() else {}
        obs = dict(prior.get("obs") or {})
        # a real report is accepted only for a vehicle whose request was prepared after the gate passed (approved,
        # in session, unchanged plan); otherwise evidence could be attached to a plan nobody approved
        before = (obs.get(vehicle_id) or {}).get("execution_status")
        gate = (prior.get("gates") or {}).get(vehicle_id) or {}
        if before != "READY_TO_REQUEST_EXECUTION" or gate.get("status") != "PASS":
            raise ValueError(f"REPORT_WITHOUT_GATED_REQUEST: {vehicle_id} is {before or 'NOT_EXECUTED'}; run "
                             "`execute --executor real` after approval first")
        o = ex.observe_preflight_report(report_path, vehicle_id=vehicle_id, task_id=v["task_id"],
                                        approved_mission_sha256=v["mission_json"]["sha256"],
                                        plan_sha256=v["plan"]["sha256"])
        if o["data_kind"] == "REJECTED_EVIDENCE":
            raise ValueError(o["failure_reason"])
        obs[vehicle_id] = o
        self.tracer = Tracer(mission_id=mission_dir.name, data_kind="REAL_SITL")
        events = list(prior.get("events") or []) + [{"vehicle_id": vehicle_id, "event": "REAL_REPORT_INGESTED",
                                                     "at": _iso(_now())}]
        return self._x_results({"mission_dir": str(mission_dir), "manifest": manifest, "obs": obs,
                                "gates": prior.get("gates") or {}, "events": events, "receipt_key": receipt_key,
                                "proposal": json.loads((mission_dir / "proposal.json").read_bytes()),
                                "prior": prior})["global_"]
