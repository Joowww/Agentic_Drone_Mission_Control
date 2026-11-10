"""Mission Orchestrator Agent (LangGraph): request -> brief -> tasks -> specialised agents -> global proposal.

Graph: interpret -> screen -> decompose -> drone_agent -> rover_agent -> assemble -> finalize.
- interpret: an interpreter (rules or model) produces a MissionBrief;
- screen: the orchestrator's OWN unsafe-phrase check on the raw text (independent of the interpreter) and the
  brief's contradictions; an unsafe request ends here as REFUSED_UNSAFE with no task;
- decompose: aerial objectives to the Drone/Swarm Agent, ground objectives to the Rover Agent;
- assemble: the global plan as the EXISTING scenario template (models.scenario_template) with dependencies
  (the rover waits for the drone that reaches its point: POI_REACHED), checked by the existing
  coordination_checks and the pairwise route separation;
- finalize: the overall status. The orchestrator NEVER authorizes: ``authorization.granted`` is always False and
  every task is PENDING_AUTHORIZATION, to be handed to the existing entries and their gates.
"""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from models.fleet import Fleet
from models.scenario_template import ScenarioTemplate
from models.site import Site
from planning.artifact_store import fingerprint
from planning.scenario_instance import coordination_checks
from planning.site_validation import route_separation

from multiagent import availability, risk_signals
from multiagent.contracts import PROPOSAL_SCHEMA, MissionBrief, OperatingContext, parse_brief
from multiagent.drone_agent import plan_aerial
from multiagent.interpreters import BriefRejected, unsafe_phrases
from multiagent.model_interpretation import InterpretationBlocked
from multiagent.rover_agent import plan_ground
from multiagent.tracing import Tracer

AGENT = "mission_orchestrator"


def stated_fact_problems(text: str, brief: dict) -> list[str]:
    """Numeric facts the deterministic rules read in the text (wind, battery, altitude) that the brief omits or
    changes. A model that drops "battery at 20 %" would otherwise get a plan the checks cannot question."""
    from multiagent.interpreters import RulesInterpreter
    stated, _ = RulesInterpreter().interpret(text)
    problems = []
    for key in ("wind_speed_kmh", "altitude_m"):
        value = getattr(stated, key)
        if value is not None and (brief.get(key) is None or abs(brief[key] - value) > 1e-6):
            problems.append(f"BRIEF_DISAGREES_WITH_STATED_FACT: {key} stated {value}, brief {brief.get(key)}")
    for vehicle, value in stated.battery_percent.items():
        got = (brief.get("battery_percent") or {}).get(vehicle)
        if got is None or abs(got - value) > 1e-6:
            problems.append(f"BRIEF_DISAGREES_WITH_STATED_FACT: battery of {vehicle} stated {value}%, brief {got}")
    return problems


class OrchestratorState(TypedDict, total=False):
    text: str
    mission_id: str
    brief: dict | None
    interpreter: dict
    stop: str | None  # terminal status decided early
    reasons: list[str]
    air: dict
    ground: dict
    template: dict | None
    coordination: dict | None
    joint_spatial: list
    safety: dict  # v2: risk signals and availability report
    proposal: dict


def _swarm_summary(air: dict) -> dict | None:
    coordination = ((air or {}).get("evidence") or {}).get("coordination")
    if coordination is None:
        return None
    return {"status": coordination["status"], "initial_conflicts": len(coordination["initial_conflicts"]),
            "residual_conflicts": len(coordination["residual_conflicts"]),
            "schedule": coordination.get("schedule"), "makespan_s": coordination.get("makespan_s"),
            "replanned": air["evidence"].get("replanned_for_coordination"),
            "attempts": len(air["evidence"].get("coordination_attempts") or []),
            "scope": "planning-time check over declared inputs; not a physical separation guarantee"}


