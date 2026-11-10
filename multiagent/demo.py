"""Reproducible OFFLINE demo of the three agents (no model, no vehicle, no network, no simulator).

    python -m multiagent.demo                      # prints the summary only, writes nothing
    python -m multiagent.demo --out DIR            # also writes the artifacts below into DIR (must be empty/new)

Agricultural request -> Mission Orchestrator -> Drone/Swarm Agent (two drones with different sensors) ->
Rover Agent (ground task after a drone reaches the point) -> global validation -> PENDING AUTHORIZATION.

Artifacts: proposal.json, template.json (existing scenario-template contract), plans/<drone>.plan with
plans/<drone>.verification.json (existing strict exporter and verifier), missions/<drone>.json,
trace.jsonl (local structured trace) and opik_payload.dry_run.json (NOT sent). Everything is SYNTHETIC:
synthetic site, declared drone profiles, deterministic rules interpreter. There is no perception: the drones
"inspect" declared points; no image is produced or analysed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from inputs.qgc_plan_export import verify_plan
from planning.scenario_instance import mission_bytes

from multiagent.contracts import load_context
from multiagent.interpreters import RulesInterpreter
from multiagent.orchestrator import MissionOrchestrator, proposal_json
from multiagent.tracing import Tracer, opik_dry_run

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = Path(__file__).with_name("fixtures") / "orchard_two_drones_v2.context.json"
SWARM_CONTEXT = Path(__file__).with_name("fixtures") / "swarm_3_tight.context.json"
SWARM_REQUEST = ("Swarm inspection of the field: photograph POI_1, take thermal images of POI_3, take multispectral "
                 "images of POI_9 and inspect POI_4. Once POI_4 has been inspected, send rover_01 to POI_4.")
REQUEST = ("Agricultural inspection of the orchard: photograph POI_1 and POI_2 with the RGB camera, "
           "take multispectral images of POI_3 and POI_4. Wind is 8 km/h. "
           "Once POI_3 has been inspected, send rover_01 to POI_3 to collect a soil sample.")


MULTIAGENT_CONFIG = Path(__file__).with_name("fixtures") / "agents_simulated_demo.json"


def run_demo(out: Path | None = None, *, text: str = REQUEST, context_path: Path = CONTEXT, agents_config=None) -> dict:
    """``agents_config``: an agents-config file (llm_agents.MultiAgentConfig); its simulated responders come from
    multiagent.simulated_llm. Without it, the deterministic demo runs exactly as before."""
    context = load_context(context_path)
    tracer = Tracer(mission_id="pending", data_kind="SYNTHETIC")
    if agents_config is None:
        orchestrator = MissionOrchestrator(context, RulesInterpreter(), tracer=tracer)
    else:
        from multiagent.llm_agents import build_orchestrator, load_config
        from multiagent.simulated_llm import RESPONDERS
        config = load_config(agents_config)
        if config.data_kind != "SIMULATED_MODELS":
            raise SystemExit("the demo only runs simulated models; real models go through the experiment runners")
        orchestrator = build_orchestrator(context, config, tracer=tracer, simulated=RESPONDERS)
    proposal = orchestrator.run(text)
    verifications = {}
    if out is not None:
        out = Path(out)
        if out.exists() and any(out.iterdir()):
            raise SystemExit(f"{out} is not empty; choose a new directory")
        (out / "plans").mkdir(parents=True, exist_ok=True)
        (out / "missions").mkdir(exist_ok=True)
        amsl = orchestrator.site.vertical_reference.origin_ground_amsl_m
        for vehicle_id, content in sorted(orchestrator.artifacts.get("plans", {}).items()):
            mission = orchestrator.artifacts["missions"][vehicle_id]
            (out / "missions" / f"{vehicle_id}.json").write_bytes(mission_bytes(mission))
            plan_path = out / "plans" / f"{vehicle_id}.plan"
            plan_path.write_bytes(content)
            verifications[vehicle_id] = verify_plan(plan_path, mission, planned_home_amsl_m=amsl)
            (out / "plans" / f"{vehicle_id}.verification.json").write_text(
                json.dumps(verifications[vehicle_id], indent=2, sort_keys=True) + "\n", encoding="utf-8")
        proposal["plan_verification"] = {v: r["status"] for v, r in verifications.items()}
        (out / "proposal.json").write_text(proposal_json(proposal), encoding="utf-8")
        if proposal.get("template"):
            (out / "template.json").write_text(json.dumps(proposal["template"], indent=2) + "\n", encoding="utf-8")
        tracer.write(out / "trace.jsonl")
        (out / "opik_payload.dry_run.json").write_text(
            json.dumps(opik_dry_run(tracer.records), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    from multiagent.llm_agents import agent_metrics
    return {"proposal": proposal, "verifications": verifications, "trace": tracer.summary(),
            "agent_metrics": agent_metrics(tracer.records), "records": tracer.records}


def summary_lines(result: dict) -> list[str]:
    p = result["proposal"]
    lines = [f"Mission {p['mission_id']}  status {p['status']}  (data: {p['data_kind']})", ""]
    air = (p.get("aerial") or {})
    for task in air.get("proposals", []):
        lines.append(f"  {task['task_id']:<20} {task['vehicle_id']}: {' -> '.join(task['poi_sequence'])}  "
                     f"{task['length_m']} m, {task['flight_minutes']} min, mission {task['deterministic_validation']['mission_status']}, "
                     f".plan {task['export']['status']}")
    chosen = ((air.get("evidence") or {}).get("reference") or {}).get("chosen")
    if chosen:
        lines.append(f"  reference allocation before coordination: {chosen['assignment']}  makespan {chosen['makespan_min']:.3f} min  "
                     f"({air['evidence']['reference']['assignments_evaluated']} assignments evaluated)")
    for task in (p.get("ground") or {}).get("proposals", []):
        lines.append(f"  {task['task_id']:<20} {task['vehicle_id']}: {task['start_point']} -> {task['target_point']}"
                     f" after {task['after_aerial_point']} is reached; ROS 2 commands sent: {task['ros2_commands_sent']}")
    if p.get("template"):
        lines.append(f"  dependencies: {[(d['task_id'], d['condition'], d['after']) for d in p['template']['dependencies']]}")
        lines.append(f"  coordination checks: {p['coordination']['status']}; joint spatial: "
                     f"{[(j['pair'], j['min_horizontal_distance_m']) for j in p['joint_spatial']]}")
    swarm = p.get("swarm_coordination")
    if swarm:
        lines.append(f"  swarm coordination: {swarm['status']}; conflicts initial {swarm['initial_conflicts']}, residual "
                     f"{swarm['residual_conflicts']}; replanned: {swarm['replanned']}; start delays: "
                     f"{ {v: s.get('start_delay_s') for v, s in (swarm['schedule'] or {}).items()} }")
        for attempt in (p.get("aerial") or {}).get("evidence", {}).get("coordination_attempts", []):
            lines.append(f"    attempt {attempt['candidate']}: {attempt['assignment']} -> {attempt['status']}"
                         f" ({attempt['initial_conflicts']} conflicts){'; ' + attempt['reason'] if attempt['reason'] else ''}")
        conflicts = ((p.get("aerial") or {}).get("evidence", {}).get("coordination") or {}).get("initial_conflicts", [])
        first = next((a for a in (p.get("aerial") or {}).get("evidence", {}).get("coordination_attempts", [])
                      if a["status"] == "UNRESOLVED"), None)
        if conflicts[:1]:
            c = conflicts[0]
            lines.append(f"    e.g. {c['vehicles']} {c['segments']}: {c['min_distance_m']} m < {c['required_m']} m "
                         f"during {c['time_overlap_s']} s")
    for reason in p["reasons"]:
        lines.append(f"  reason: {reason}")
    if result["verifications"]:
        lines.append(f"  .plan verification: {p.get('plan_verification')}")
    lines += ["", f"  authorization granted: {p['authorization']['granted']}; movement authorized: "
                  f"{p['movement_authorized']}; commands sent: {p['commands_sent']}",
              f"  trace: {result['trace']['spans']} spans {result['trace']['by_kind']}; Opik: DRY RUN, nothing sent"]
    steps = [r for r in result.get("records", []) if r["kind"] in ("llm", "tool") or
             r["name"].startswith(("gate:", "revision_request:"))]
    if any(r["kind"] == "llm" and r["agent"] != "mission_orchestrator" for r in steps):
        lines += ["", "  agent steps (SIMULATED models: scripted test doubles, not model reasoning):"]
        for r in steps:
            lines.append(f"    {r['agent']:<22} {r['kind']:<10} {r['name']:<40} {r['status']}")
        for role, m in result["agent_metrics"].items():
            lines.append(f"  {role}: llm calls real {m['llm_calls_real']} / test double {m['llm_calls_test_double']}, "
                         f"tool calls {m['tool_calls']}" + (f", revisions requested {m['revision_requests']}, gates "
                                                            f"rejected {m['gates_rejected']} / accepted {m['gates_accepted']}"
                                                            if "revision_requests" in m else ""))
    return lines


def _rover_handoff(result: dict, snapshot: Path | None, *, reviewed: bool = False) -> None:
    """Prints the hand-off of this run's request through the rover's real code (TEST_FIXTURE limits and authorization:
    they connect software; no human approved anything). Nothing is executed."""
    from multiagent import integration_battery, rover_handoff as rh
    if not result.get("execution_request") or (result.get("observation_gate") or {}).get("status") != "ACCEPTED":
        sys.stdout.write("[rover]       no execution request in this run: nothing to hand off\n")
        return
    with rh.rover_contract(snapshot, reviewed=reviewed) as rover_side:
        _, trace = integration_battery.handoff_for(result, rover_side, conversion_owner="MULTIAGENT_FRAMES2D")
        _, final = integration_battery.handoff_for(result, rover_side, conversion_owner="ROVER_ADAPTER")
        local_tag = getattr(rover_side, "tag", None) if snapshot is None else None
    label = (f"this repository, {local_tag}, imported in-process" if snapshot is None
             else f"{rh.REVIEWED['commit']} + protected review patch {rh.REVIEWED['patch_sha256'][:12]}, immutable snapshot"
             if reviewed else f"{rh.ROVER_CONTRACT_COMMIT}, immutable snapshot")
    sys.stdout.write(f"[rover]       REAL_CONTRACT_CODE: the rover's own validators and executor admission ({label}); "
                     "TEST_FIXTURE limits/authorization/transform/localization\n")
    sys.stdout.write("[rover]       OFFLINE TEST PATH (conversion owner MULTIAGENT_FRAMES2D; refused in OPERATIONAL mode):\n")
    for st in trace["stages"]:
        sys.stdout.write(f"[rover]         {st['stage']:<17} {st['status']:<12} {st['reasons'][:2]}\n")
    stages = {s["stage"]: s for s in trace["stages"]}
    conv = stages["frames"].get("conversion") or {}
    if conv.get("to"):
        sys.stdout.write(f"[rover]       frames: {conv['from']['frame']} ({conv['from']['x_m']}, {conv['from']['y_m']}) -> "
                         f"{conv['to']['frame']} ({conv['to']['x_m']:.3f}, {conv['to']['y_m']:.3f}) +-{conv['to']['sigma_m']:.2f} m, "
                         f"converted once by {conv['converted_by']} (TEST_FIXTURE transform)\n")
    env = trace.get("envelope") or {}
    if env:
        payload = env["rover_side"]["v2_payload"]
        sys.stdout.write(f"[rover]       payload v2: plan {payload.get('plan_sha256', '')[:12]}, scope "
                         f"{env['scope']['rover_scope_sha256'][:12] if env['scope']['rover_scope_sha256'] else None}, "
                         f"rover decision {env['rover_side']['v2_decision']}, schema errors "
                         f"{len(stages['rover_v2'].get('schema_errors') or [])}\n")
        sys.stdout.write(f"[rover]       submission envelope {env['schema']}: {env['status']} (not a command)\n")
    sys.stdout.write(f"[rover]       DRY_RUN_EXECUTOR: {stages['dry_run']['status']} {stages['dry_run']['reasons'][:1]}\n")
    sys.stdout.write(f"[rover]       {trace['classification']}; commands {len(trace['commands'])}; movement executed "
                     f"{trace['movement_executed']}\n")
    rec = ((final.get("envelope") or {}).get("goal_handoff")) or {}
    fs = {s["stage"]: s for s in final["stages"]}
    sys.stdout.write("[rover]       FINAL CONTRACT (conversion owner ROVER_ADAPTER, decided 07/11):\n")
    if rec:
        g = rec["goal_site"]
        sys.stdout.write(f"[rover]         goal kept in {g['frame']} ({g['x_m']}, {g['y_m']}) +-{g['sigma_m']} m; transform "
                         f"{rec['transform_required']['status']}; conversions applied here "
                         f"{len(rec['applied_conversions'])}; delegated {rec['delegated_checks']}\n")
    sys.stdout.write(f"[rover]         executor_request {fs['executor_request']['status']} "
                     f"{fs['executor_request']['reasons'][-1:]}\n")
    sys.stdout.write(f"[rover]         {final['classification']}; commands {len(final['commands'])}\n")


def _plan_input(plan: Path, manifest: Path | None) -> int:
    """Steps 1-6 from a QGroundControl .plan: Hermes' importer -> semantics manifest -> mission-input/1 -> the SAME
    supervisor, Drone Agent and validators. STRUCTURED_INPUT: no model is called. A .plan cannot carry the
    conditional rover task: that is reported, not invented."""
    import hashlib
    from models.qgc_import import QGroundControlImportContext
    from multiagent import integrated_mission as im, mission_inputs as mi, plan_semantics as ps
    from multiagent.orchestrator import MissionOrchestrator
    from multiagent.tracing import Tracer
    w = sys.stdout.write
    ctx = im.load_context(im.CONTEXT)
    site, _ = im._site_fleet(ctx)
    ic = QGroundControlImportContext(battery_percent=90, battery_consumption_percent_per_minute=1.0, wind_speed_kmh=0,
                                     wind_direction_from_deg=0, minimum_battery_reserve_percent=20,
                                     maximum_wind_speed_kmh=30, maximum_altitude_m=50)
    w("[plan]  mode          STRUCTURED_INPUT: a QGroundControl .plan; no model is called (import context is "
      "TEST_FIXTURE, not an operator statement)\n")
    w(f"[plan]  1 input       {plan} sha256 {hashlib.sha256(Path(plan).read_bytes()).hexdigest()[:12]} (Hermes importer)\n")
    r = ps.import_with_manifest(plan, manifest, site=site, context=ctx, import_context=ic)
    sem = r.get("semantics") or {}
    w(f"[plan]  2 semantics   {sem.get('status')} {sem.get('problems') or ''}\n")
    w(f"[plan]    mission-input/1 {r['status']}; findings {[f['kind'] for f in r['findings']]}\n")
    for o in (r.get("brief") or {}).get("aerial_objectives", []):
        w(f"[plan]    objective {o['objective_id']} at {o['coordinates']} sensor {o['required_sensor']} ({o['description']})\n")
    if r["status"] == "REJECTED":
        w("[plan]  REJECTED: nothing is planned\n")
        return 1
    p = MissionOrchestrator(ctx, mi.StructuredInterpreter(r), tracer=Tracer(mission_id="plan-input"), pipeline="v2",
                            safety_policy="safety/4").run("structured mission input")
    w(f"[plan]  3 supervisor  {p['status']} (safety/4); reasons {p.get('reasons', [])[:2]}\n")
    for t in (p.get("aerial") or {}).get("proposals", []):
        w(f"[plan]  4 drone_agent {t['vehicle_id']} -> {t['poi_sequence']}\n")
    w(f"[plan]  5 validation  commands sent {p['commands_sent']}\n")
    w("[plan]  6 ground      NOT REPRESENTABLE in a .plan: the conditional rover task ('if a card is seen, send "
      "rover_01') must come from the operator (natural-language path: --scenario red_target)\n")
    return 0 if p["status"] in ("PROPOSED_PENDING_AUTHORIZATION", "PARTIAL_PENDING_AUTHORIZATION",
                                "NEEDS_CLARIFICATION") else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline three-agent demo")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--text")
    parser.add_argument("--swarm", action="store_true",
                        help="three drones under a tight separation policy: conflict -> replanning -> rover task")
    parser.add_argument("--multiagent-simulated", action="store_true",
                        help="the three agents in LLM mode with SIMULATED models: tools, gate, revision, rover review")
    parser.add_argument("--scenario", help="integrated precision-agriculture demo scenario (multiagent.precision_demo)")
    parser.add_argument("--list-scenarios", action="store_true")
    parser.add_argument("--all-scenarios", action="store_true", help="run every scenario, one summary line each")
    parser.add_argument("--replay", type=Path, metavar="RESULTS_DIR",
                        help="replay a SEALED pilot's recorded events (no model call, nothing recomputed)")
    parser.add_argument("--rover-snapshot", type=Path, metavar="DIR",
                        help="also hand the scenario's request to the rover's REAL contract and executor code (immutable "
                             "snapshot of the pinned commit, created in DIR if absent); TEST_FIXTURE limits/authorization; "
                             "with --battery: run the offline integration battery")
    parser.add_argument("--battery", action="store_true",
                        help="the 18-mission integration battery against this repository's rover code (or, with "
                             "--rover-snapshot, against a historical pinned revision)")
    parser.add_argument("--rover-handoff", action="store_true",
                        help="with --scenario/--two-drones: hand the request to this repository's rover contract, adapter "
                             "and executor admission (in-process; TEST_FIXTURE limits/authorization; zero commands)")
    parser.add_argument("--rover-reviewed", action="store_true",
                        help="with --rover-snapshot: the rover's committed contract plus its protected review patch (applied "
                             "only inside the snapshot) instead of the committed contract alone")
    parser.add_argument("--two-drones", action="store_true",
                        help="end-to-end offline demo: two drones planned, Hermes-validated, prepared for the H2 SITL "
                             "path, synthetic camera observation, Rover Agent, the rover v2 hand-off; zero commands")
    parser.add_argument("--replay-plan", action="store_true",
                        help="with --two-drones: use the sealed M4c-r1 plan (recorded REAL_LOCAL_LLM, no new call)")
    parser.add_argument("--input-plan", type=Path, metavar="PLAN",
                        help="enter the mission as a QGroundControl .plan (Hermes importer) instead of natural language")
    parser.add_argument("--plan-manifest", type=Path, metavar="JSON",
                        help="with --input-plan: the semantics manifest bound to that .plan (multiagent.plan_semantics)")
    parser.add_argument("--safety-policy", choices=("safety/3", "safety/4"), default="safety/3",
                        help="supervisor safety policy for --scenario/--all-scenarios (safety/4 adds the operator-text screen)")
    args = parser.parse_args(argv)
    if args.two_drones:
        from multiagent import two_drone_demo
        if args.out is not None and args.out.exists():
            parser.error(f"--out {args.out} already exists: evidence is never overwritten")
        r = two_drone_demo.run(replay_plan=args.replay_plan, rover_snapshot=args.rover_snapshot,
                               reviewed=args.rover_reviewed, out=args.out, rover_local=args.rover_handoff)
        return 0 if r.get("status") == "COMPLETED_OFFLINE" and r.get("commands") == 0 else 1
    if args.input_plan is not None:
        return _plan_input(args.input_plan, args.plan_manifest)
    if args.replay is not None:
        from multiagent import replay
        return 0 if replay.replay(args.replay)["status"] == "REPLAYED" else 1
    if args.battery:
        from multiagent import integration_battery
        if args.rover_snapshot is None:
            if args.rover_reviewed:
                parser.error("--rover-reviewed applies only to a historical --rover-snapshot")
            return integration_battery.main([])
        return integration_battery.main(["--snapshot", str(args.rover_snapshot)] + (["--reviewed"] if args.rover_reviewed else []))
    if args.list_scenarios or args.scenario or args.all_scenarios:
        from multiagent import precision_demo
        if (args.scenario or args.all_scenarios) and args.out is not None and args.out.exists():
            parser.error(f"--out {args.out} already exists: evidence is never overwritten; choose a new directory")
        if args.list_scenarios:
            for name, spec in precision_demo.SCENARIOS.items():
                sys.stdout.write(f"{name:24s} {spec['what']}  -> expected {spec['expect']}\n")
            return 0
        if args.all_scenarios:
            bad = 0
            for name in precision_demo.SCENARIOS:
                r = precision_demo.run_scenario(name, quiet=True, out=(args.out / name) if args.out else None,
                                                safety_policy=args.safety_policy)
                bad += not r["as_expected"]
                sys.stdout.write(f"{'OK ' if r['as_expected'] else 'BAD'} {name:24s} {r['classification']} "
                                 f"(commands {r['commands_sent']})\n")
            return 1 if bad else 0
        if args.scenario not in precision_demo.SCENARIOS:
            parser.error(f"unknown scenario {args.scenario!r}; see --list-scenarios")
        r = precision_demo.run_scenario(args.scenario, out=args.out, safety_policy=args.safety_policy)
        if args.rover_snapshot is not None or args.rover_handoff:
            _rover_handoff(r, args.rover_snapshot, reviewed=args.rover_reviewed)
        return 0 if r["as_expected"] else 1
    if args.multiagent_simulated:
        from multiagent.simulated_llm import DEMO_TEXT
        result = run_demo(args.out, text=args.text or DEMO_TEXT, context_path=SWARM_CONTEXT,
                          agents_config=MULTIAGENT_CONFIG)
    elif args.swarm:
        result = run_demo(args.out, text=args.text or SWARM_REQUEST, context_path=SWARM_CONTEXT)
    else:
        result = run_demo(args.out, text=args.text or REQUEST)
    sys.stdout.write("\n".join(summary_lines(result)) + "\n")
    return 0 if result["proposal"]["status"] in ("PROPOSED_PENDING_AUTHORIZATION",
                                                  "PARTIAL_PENDING_AUTHORIZATION") else 1


if __name__ == "__main__":
    raise SystemExit(main())
