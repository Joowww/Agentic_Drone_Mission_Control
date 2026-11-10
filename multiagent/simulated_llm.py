"""SIMULATED model replies for the offline multi-agent demo and tests. NOT a model and NOT reasoning: each
responder is a fixed script that reads the prompt's TASK/HISTORY/FEEDBACK data and returns the next step. They
exist to exercise the loop, the tools, the gates, the revision request and the traces end to end. Every span
they produce carries data_kind SYNTHETIC and the model name "scripted:<name>".

Demo script (swarm_3_tight context, objectives POI_1 rgb, POI_4 rgb, POI_3 thermal; rover to POI_4):
- orchestrator: returns the brief /2 of the demo request;
- drone agent, round 1: asks for drone_capabilities, then proposes assignment A (drone_01: POI_4,
  drone_03: POI_1 + POI_3) WITHOUT checking separation;
- the orchestrator's gate finds A unresolvable (crossing routes, 20 s max delay) and requests a revision;
- drone agent, round 2: checks assignment B with check_separation, sees CLEAR, proposes B;
- rover agent: validates POI_4, checks the dependency on the aerial proposal, proposes the waiting task.
"""
from __future__ import annotations

import json

DEMO_TEXT = ("Inspect the field: photograph POI_1 and POI_4 and take thermal images of POI_3. "
             "Once POI_4 has been inspected, send rover_01 to POI_4.")
A = {"drone_01": ["A2"], "drone_03": ["A1", "A3"]}
B = {"drone_01": ["A1"], "drone_03": ["A3", "A2"]}


def _section(prompt: str, name: str):
    for line in prompt.splitlines():
        if line.startswith(f"{name} (data): "):
            return json.loads(line.split(": ", 1)[1])
    return None


def orchestrator(prompt: str) -> str:
    return json.dumps({
        "schema": "tfg.multiagent.mission-brief/2",
        "aerial_objectives": [{"objective_id": "A1", "point_id": "POI_1", "required_sensor": "rgb"},
                              {"objective_id": "A2", "point_id": "POI_4", "required_sensor": "rgb"},
                              {"objective_id": "A3", "point_id": "POI_3", "required_sensor": "thermal"}],
        "ground_objectives": [{"objective_id": "G1", "point_id": "POI_4", "after_aerial": True}],
        "rover": "rover_01"})


def drone(prompt: str) -> str:
    history, feedback = _section(prompt, "HISTORY") or [], _section(prompt, "FEEDBACK") or []
    if any("REVISION_REQUESTED" in f for f in feedback):
        if not history:
            return json.dumps({"action": "tool", "tool": "check_separation", "arguments": {"assignments": B},
                               "reason": "the gate reported a separation conflict; try routes that do not cross"})
        return json.dumps({"action": "final", "proposal": {"assignments": B},
                           "explanation": "drone_03 takes POI_3 and POI_4 next to its pad; drone_01 keeps POI_1",
                           "evidence": [history[-1]["tool_call"]]})
    if not history:
        return json.dumps({"action": "tool", "tool": "drone_capabilities", "arguments": {},
                           "reason": "read sensors and eligibility"})
    return json.dumps({"action": "final", "proposal": {"assignments": A},
                       "explanation": "first proposal, separation not checked", "evidence": [history[-1]["tool_call"]]})


def rover(prompt: str) -> str:
    history, task = _section(prompt, "HISTORY") or [], _section(prompt, "TASK") or {}
    if not history:
        return json.dumps({"action": "tool", "tool": "validate_ground_target", "arguments": {"target_point": "POI_4"}})
    if len(history) == 1:
        return json.dumps({"action": "tool", "tool": "check_dependency",
                           "arguments": {"point": "POI_4", "aerial_points": task.get("aerial_points_proposed", [])}})
    return json.dumps({"action": "final", "proposal": {
        "tasks": [{"objective_id": "G1", "target_point": "POI_4", "after_aerial_point": "POI_4"}],
        "insufficient_information": []}, "explanation": "POI_4 is reachable and a drone task reaches it first",
        "evidence": [h["tool_call"] for h in history]})


RESPONDERS = {"demo_orchestrator": orchestrator, "demo_drone": drone, "demo_rover": rover}


# --------------------------------------------------------------- harness doubles (tests only) --
def gold_orchestrator(cases: list[dict]):
    """Returns the case's gold brief: exercises the multi-agent benchmark wiring. NOT a model."""
    def respond(prompt: str) -> str:
        text = prompt.rsplit("Request: ", 1)[1]
        case = next(c for c in cases if c["text"] == text)
        gold = dict(case["gold_brief"])
        for key in ("unsafe_requests", "contradictions", "ambiguities"):
            if gold.get(key):
                gold[key] = ["(harness double)"]
        return json.dumps(gold)
    return respond


