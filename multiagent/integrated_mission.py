"""First integrated multi-agent mission, OFFLINE: supervisor -> drone/swarm agent -> observation -> rover agent ->
dependencies and validators -> one proposal PENDING AUTHORIZATION. No ROS, Gazebo, hardware or command.

    python -m multiagent.integrated_mission --simulated --out <new dir>

Flow (each step a span in one trace per phase):
 Phase A (mission_orchestrator, drone_swarm_agent): the operator text is interpreted; the aerial objectives are
   delegated and planned; a ground objective whose point is not known yet ("the point a validated observation
   indicates") is held by the supervisor as AWAITING_OBSERVATION and not planned.
 Observation: one observation (tfg.multiagent.observation/1) goes through multiagent.perception's gate. In this
   offline run it is a TEST FIXTURE (labelled so in the observation, its pose and every output); no camera ran.
 Phase B (all three roles): the supervisor updates its brief with the validated target (a deterministic,
   labelled update: the ground objective now names the matched declared POI and waits for the drone that reaches
   it); the drone agent plans again; the rover agent plans to the target; the supervisor checks dependencies and
   coordination and returns the proposal, PENDING AUTHORIZATION.
A refused observation stops phase B: the ground task stays AWAITING_OBSERVATION and nothing is invented.

The agents use whatever the configuration says (scripted test doubles here; ollama/aida/hermes candidates through
llm_agents when allowed). The simulated run is never a model result.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys

from multiagent import perception, simulated_llm
from multiagent.contracts import BRIEF_SCHEMA_V2, load_context, parse_brief
from multiagent.llm_agents import MultiAgentConfig, build_orchestrator
from multiagent.tracing import Tracer, opik_dry_run

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "multiagent/fixtures/orchard_two_drones_v2.context.json"
CAMERAS = {"drone_01": ["cam_down_fixture"], "drone_02": ["cam_down_fixture"]}  # fixture declaration
SIMULATED = MultiAgentConfig.model_validate({
    "schema": "tfg.multiagent.agents-config/1", "config_id": "integrated-simulated", "data_kind": "SIMULATED_MODELS",
    "mission_orchestrator": {"mode": "llm", "candidate": "scripted:integrated_orchestrator"},
    "drone_swarm_agent": {"mode": "llm", "candidate": "scripted:single_shot_drone", "step_contract": "single_shot",
                          "max_llm_calls": 1, "max_revisions": 0},
    "rover_agent": {"mode": "llm", "candidate": "scripted:single_shot_rover", "step_contract": "single_shot",
                    "prompt_id": "agent_rover_single/2", "max_llm_calls": 1, "max_revisions": 0}})


class SupervisorUpdate:
    """The supervisor's deterministic brief update after a validated observation. Labelled; never a model."""
    info = {"provider": "deterministic", "model": "supervisor-brief-update/1", "version": "1", "data_kind": "DETERMINISTIC"}

    def __init__(self, brief: dict):
        self.brief = brief

    def interpret(self, text):
        return parse_brief(self.brief), dict(self.info, latency_s=0.0)


def _site_fleet(context):
    from models.fleet import Fleet
    from models.site import Site
    site = Site.model_validate_json(Path(context.resolve(context.site_path)).read_text(encoding="utf-8"))
    fleet = Fleet.model_validate_json(Path(context.resolve(context.fleet_path)).read_text(encoding="utf-8"))
    return site, fleet


def fixture_timeline(observation: dict, now, *, drone_task="AIR_drone_02", point="POI_3") -> list[dict]:
    """TEST FIXTURE events (no camera or vehicle reported anything): the drone keeps reporting, its camera's
    observation arrives, then it reports the point reached."""
    from datetime import timedelta
    t0 = now - timedelta(seconds=3)
    return [{"type": "HEARTBEAT", "task_id": drone_task, "source": "TEST_FIXTURE", "at": t0},
            {"type": "OBSERVATION", "observation": observation, "source": "TEST_FIXTURE", "at": now},
            {"type": "AERIAL_POINT_REACHED", "task_id": drone_task, "point": point, "source": "TEST_FIXTURE",
             "at": now + timedelta(seconds=2)}]