class MissionOrchestrator:
    def __init__(self, context: OperatingContext, interpreter, *, allocator=None, tracer: Tracer | None = None,
                 pipeline: str = "v1", rover_reviewer=None, safety_policy: str = "safety/2"):
        """``pipeline`` v1: the behaviour every sealed result was produced with. v2: brief /2 (availability),
        safety policy safety/2 (risk signals kept across invalid replies) and the interpretation report."""
        if pipeline not in ("v1", "v2"):
            raise ValueError(f"unknown pipeline {pipeline!r}")
        self.context, self.interpreter, self.allocator, self.pipeline = context, interpreter, allocator, pipeline
        self.rover_reviewer = rover_reviewer  # optional LLM rover agent (llm_agents.rover_reviewer); advisory only
        if safety_policy not in ("safety/2", "safety/3", "safety/4"):
            raise ValueError(f"unknown safety policy {safety_policy!r}")
        self.safety_policy = safety_policy  # safety/3 (supervisor_policy) only with pipeline v2, opt-in
        self.planning_context = context
        self.site = Site.model_validate_json(Path(context.resolve(context.site_path)).read_text(encoding="utf-8"))
        self.fleet = Fleet.model_validate_json(Path(context.resolve(context.fleet_path)).read_text(encoding="utf-8"))
        self.tracer = tracer
        self.artifacts: dict = {}
        graph = StateGraph(OrchestratorState)
        for name in ("interpret", "screen", "decompose", "drone_agent", "rover_agent", "assemble", "finalize"):
            graph.add_node(name, getattr(self, "_" + name))
        graph.add_edge(START, "interpret")
        graph.add_edge("interpret", "screen")
        graph.add_conditional_edges("screen", lambda s: "finalize" if s.get("stop") else "decompose")
        graph.add_edge("decompose", "drone_agent")
        graph.add_edge("drone_agent", "rover_agent")
        graph.add_edge("rover_agent", "assemble")
        graph.add_edge("assemble", "finalize")
        graph.add_edge("finalize", END)
        self.graph = graph.compile()

    # ------------------------------------------------------------------ nodes --
    def _interpret(self, state):
        with self.tracer.span(AGENT, "llm" if self.interpreter.info.get("data_kind") != "DETERMINISTIC" else "tool",
                              "interpret", model=self.interpreter.info, inputs={"text": state["text"]}) as span:
            try:
                brief, meta = self.interpreter.interpret(state["text"])
            except InterpretationBlocked as exc:
                self.tracer.output(span, {"blocked": exc.args[0]}, status="ERROR_INFRASTRUCTURE", model_call=exc.args[1])
                return {"brief": None, "interpreter": exc.args[1], "stop": "BLOCKED_INFRASTRUCTURE_ERROR",
                        "reasons": [exc.args[0]]}
            except BriefRejected as exc:
                self.tracer.output(span, {"rejected": exc.args[0]}, status="REJECTED", model_call=exc.args[1])
                return {"brief": None, "interpreter": exc.args[1], "stop": "NEEDS_CLARIFICATION",
                        "reasons": [f"BRIEF_REJECTED: {exc.args[0]}"]}
            except ValidationError as exc:
                self.tracer.output(span, {"rejected": str(exc)[:300]}, status="REJECTED")
                return {"brief": None, "interpreter": dict(self.interpreter.info), "stop": "NEEDS_CLARIFICATION",
                        "reasons": ["BRIEF_REJECTED: invalid brief"]}
            dumped = brief.model_dump(mode="json", by_alias=True)
            self.tracer.output(span, dumped, model_call=meta)
        return {"brief": dumped, "interpreter": meta}

    def _screen(self, state):
        if self.pipeline == "v2":
            return self._screen_v2(state)
        brief = state.get("brief")
        # The orchestrator's own screen of the RAW text applies even when the interpreter missed it or failed.
        unsafe = sorted(set(unsafe_phrases(state["text"])) | set((brief or {}).get("unsafe_requests") or []))
        self.tracer.validation(AGENT, "unsafe_request_screen", "FAIL" if unsafe else "PASS", unsafe)
        if unsafe:
            return {"stop": "REFUSED_UNSAFE", "reasons": [f"UNSAFE_REQUEST: {u}" for u in unsafe]}
        if state.get("stop"):
            return {}
        self.tracer.validation(AGENT, "contradictions", "FAIL" if brief["contradictions"] else "PASS",
                               brief["contradictions"])
        if brief["contradictions"]:
            return {"stop": "NEEDS_CLARIFICATION", "reasons": [f"CONTRADICTION: {c}" for c in brief["contradictions"]]}
        omitted = stated_fact_problems(state["text"], brief)
        self.tracer.validation(AGENT, "stated_facts_cross_check", "FAIL" if omitted else "PASS", omitted)
        if omitted:
            return {"stop": "NEEDS_CLARIFICATION", "reasons": omitted}
        if not brief["aerial_objectives"] and not brief["ground_objectives"]:
            return {"stop": "NEEDS_CLARIFICATION", "reasons": ["NO_OBJECTIVES: the request names nothing to do"]}
        if brief.get("site_id") not in (None, self.site.site_id):
            return {"stop": "NEEDS_CLARIFICATION", "reasons": [f"OTHER_SITE: {brief['site_id']} is not {self.site.site_id}"]}
        return {}

    def _screen_v2(self, state):
        """safety/2: every signal is kept with its source; the decision is deterministic and can only refuse."""
        brief, meta = state.get("brief"), state.get("interpreter") or {}
        signals = risk_signals.text_signals(state["text"], self.site)
        model_flags = (brief or {}).get("unsafe_requests") if brief is not None else meta.get("model_risk_flags") or []
        signals += [{"source": "MODEL_FLAG", "kind": "MODEL_FLAGGED_UNSAFE", "evidence": str(f)[:160],
                     "reply_valid": brief is not None} for f in model_flags or []]
        unsafe = [s for s in signals if s["source"] in ("DETERMINISTIC_TEXT", "MODEL_FLAG")]
        report = {"risk_signals": signals}
        reclassified = None
        if self.safety_policy in ("safety/3", "safety/4"):
            from multiagent import supervisor_policy
            if self.safety_policy == "safety/4":  # independent operator-text screen; only adds refusals
                extra = supervisor_policy.operator_text_signals(state["text"])
                signals = extra + signals
                report["risk_signals"] = signals
            text_only = [s for s in signals if s["source"] == "DETERMINISTIC_TEXT"]
            reclassified = supervisor_policy.classify(state["text"], brief, model_flags or [], text_only)
            report["classification"] = reclassified
            unsafe = text_only + [s for s, c in zip([x for x in signals if x["source"] == "MODEL_FLAG"],
                                                    reclassified["flags"]) if c["category"] == "UNSAFE_REQUEST"]
            self.tracer.validation(AGENT, f"supervisor_policy:{self.safety_policy}", "FAIL" if unsafe else "PASS", reclassified)
        self.tracer.validation(AGENT, f"risk_signals:{self.safety_policy}", "FAIL" if unsafe else "PASS", signals)
        if unsafe:
            reasons = [f"UNSAFE_REQUEST ({s['source']}:{s['kind']}): {s['evidence']}" for s in unsafe]
            if state.get("stop"):
                reasons += list(state.get("reasons") or [])  # e.g. the invalid reply, kept as a second reason
            return {"stop": "REFUSED_UNSAFE", "reasons": reasons, "safety": report}
        if state.get("stop"):
            return {"safety": report}
        problems = [f"CONTRADICTION: {c}" for c in brief["contradictions"]]
        if reclassified:
            problems += [f"INSUFFICIENT_INFORMATION (model flag reclassified by safety/3): {e}"
                         for e in reclassified["insufficient_information"]]
        problems += [f"AMBIGUITY: {a}" for a in brief.get("ambiguities") or []]
        problems += stated_fact_problems(state["text"], brief)
        if not brief["aerial_objectives"] and not brief["ground_objectives"]:
            problems.append("NO_OBJECTIVES: the request names nothing to do")
        stated = risk_signals.stated_availability(state["text"])
        avail = availability.resolve(brief, self.context, self.fleet, stated)
        report["availability"] = avail
        problems += avail["clarifications"]
        self.tracer.validation(AGENT, "availability", "FAIL" if avail["clarifications"] else "PASS", avail)
        if problems:
            return {"stop": "NEEDS_CLARIFICATION", "reasons": problems, "safety": report}
        self.planning_context = availability.apply(self.context, avail)
        return {"safety": report}

    def _decompose(self, state):
        brief = state["brief"]
        self.tracer.validation(AGENT, "decomposition", "PASS", {
            "aerial": [o["objective_id"] for o in brief["aerial_objectives"]],
            "ground": [o["objective_id"] for o in brief["ground_objectives"]]})
        return {}

    def _drone_agent(self, state):
        brief = parse_brief(state["brief"])
        wind = brief.wind_speed_kmh if brief.wind_speed_kmh is not None else self.context.wind_speed_kmh
        with self.tracer.span("drone_swarm_agent", "agent", "plan_aerial",
                              inputs={"objectives": state["brief"]["aerial_objectives"], "wind_speed_kmh": wind}) as span:
            result, artifacts = plan_aerial(brief.aerial_objectives, context=self.planning_context, site=self.site,
                                            fleet=self.fleet, wind_speed_kmh=wind, battery_percent=brief.battery_percent,
                                            altitude_m=brief.altitude_m, requested_drones=brief.drones,
                                            tracer=self.tracer, allocator=self.allocator)
            dumped = result.dump()
            self.tracer.output(span, {k: dumped[k] for k in ("status", "incompatible", "clarifications")} |
                               {"proposals": [{k: p[k] for k in ("vehicle_id", "poi_sequence", "mission_sha256")}
                                              for p in dumped["proposals"]]})
        self.artifacts.update(artifacts)
        return {"air": dumped}

    def _rover_agent(self, state):
        brief = parse_brief(state["brief"])
        with self.tracer.span("rover_agent", "agent", "plan_ground",
                              inputs={"objectives": state["brief"]["ground_objectives"], "rover": brief.rover}) as span:
            result = plan_ground(brief.ground_objectives, context=self.planning_context, site=self.site, fleet=self.fleet,
                                 rover_id=brief.rover, tracer=self.tracer)
            dumped = result.dump()
            if self.rover_reviewer is not None and brief.ground_objectives:
                dumped = self._rover_review(dumped, brief, state)
            self.tracer.output(span, {k: dumped[k] for k in ("status", "proposals", "incompatible", "clarifications")})
        return {"ground": dumped}

    def _rover_review(self, dumped, brief, state):
        """LLM rover agent: its proposal is compared with the deterministic one, which keeps the last word. It can
        only make the outcome more conservative (missing information becomes a clarification)."""
        aerial = sorted({p for a in (state.get("air") or {}).get("proposals", []) for p in a["poi_sequence"]})
        review = self.rover_reviewer(brief.ground_objectives, site=self.site, context=self.planning_context,
                                     fleet=self.fleet, rover_id=brief.rover, aerial_points=aerial)
        v3 = review.get("contract") == "v3"
        # v3: the typed decisions, normalized by rover_gate (wait point derived); None when the gate rejected them
        proposal = (review.get("normalized_proposal") or {}) if v3 else (review.get("proposal") or {})
        deterministic = {(t["objective_ids"][0], t["target_point"], t["after_aerial_point"]) for t in dumped["proposals"]}
        proposed = {(t.get("objective_id"), t.get("target_point"), t.get("after_aerial_point"))
                    for t in proposal.get("tasks") or [] if isinstance(t, dict)}
        if review["status"] != "FINAL":
            agreement = "AGENT_FAILED"
        elif v3 and review.get("normalized_proposal") is None:
            agreement = "REJECTED_BY_ROVER_GATE_DETERMINISTIC_KEPT"
        else:
            agreement = "AGREES" if proposed == deterministic else "DISAGREES_DETERMINISTIC_KEPT"
        self.tracer.validation(AGENT, "gate:rover_proposal", agreement,
                               {"deterministic": sorted(map(list, deterministic)), "proposed": sorted(map(list, proposed))})
        missing = [str(m)[:200] for m in proposal.get("insufficient_information") or []] if review["status"] == "FINAL" else []
        if v3:  # a typed CANNOT_PLAN the deterministic side does not record itself becomes a clarification
            known = {i["objective_id"] for i in dumped["incompatible"]}
            missing += [f"{x['objective_id']}: {x['reason']}" for x in proposal.get("infeasible") or []
                        if x["objective_id"] not in known and x["reason"] != "NO_DRONE_TASK_REACHES_WAIT_POINT"]
        evidence = {**dumped["evidence"], "llm_review": {**review, "agreement": agreement}}
        clarifications = dumped["clarifications"] + [f"ROVER_AGENT_REPORTS_MISSING: {m}" for m in missing]
        return {**dumped, "evidence": evidence, "clarifications": clarifications}

    def _assemble(self, state):
        air, ground = state["air"]["proposals"], list(state["ground"]["proposals"])
        dependencies, blocked = [], []
        aerial_ids = [p["task_id"] for p in air]
        for task in list(ground):
            point = task["after_aerial_point"]
            if point is None:
                continue
            visitor = next((p for p in air if point in p["poi_sequence"]), None)
            if visitor is None:
                ground.remove(task)
                blocked.append({"objective_id": task["objective_ids"][0], "reasons": [
                    f"DEPENDENCY_UNSATISFIED: no drone task reaches {point}, so the rover cannot wait for it"]})
            else:
                dependencies.append({"task_id": task["task_id"], "after": visitor["task_id"], "condition": "POI_REACHED",
                                     "point": point})
        for task in ground:
            for aerial in aerial_ids:  # sequential order of the existing coordinator: the rover goes last
                if not any(d["task_id"] == task["task_id"] and d["after"] == aerial for d in dependencies):
                    dependencies.append({"task_id": task["task_id"], "after": aerial, "condition": "COMPLETED"})
        drones = [d for d in self.context.drones if d.vehicle_id in {p["vehicle_id"] for p in air}] or self.context.drones
        template = {
            "schema": "tfg.scenario-template/1", "template_id": f"multiagent_{state['mission_id'][:12]}", "version": 1,
            "description": "global proposal of the Mission Orchestrator (multi-agent prototype)",
            "provenance": "SYNTHETIC: multiagent prototype over a synthetic operating context",
            "planning_margin_m": self.context.planning_margin_m,
            "mission_defaults": {
                "cruise_speed_kmh": min(d.cruise_speed_kmh for d in drones),
                "battery_percent": min(d.battery_percent for d in drones),
                "battery_consumption_percent_per_minute": max(d.consumption_percent_per_minute for d in drones),
                "wind_speed_kmh": state["air"]["evidence"].get("wind_speed_kmh", self.context.wind_speed_kmh),
                "wind_direction_from_deg": 0.0,
                "minimum_battery_reserve_percent": self.context.minimum_battery_reserve_percent,
                "maximum_wind_speed_kmh": min(d.max_wind_kmh for d in drones),
                "maximum_altitude_m": self.site.vertical_limits.max_altitude_m or 120.0,
                "failsafe": {"low_battery_action": "RETURN_TO_HOME", "unsafe_wind_action": "RETURN_TO_HOME",
                             "communication_loss_action": "RETURN_TO_HOME"},
                "source": "conservative envelope of the declared drone profiles; each individual mission carries its "
                          "own drone's profile"},
            "aerial_tasks": [{"task_id": p["task_id"], "vehicle_id": p["vehicle_id"], "takeoff_point": p["takeoff_point"],
                              "poi_sequence": p["poi_sequence"],
                              "altitude_m": (state["brief"].get("altitude_m") or self.context.altitude_m),
                              "requested_speed_kmh": next((d.survey_speed_kmh for d in self.context.drones
                                                           if d.vehicle_id == p["vehicle_id"] and d.survey_speed_kmh),
                                                          self.context.requested_speed_kmh)} for p in air],
            "ground_tasks": [{"task_id": t["task_id"], "vehicle_id": t["vehicle_id"], "start_point": t["start_point"],
                              "target_point": t["target_point"]} for t in ground],
            "dependencies": dependencies,
            "execution_order": [*aerial_ids, *[t["task_id"] for t in ground]]}
        if not air and not ground:
            # the proposals list must be the FILTERED one: a rover task whose dependency cannot be met is dropped
            return {"template": None, "coordination": None, "joint_spatial": [], "ground": {**state["ground"],
                    "proposals": ground, "incompatible": state["ground"]["incompatible"] + blocked}}
        model = ScenarioTemplate.model_validate(template)
        coordination = coordination_checks(model, self.fleet)
        joint = route_separation({p["task_id"]: p["route_local"] for p in air})
        self.tracer.validation(AGENT, "coordination_checks", coordination["status"], coordination["errors"])
        self.tracer.validation(AGENT, "joint_spatial", "INFO", joint)
        ground_result = {**state["ground"], "proposals": ground,
                         "incompatible": state["ground"]["incompatible"] + blocked}
        return {"template": template, "coordination": coordination, "joint_spatial": joint, "ground": ground_result}

    def _finalize(self, state):
        air, ground = state.get("air") or {}, state.get("ground") or {}
        reasons = list(state.get("reasons") or [])
        proposals = [*(air.get("proposals") or []), *(ground.get("proposals") or [])]
        incompatible = [*(air.get("incompatible") or []), *(ground.get("incompatible") or [])]
        clarifications = [*(air.get("clarifications") or []), *(ground.get("clarifications") or [])]
        coordination = state.get("coordination")
        if state.get("stop"):
            status, proposals = state["stop"], []
        elif coordination is not None and coordination["status"] != "PASS":
            status = "INFEASIBLE"
            reasons += [f"COORDINATION: {e}" for e in coordination["errors"]]
        elif clarifications:
            status = "NEEDS_CLARIFICATION"
        elif not proposals:
            status = "INFEASIBLE"
        elif air.get("status") == "COORDINATION_PENDING":
            status = "COORDINATION_PENDING"
            reasons.append("COORDINATION_PENDING: several drones planned but no declared separation policy; "
                           "independent plans are not a coordinated swarm")
        elif incompatible:
            status = "PARTIAL_PENDING_AUTHORIZATION"
        else:
            status = "PROPOSED_PENDING_AUTHORIZATION"
        reasons += clarifications
        reasons += [f"INCOMPATIBLE {i['objective_id']}: {r}" for i in incompatible for r in i["reasons"]]
        proposal = {
            "schema": PROPOSAL_SCHEMA, "mission_id": state["mission_id"], "status": status, "reasons": reasons,
            "data_kind": "SYNTHETIC" if self.interpreter.info.get("data_kind") in ("SYNTHETIC", "DETERMINISTIC")
            else "MODEL_OUTPUT_OVER_SYNTHETIC_CONTEXT",
            "context": {"context_id": self.context.context_id, "site": f"{self.site.site_id} v{self.site.version}",
                        "fleet": f"{self.fleet.fleet_id} v{self.fleet.version}", "provenance": self.context.provenance},
            "interpreter": state.get("interpreter"), "brief": state.get("brief"),
            "aerial": air or None, "ground": ground or None,
            "tasks": [{"task_id": p["task_id"], "vehicle_id": p["vehicle_id"], "state": "PENDING_AUTHORIZATION"}
                      for p in proposals],
            "template": state.get("template"), "coordination": coordination, "joint_spatial": state.get("joint_spatial"),
            "swarm_coordination": _swarm_summary(air),
            "authorization": {"required": True, "granted": False, "by": None,
                              "how": "each task separately through the existing entries and gates"},
            "movement_authorized": False, "commands_sent": 0, "vehicles_contacted": 0}
        if self.pipeline == "v2":
            proposal["pipeline"] = "v2"
            proposal["interpretation"] = self._interpretation_report(state, status, reasons)
        proposal["proposal_sha256"] = fingerprint({k: v for k, v in proposal.items() if k != "interpreter"})
        return {"proposal": proposal}

    def _interpretation_report(self, state, status, reasons):
        import hashlib
        meta, safety = state.get("interpreter") or {}, state.get("safety") or {}
        raw = meta.get("raw_text")
        return {"operator_text": state["text"],
                "operator_text_sha256": hashlib.sha256(state["text"].encode()).hexdigest(),
                "model_reply_sha256": meta.get("raw_sha256") or (hashlib.sha256(raw.encode()).hexdigest() if raw else None),
                "json_valid": meta.get("json_valid"), "contract_valid": meta.get("contract_valid",
                                                                                  state.get("brief") is not None),
                "parse_error": meta.get("parse_error"), "risk_signals": safety.get("risk_signals", []),
                "availability": safety.get("availability"),
                "safety_decision": {"policy": risk_signals.POLICY_ID, "decided_by": "deterministic orchestrator policy",
                                    "decision": "REFUSE" if status == "REFUSED_UNSAFE" else "NO_UNSAFE_SIGNAL",
                                    "authority_granted": False},
                "final_status": status, "final_reason": reasons[0] if reasons else None}

    # ------------------------------------------------------------------ entry --
    def run(self, text: str) -> dict:
        mission_id = "M-" + fingerprint({"text": text, "context": self.context.context_id})[:16]
        if self.tracer is None:
            kind = "SYNTHETIC" if self.interpreter.info.get("data_kind") in ("SYNTHETIC", "DETERMINISTIC") else "MODEL_OUTPUT"
            self.tracer = Tracer(mission_id=mission_id, data_kind=kind)
        self.tracer.mission_id = mission_id
        self.planning_context = self.context  # availability of a previous run never carries over
        started = time.perf_counter()
        with self.tracer.span(AGENT, "agent", "mission", model=self.interpreter.info, inputs={"text": text}) as span:
            final = self.graph.invoke({"text": text, "mission_id": mission_id})
            proposal = final["proposal"]
            self.tracer.output(span, {"status": proposal["status"], "tasks": proposal["tasks"],
                                      "proposal_sha256": proposal["proposal_sha256"]}, status="OK")
        proposal["elapsed_s"] = time.perf_counter() - started
        return proposal


def proposal_json(proposal: dict) -> str:
    return json.dumps(proposal, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n"