def reference_drone(prompt: str) -> str:
    """Asks the deterministic reference and proposes it. NOT a model."""
    history = _section(prompt, "HISTORY") or []
    if not history:
        return json.dumps({"action": "tool", "tool": "reference_allocation", "arguments": {}})
    assignment = history[-1]["data"].get("assignment") or {}
    return json.dumps({"action": "final", "proposal": {"assignments": assignment}, "explanation": "reference",
                       "evidence": [history[-1]["tool_call"]]})


def echo_rover(prompt: str) -> str:
    """Restates the ground objectives as tasks. NOT a model."""
    task = _section(prompt, "TASK") or {}
    tasks = [{"objective_id": o["objective_id"], "target_point": o["point_id"],
              "after_aerial_point": o["point_id"] if o.get("after_aerial") else None}
             for o in task.get("ground_objectives", [])]
    return json.dumps({"action": "final", "proposal": {"tasks": tasks, "insufficient_information": []},
                       "explanation": "restated", "evidence": []})


# ------------------------------------------------- single-shot doubles (integrated offline mission) --
INTEGRATED_TEXT = ("Inspect POI_1 with the RGB camera and take multispectral images of POI_3. If a drone camera reports a red "
                   "or yellow card, send rover_01 to the point it indicates once that observation has been validated.")


def integrated_orchestrator(prompt: str) -> str:
    """Brief /2 of an integrated request, read from the request text with FIXED patterns (a scripted double, not a
    model): "Inspect POI_n with the RGB camera", "<sensor> images of POI_n", and a rover sent "to the point it
    indicates" (a ground objective whose point is not known yet)."""
    import re
    text = prompt.rsplit("Request: ", 1)[-1]
    found = [(m.start(), m.group(1), "rgb") for m in re.finditer(r"Inspect (POI_\d+) with the RGB camera", text)]
    found += [(m.start(), m.group(2), m.group(1)) for m in re.finditer(r"(multispectral|thermal) images of (POI_\d+)", text)]
    aerial = [{"objective_id": f"A{i}", "point_id": point, "required_sensor": sensor}
              for i, (_, point, sensor) in enumerate(sorted(found), 1)]
    ground = [{"objective_id": "G1", "point_id": None, "after_aerial": True,
               "description": "point indicated by a validated card observation"}] if "point it indicates" in text else []
    return json.dumps({"schema": "tfg.multiagent.mission-brief/2", "aerial_objectives": aerial,
                       "ground_objectives": ground, "rover": "rover_01" if ground else None})


def single_shot_drone(prompt: str) -> str:
    """Assigns each objective to its last eligible drone (from the runtime CONTEXT) and asks for checks. NOT a model."""
    caps = _section(prompt, "CONTEXT")[0]["data"]
    assign = {}
    for o in caps["objectives"]:
        if o["eligible_drones"]:
            assign.setdefault(o["eligible_drones"][-1], []).append(o["objective_id"])
    points = {o["objective_id"]: o["point_id"] for o in caps["objectives"]}
    verify = [{"tool": "validate_route", "arguments": {"vehicle_id": v, "sequence": [points[i] for i in ids]}}
              for v, ids in assign.items()]
    verify += [{"tool": "check_separation", "arguments": {"assignments": assign}}] if len(assign) > 1 else []
    return json.dumps({"proposal": {"assignments": assign}, "verify": verify, "explanation": "eligible drones"})


def single_shot_rover(prompt: str) -> str:
    """Restates declared ground objectives the rover can take, lists what is missing. NOT a model."""
    caps, task = _section(prompt, "CONTEXT")[0]["data"], _section(prompt, "TASK")
    tasks, missing = [], []
    available = caps.get("available", caps.get("declared_available"))
    declared = caps.get("declared_pois") or (caps.get("planning") or {}).get("targets_allowed", [])
    conditional = [{"objective_id": o["objective_id"], "waits_for": "VALIDATED_OBSERVATION"}
                   for o in task.get("awaiting_observation") or []]
    for o in task["ground_objectives"]:
        wait = o["point_id"] if o.get("after_aerial") else None
        if not available:
            missing.append(f"{caps.get('rover')} unavailable")
        elif o.get("point_id") not in declared:
            missing.append(f"{o['objective_id']}: no declared target point")
        elif wait and wait not in caps["aerial_points_proposed"]:
            missing.append(f"no drone task reaches {wait}")
        else:
            tasks.append({"objective_id": o["objective_id"], "target_point": o["point_id"], "after_aerial_point": wait})
    verify = [{"tool": "validate_ground_target", "arguments": {"target_point": t["target_point"]}} for t in tasks]
    verify += [{"tool": "check_dependency", "arguments": {"point": t["after_aerial_point"],
                                                          "aerial_points": caps["aerial_points_proposed"]}}
               for t in tasks if t["after_aerial_point"]]
    proposal = {"tasks": tasks, "insufficient_information": missing}
    if conditional:
        proposal["conditional_tasks"] = conditional
    return json.dumps({"proposal": proposal, "verify": verify, "explanation": "declared targets only"})