def plan_phase_a(config: MultiAgentConfig = SIMULATED, *, text: str = simulated_llm.INTEGRATED_TEXT, simulated=None,
                 allow_model_calls=False, safety_policy: str = "safety/2", adapter_wrapper=None) -> dict:
    """Supervisor interpretation + aerial planning; ground objectives without a point are held as conditional tasks
    (and planned as a wait by the Rover Agent when it is in llm mode)."""
    context = load_context(CONTEXT)
    site, fleet = _site_fleet(context)
    simulated = simulated if simulated is not None else simulated_llm.RESPONDERS
    data_kind = "SYNTHETIC" if config.data_kind != "REAL_MODELS" else "MODEL_OUTPUT"
    tracer = Tracer(mission_id="pending", data_kind=data_kind)
    orch = build_orchestrator(context, config, tracer=tracer, simulated=simulated, allow_model_calls=allow_model_calls,
                              safety_policy=safety_policy, adapter_wrapper=adapter_wrapper)
    holder = {}
    interpreter = orch.interpreter

    class HoldGround:  # phase A plans the aerial part; ground objectives without a point wait for an observation
        info = interpreter.info

        def interpret(self, t):
            brief, meta = interpreter.interpret(t)
            dumped = brief.model_dump(by_alias=True)
            pending = [g for g in dumped["ground_objectives"] if not g.get("point_id") and not g.get("coordinates")]
            dumped["ground_objectives"] = [g for g in dumped["ground_objectives"] if g not in pending]
            holder.update(original=brief.model_dump(by_alias=True), pending=pending)
            return parse_brief(dumped), meta
    orch.interpreter = HoldGround()
    proposal = orch.run(text)
    pending = holder.get("pending", [])
    aerial_tasks = [p["task_id"] for p in (proposal.get("aerial") or {}).get("proposals", [])]
    aerial_points = sorted({pt for p in (proposal.get("aerial") or {}).get("proposals", []) for pt in p["poi_sequence"]})
    rover_id = (holder.get("original") or {}).get("rover")
    phase_a = {"proposal": proposal, "brief_from_interpreter": holder.get("original"),
               # the supervisor's own (deterministic) record of the conditional ground work
               "pending_ground": [{**g, "state": "AWAITING_OBSERVATION"} for g in pending],
               "conditional_ground_tasks": [{"objective_id": g["objective_id"], "vehicle_id": rover_id,
                                             "state": "CONDITIONAL_AWAITING_OBSERVATION", "target_point": None,
                                             "waits_for": "VALIDATED_OBSERVATION", "after_tasks": aerial_tasks,
                                             "executable": False} for g in pending]}
    planned = proposal["status"] in ("PROPOSED_PENDING_AUTHORIZATION", "PARTIAL_PENDING_AUTHORIZATION")
    if pending and planned and config.rover_agent.mode == "llm":  # plans the wait without inventing a target; never
        # after the supervisor refused or asked for clarification (found in pilot M4: a wasted, meaningless call)
        from multiagent.llm_agents import make_adapter, rover_reviewer
        adapter = make_adapter(config.rover_agent, simulated=simulated, allow_model_calls=allow_model_calls)
        if adapter_wrapper is not None:
            adapter = adapter_wrapper("rover_agent", adapter)
        review = rover_reviewer(config.rover_agent, adapter, tracer=tracer)
        phase_a["rover_conditional_review"] = review([], site=site, context=context, fleet=fleet, rover_id=rover_id,
                                                     aerial_points=aerial_points, awaiting=pending)
    return {"context": context, "site": site, "fleet": fleet, "phase_a": phase_a, "pending": pending, "tracer": tracer,
            "data_kind": data_kind, "simulated": simulated, "text": text}


def pinned_allocator(assignment: dict):
    """Phase B reuses the aerial allocation already accepted in phase A (no new model call). plan_aerial validates it
    again with the same deterministic checks; labelled PINNED_FROM_PHASE_A."""
    def allocator(problem):
        return {"assignments": assignment}, {"agent": "drone_swarm_agent", "source": "PINNED_FROM_PHASE_A",
                                             "accepted_by_gate": None, "llm_calls": 0, "rounds": []}
    return allocator


def plan_phase_b(config: MultiAgentConfig, bundle: dict, gate: dict, *, allow_model_calls=False,
                 safety_policy: str = "safety/2", pin_aerial: bool = False, adapter_wrapper=None) -> dict:
    """The supervisor's deterministic brief update with the validated target, then aerial and ground planning."""
    phase_a, pending = bundle["phase_a"], bundle["pending"]
    target = gate["target"]["matched_poi"]
    aerial_points = {o["point_id"] for o in (phase_a["brief_from_interpreter"] or {}).get("aerial_objectives", [])}
    updated = dict(phase_a["brief_from_interpreter"])
    updated["schema"] = BRIEF_SCHEMA_V2 if updated.get("schema") == BRIEF_SCHEMA_V2 else updated.get("schema")
    updated["ground_objectives"] = [{"objective_id": g["objective_id"], "point_id": target, "coordinates": None,
                                     "after_aerial": target in aerial_points,
                                     "description": f"target of observation {gate['observation_id']} "
                                                    f"({gate['target']['object_class']}, {gate['data_kind']})"}
                                    for g in pending]
    tracer = Tracer(mission_id="pending", data_kind=bundle["data_kind"])
    orch = build_orchestrator(bundle["context"], config, tracer=tracer, simulated=bundle["simulated"],
                              allow_model_calls=allow_model_calls, safety_policy=safety_policy,
                              adapter_wrapper=adapter_wrapper)
    orch.interpreter = SupervisorUpdate(updated)
    if pin_aerial:
        chosen = {p["vehicle_id"]: p["objective_ids"] for p in (phase_a["proposal"].get("aerial") or {}).get("proposals", [])}
        orch.allocator = pinned_allocator(chosen)
    tracer.validation("mission_orchestrator", "observation_gate", gate["status"],
                      {"observation_id": gate["observation_id"], "data_kind": gate["data_kind"],
                       "target": gate["target"], "failed": gate["reasons"]})
    proposal = orch.run(bundle["text"])
    from multiagent.execution_handoff import handoffs
    return {"brief": updated, "proposal": proposal, "tracer": tracer, "handoff_dry_run": handoffs(proposal, bundle["site"])}


def run(config: MultiAgentConfig = SIMULATED, *, text: str = simulated_llm.INTEGRATED_TEXT, observation=None,
        now=None, policy: perception.Policy | None = None, simulated=None, allow_model_calls=False,
        events: list[dict] | None = None, safety_policy: str = "safety/2") -> dict:
    now = now or perception.utc_now()
    bundle = plan_phase_a(config, text=text, simulated=simulated, allow_model_calls=allow_model_calls,
                          safety_policy=safety_policy)
    context, site, fleet, phase_a, pending = (bundle[k] for k in ("context", "site", "fleet", "phase_a", "pending"))
    proposal_a = phase_a["proposal"]
    if observation is None:
        observation = perception.fixture_observation(site=site, drone="drone_02", poi="POI_3", now=now)
    policy = policy or perception.Policy(allow_fixtures=True)
    gate = perception.ground_target_from_observation(observation, site=site, context=context, fleet=fleet, now=now,
                                                     policy=policy, camera_ids=CAMERAS)
    result = {"schema": "tfg.multiagent.integrated-mission/1", "text": text, "config_id": config.config_id,
              "data_kind": "SIMULATED_TEST_DOUBLES" if config.data_kind == "SIMULATED_MODELS" else config.data_kind,
              "phase_a": phase_a, "observation": observation, "observation_gate": gate,
              "traces": {"phase_a": bundle["tracer"].records}}
    if not pending:
        result.update(status="NO_GROUND_OBJECTIVE_AWAITING", final=proposal_a)
        return result
    from multiagent.mission_coordinator import Coordinator
    coordinator = Coordinator(proposal=proposal_a, conditional_tasks=phase_a["conditional_ground_tasks"], site=site,
                              context=context, fleet=fleet, cameras=CAMERAS, policy=policy)
    for event in (events if events is not None else fixture_timeline(observation, now)):
        coordinator.handle(event)
    result["coordination"] = {"log": coordinator.log, "summary": coordinator.summary()}
    states = {g["state"] for g in coordinator.states().values()}
    if gate["status"] == "ACCEPTED" and not states & {"TARGET_VALIDATED", "READY_FOR_AUTHORIZATION"}:
        result.update(status="GROUND_TASK_BLOCKED_" + "_".join(sorted(states)), final=proposal_a)
        return result
    if gate["status"] != "ACCEPTED" or proposal_a["status"] in ("REFUSED_UNSAFE", "NEEDS_CLARIFICATION"):
        result.update(status="GROUND_TASK_AWAITING_OBSERVATION" if gate["status"] != "ACCEPTED" else
                      f"STOPPED_AT_PHASE_A_{proposal_a['status']}", final=proposal_a)
        return result
    b = plan_phase_b(config, bundle, gate, allow_model_calls=allow_model_calls, safety_policy=safety_policy)
    result["phase_b"] = {"brief": b["brief"], "proposal": b["proposal"]}
    result["traces"]["phase_b"] = b["tracer"].records
    result.update(status=b["proposal"]["status"], final=b["proposal"], handoff_dry_run=b["handoff_dry_run"])
    return result


def write(result: dict, out: Path) -> dict:
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    out.mkdir(parents=True)
    traces = result.pop("traces")
    (out / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + "\n")
    for phase, records in traces.items():
        (out / f"trace_{phase}.jsonl").write_text("".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in records))
        dry = opik_dry_run(records, "tfg-multiagent-benchmarks", workspace="joowww", native_fields=True)
        (out / f"opik_{phase}.dry_run.json").write_text(json.dumps(dry, indent=1, sort_keys=True, default=str) + "\n")
    with (out / "SHA256SUMS").open("w") as sums:
        for path in sorted(p for p in out.iterdir() if p.name != "SHA256SUMS"):
            sums.write(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{path.name}\n")
    return {"status": result["status"], "out": str(out)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--simulated", action="store_true", help="scripted test doubles for the three agents (required)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if not a.simulated:
        raise SystemExit("only the simulated run is available from the CLI; real agents need a registered experiment")
    result = run()
    summary = write(result, a.out)
    final = result["final"]
    print(json.dumps({**summary, "tasks": final["tasks"], "dependencies": (final.get("template") or {}).get("dependencies"),
                      "observation_gate": result["observation_gate"]["status"],
                      "authorization": final["authorization"], "commands_sent": final["commands_sent"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