RESPONDERS.update({"integrated_orchestrator": integrated_orchestrator, "single_shot_drone": single_shot_drone,
                   "single_shot_rover": single_shot_rover})


def single_shot_rover_v3(prompt: str) -> str:
    """Contract /3 double: one typed decision per objective from the CONTEXT facts. NOT a model."""
    caps = _section(prompt, "CONTEXT")[0]["data"]
    decisions = []
    for o in caps.get("objectives", []):
        oid = o["objective_id"]
        if o.get("target_from_future_observation"):
            decisions.append({"objective_id": oid, "decision": "WAIT_FOR_OBSERVATION", "target_point": None, "reason": None})
        elif not caps.get("declared_available"):
            decisions.append({"objective_id": oid, "decision": "CANNOT_PLAN", "target_point": None, "reason": "ROVER_UNAVAILABLE"})
        elif o.get("waits_for_drone") and not o.get("wait_point_reached_by_proposed_drone_task"):
            decisions.append({"objective_id": oid, "decision": "CANNOT_PLAN", "target_point": None,
                              "reason": "NO_DRONE_TASK_REACHES_WAIT_POINT"})
        elif not o.get("point_is_declared_poi"):
            decisions.append({"objective_id": oid, "decision": "CANNOT_PLAN", "target_point": None, "reason": "TARGET_NOT_DECLARED"})
        else:
            decisions.append({"objective_id": oid, "decision": "PLAN_TO_DECLARED_POI", "target_point": o["point_id"],
                              "reason": None})
    verify = [{"tool": "validate_ground_target", "arguments": {"target_point": d["target_point"]}}
              for d in decisions if d["decision"] == "PLAN_TO_DECLARED_POI"]
    return json.dumps({"proposal": {"decisions": decisions}, "verify": verify, "explanation": "facts of the context"})


RESPONDERS["single_shot_rover_v3"] = single_shot_rover_v3


def integrated_orchestrator_v4(prompt: str) -> str:
    """Provenance brief (interpret_brief/4) of an integrated request, from the same FIXED patterns as
    integrated_orchestrator, quoting the operator's words. States nothing about vehicles. A scripted double."""
    import re
    text = prompt.rsplit("Request: ", 1)[-1]
    sentences = [s.strip() for s in re.split(r"(?<=\.)\s+", text) if s.strip()]
    found = [(m.start(), m.group(1), "rgb", m.group(0)) for m in re.finditer(r"Inspect (POI_\d+) with the RGB camera", text)]
    found += [(m.start(), m.group(2), m.group(1), m.group(0))
              for m in re.finditer(r"(multispectral|thermal) images of (POI_\d+)", text)]
    aerial = [{"objective_id": f"A{i}", "point_id": point, "required_sensor": sensor, "description": quote,
               "quote": quote} for i, (_, point, sensor, quote) in enumerate(sorted(found), 1)]
    cond = next((s for s in sentences if "point it indicates" in s), None)
    rover = re.search(r"\b(rover_\d+)\b", cond or "")
    ground = [{"objective_id": "G1", "point_id": None, "vehicle_id": rover.group(1) if rover else None,
               "after_aerial": True, "waits_for": "VALIDATED_OBSERVATION",
               "description": "point indicated by a validated card observation", "quote": cond.rstrip(".")}] if cond else []
    return json.dumps({"schema": "tfg.multiagent.mission-brief-provenance/1", "aerial_objectives": aerial,
                       "ground_objectives": ground, "stated": [],
                       "to_look_up": ["vehicle_availability", "battery_percent", "drone_capabilities"] +
                                     (["rover_localization"] if ground else []),
                       "unsafe_requests": [], "contradictions": [], "ambiguities": []})


RESPONDERS["integrated_orchestrator_v4"] = integrated_orchestrator_v4
