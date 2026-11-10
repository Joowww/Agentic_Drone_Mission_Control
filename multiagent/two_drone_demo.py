"""End-to-end OFFLINE demo: a two-drone mission planned by the multi-agent system, validated by Hermes, prepared for
the historical ArduPilot SITL path, observed by a synthetic camera, and handed to the Rover Agent and to the rover's
protected executor contract. Zero commands; no simulator, no vehicle, no model call.

Every line is labelled:
  OFFLINE_DETERMINISTIC   scripted test doubles in the agent roles (no model)
  REPLAY                  the sealed M4c-r1 plan (its agents were REAL_LOCAL_LLM, recorded; nothing is called again)
  REAL_CODE               the repository's own validators, builders, gates, coordinator and the rover's contract code
  SYNTHETIC_SENSOR / TEST_FIXTURE   rendered image, declared virtual camera, fixture poses, events and statements
  DRY_RUN                 nothing is submitted: the executor calls are named, never made
  NOT_EXECUTED            what a real SITL run would do and this demo does not
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile

M4C_R1 = Path(__file__).parent / "benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9"
STATEMENT = "TEST_FIXTURE: offline demo statement; not an operator authorization"


class Console:
    def __init__(self, quiet):
        self.quiet, self.lines = quiet, []

    def __call__(self, n, label, text):
        line = f"[{n:>2}] {label:<22} {text}"
        self.lines.append(line)
        if not self.quiet:
            print(line, flush=True)


def run(*, replay_plan: bool = False, rover_snapshot: Path | None = None, reviewed: bool = False,
        out: Path | None = None, quiet: bool = False, now: datetime | None = None, rover_local: bool = False) -> dict:
    from multiagent import (camera_observation as co, drone_execution_bridge as db, drone_schedule as ds, geometry,
                            hermes_mission_adapter as ha, integrated_mission as im, precision_demo as pd,
                            rover_executor_bridge as rb, synthetic_scenes)
    from multiagent.mission_coordinator import Coordinator
    say = Console(quiet)
    now = now or datetime.now(timezone.utc)
    result = {"schema": "tfg.multiagent.two-drone-demo/1", "steps": {}, "commands": 0}
    # 1-2 ------------------------------------------------------------------------------------------- mission
    text = pd.INTEGRATED_TEXT
    say(1, "operator", f"mission (natural language): {text}")
    bundle = im.plan_phase_a(pd.CONFIG, text=text, safety_policy="safety/4")
    site, context, fleet = bundle["site"], bundle["context"], bundle["fleet"]
    pa = bundle["phase_a"]["proposal"]
    say(2, "supervisor", f"OFFLINE_DETERMINISTIC: {pa['status']} (safety/4); provenance "
        f"{((pa.get('interpreter') or {}).get('provenance') or {}).get('status')}")
    plan_source, proposal = {"kind": "LIVE", "agents": "OFFLINE_DETERMINISTIC (scripted test doubles)"}, pa
    if replay_plan:
        sealed = json.loads((M4C_R1 / "demo/phase_b_proposal.json").read_text())
        same = sorted((t["vehicle_id"], t["mission_sha256"]) for t in sealed["aerial"]["proposals"]) == \
            sorted((t["vehicle_id"], t["mission_sha256"]) for t in pa["aerial"]["proposals"])
        plan_source = {"kind": "REPLAY_OF_SEALED_RUN", "evidence": M4C_R1.name, "agents_recorded_as": "REAL_LOCAL_LLM",
                       "new_llm_calls": 0, "same_missions_as_scripted_plan": same}
        say(2, "supervisor", f"REPLAY: sealed M4c-r1 plan (recorded REAL_LOCAL_LLM, 0 new calls); identical missions "
            f"to the scripted plan: {same}")
        if not same:
            result.update(status="STOPPED_REPLAY_DIFFERS", plan_source=plan_source)
            return result
        proposal = sealed
    # 3-5 ------------------------------------------------------------------------------------- aerial plan
    for t in proposal["aerial"]["proposals"]:
        say(3, "drone_agent", f"{t['vehicle_id']} -> {t['poi_sequence']} ({t['objective_ids']}); route "
            f"{t['deterministic_validation']['mission_status']}")
    sc = proposal.get("swarm_coordination") or {}
    say(5, "separation", f"REAL_CODE: {sc.get('status')}, {sc.get('initial_conflicts')} initial conflicts, delays "
        f"{ {v: d['start_delay_s'] for v, d in (sc.get('schedule') or {}).items()} }")
    # 7-8 ------------------------------------------------------------------------- Hermes contract + checks
    adapted = ha.adapt_proposal(proposal, context=context, site=site, fleet=fleet, source=plan_source)
    deferred = []
    for d in adapted["drones"]:
        deferred.append((7, "hermes_adapter", f"REAL_CODE: {d['vehicle_id']} mission {d.get('mission_sha256', '')[:12]} rebuilt "
            f"{'identical' if d.get('mission_sha256') == d['recorded_mission_sha256'] else 'DIFFERENT'}; "
            f".plan {d.get('qgc_plan', {}).get('status')} {d.get('qgc_plan', {}).get('sha256', '')[:12]}; "
            f"SITL {(d.get('sitl_binding') or {}).get('simulated_vehicle')}"))
        deferred.append((8, "hermes_validation", f"REAL_CODE: {d['vehicle_id']} {d['hermes_validation']['mission_status']}/"
                         f"{d['hermes_validation']['execution_status']}"))
    deferred.append((8, "hermes_adapter", f"plan {adapted['status']}; findings {[f['kind'] for f in adapted['findings']]}"))
    result["steps"]["adapter"] = {"status": adapted["status"], "findings": adapted["findings"],
                                  "missions": {d["vehicle_id"]: d.get("mission_sha256") for d in adapted["drones"]}}
    if adapted["status"] != "PLANNING_VALID":
        for line in deferred:
            say(*line)
        result.update(status="STOPPED_PLAN_NOT_VALID")
        return result
    # 6 -------------------------------------------------------------------------------------------- agenda
    plans = ds.plans_from_adapter(adapted)
    policy = context.separation_policy
    rep = ds.reproduce_deconfliction(plans, policy)
    launch = Path(__file__).resolve().parents[1] / "simulation/ros2_gazebo/launch/tfg_demo_2drones.launch.py"
    sitl = ds.sitl_effective_deconfliction(plans, ds.launch_spawn_positions(launch), policy)
    say(6, "agenda", f"REAL_CODE: reproduced {rep['status']} {len(rep['initial_conflicts'])} conflicts, delays "
        f"{ {v: s['start_delay_s'] for v, s in rep['schedule'].items()} }; on the SITL spawn geometry "
        f"{sitl['status']} {({v: s['start_delay_s'] for v, s in sitl.get('schedule', {}).items()})}")
    result["steps"]["agenda"] = {"reproduced": rep["schedule"], "sitl_effective": sitl.get("schedule"),
                                 "sitl_status": sitl["status"]}
    for line in deferred:
        say(*line)
    # 9 ------------------------------------------------------------------------------------ execution request
    with tempfile.TemporaryDirectory() as tmp:
        mdir = (Path(out) / "missions") if out else Path(tmp) / "missions"
        req = db.request_execution(adapted, mission_dir=mdir, request_key=f"two-drone-demo-{now:%Y%m%dT%H%M%S}",
                                   authorization_statement=STATEMENT)
    say(9, "h2_request", f"REAL_CODE + DRY_RUN: {req['status']} via {req.get('execution_path', {}).get('realization')} "
        f"(order {[m['vehicle_id'] for m in req.get('missions', [])]}); would call "
        f"{(req.get('would_call') or {}).get('function')}; submitted {req['submitted']}")
    result["steps"]["execution_request"] = {k: req.get(k) for k in ("status", "execution_path", "submitted",
                                                                     "admission_check", "problems")}
    # 10 ------------------------------------------------------- synthetic producer: schedule + arrival events
    class Clock:
        t = now

        def __call__(self):
            return self.t
    clock = Clock()
    sched = ds.DroneScheduler(plans, policy, clock=clock, mode="SEQUENTIAL_H2")
    first = min(plans, key=lambda v: (plans[v].start_delay_s, v))
    second = next(v for v in plans if v != first)

    def fx_event(kind, vid, dt, **kw):
        clock.t = now + timedelta(seconds=dt)
        return sched.handle({"type": kind, "vehicle_id": vid, "source": "TEST_FIXTURE", "at": clock.t, **kw})
    for v in plans:
        fx_event("READINESS", v, 0.0, ready=True)
    decision = sched.decide()
    say(10, "schedule", f"TEST_FIXTURE events, SEQUENTIAL_H2: {first} {decision[first]['decision']}, {second} "
        f"{decision[second]['decision']} {decision[second]['reasons'][:1]}")
    p = plans[first]
    segs = ds.dc.timeline(first, p.route_local, p.labels, p.leg_minutes, policy, 0.0)
    arrival = next(s for s in segs if s.kind == "leg").t1
    fx_event("AIRBORNE", first, 0.0)
    for t in range(1, int(arrival) + 1):
        fx_event("TELEMETRY", first, float(t))
    fx_event("WAYPOINT_REACHED", first, arrival, index=1)
    say(10, "schedule", f"TEST_FIXTURE: {first} reaches {p.labels[1]} at {arrival:.1f} s (nominal)")
    # coordinator: the same objects the precision demo uses
    a = bundle["phase_a"]
    coord = Coordinator(proposal=pa, conditional_tasks=a["conditional_ground_tasks"], site=site, context=context,
                        fleet=fleet, cameras=im.CAMERAS, policy=pd.POLICY, created_at=now, detection_deadline_s=300)
    cev = lambda kind, dt, **kw: coord.handle({"type": kind, "source": "TEST_FIXTURE",  # noqa: E731
                                               "at": now + timedelta(seconds=dt), **kw})
    for phase in ("INTERPRETED", "AERIAL_PLANNED", "VALIDATED"):
        cev("MISSION_PHASE", 0.0, phase=phase)
    cev("HEARTBEAT", arrival - 0.5, task_id=f"AIR_{first}")
    # 11-14 ------------------------------------------------------------------ synthetic camera -> observation
    over = site.point("POI_3")
    img, manifest = synthetic_scenes.render({"seed": 11, "camera": pd.CAM, "height_m": 10.0, "background": "grass",
                                             "noise": 8, "cards": [{"color": "red", "center_px": [190, 120],
                                                                    "angle_deg": 18, **pd.CARD}]})
    stamp = now + timedelta(seconds=arrival + 0.2)
    ext, pose = geometry.virtual_rig(first, pd.CAM, position_m=(over.x_m - 1.0, over.y_m, 10.0), stamp_utc=stamp,
                                     site_frame=site.local_frame.frame_id)
    k = pd.CAM
    obs = co.observe(image=img, image_stamp=stamp, image_frame_id="cam_down_fixture_optical",
                     camera_info={"header": {"frame_id": "cam_down_fixture_optical"}, "width": k["width_px"],
                                  "height": k["height_px"], "k": [k["fx"], 0, k["cx"], 0, k["fy"], k["cy"], 0, 0, 1],
                                  "d": [], "distortion_model": "plumb_bob", "calibration_status": "DECLARED_VIRTUAL"},
                     pose={**pose, "accredited": True}, now=stamp + timedelta(seconds=0.3),
                     cfg=co.CameraConfig("cam_down_fixture", first, "cam_down_fixture_optical", ext),
                     state=co.AdapterState(), site=site, context=context, fleet=fleet, policy=pd.POLICY,
                     camera_ids=im.CAMERAS, mission_cancelled=False, observation_id="two-drone-obs-1",
                     ingestion_source="TEST_FIXTURE_INGESTION",
                     image_source={"kind": "SYNTHETIC_TEST", "manifest_sha256": manifest["image_sha256"]})
    say(11, "camera", "SYNTHETIC_SENSOR: rendered SYNTHETIC_TEST image, DECLARED_VIRTUAL camera, TEST_FIXTURE pose "
        f"of {first} (not a Gazebo capture)")
    say(12, "detector", f"REAL_CODE: {obs['provenance'].get('detector')}")
    say(13, "geometry", f"REAL_CODE: {obs['status']} target {obs.get('target_site_frame')} (site frame; "
        f"{obs.get('rover_frame_conversion')})")
    if obs["status"] != "OBSERVED":
        result.update(status="STOPPED_NO_OBSERVATION", observation=obs["reasons"])
        return result
    reg = coord.handle({**obs["event"], "at": stamp + timedelta(seconds=0.3)})
    cev("AERIAL_POINT_REACHED", arrival + 1.0, task_id=f"AIR_{first}", point="POI_3")
    say(14, "coordinator", f"REAL_CODE: observation {reg['outcome']}; ground {coord.states()}")
    # 15 ----------------------------------------------------------------------------------------- Rover Agent
    b = im.plan_phase_b(pd.CONFIG, bundle, obs["gate"], safety_policy="safety/4", pin_aerial=True)
    pb = b["proposal"]
    ground = (pb.get("ground") or {}).get("proposals", [])
    ok = pb["status"] in ("PROPOSED_PENDING_AUTHORIZATION", "PARTIAL_PENDING_AUTHORIZATION")
    for phase in ("GROUND_PLANNED",) + (("GROUND_VALIDATED", "AUTHORIZATION_REQUESTED") if ok else ()):
        cev("MISSION_PHASE", arrival + 2.0, phase=phase)
    say(15, "rover_agent", f"OFFLINE_DETERMINISTIC: {pb['status']}; "
        f"{[(g['start_point'], g['target_point'], g['state']) for g in ground]}")
    # the second drone flies after the first COMPLETED (sequential realization), by the same fixtures
    land = segs[-1].t1
    for t in range(int(arrival) + 1, int(land) + 1):
        fx_event("TELEMETRY", first, float(t))
    fx_event("LANDED", first, land)
    fx_event("DISARMED", first, land)
    fx_event("READINESS", second, max(land, plans[second].start_delay_s), ready=True)
    later = sched.decide()
    say(10, "schedule", f"TEST_FIXTURE: {first} COMPLETED at {land:.1f} s; {second} {later[second]['decision']} at "
        f"{(clock.t - now).total_seconds():.1f} s (planned delay {plans[second].start_delay_s} s)")
    result["steps"]["schedule"] = {"first": first, "second": second, "second_decision": later[second],
                                   "arrival_s": round(arrival, 2), "first_landed_s": round(land, 2)}
    # 16-17 ------------------------------------------------------------------- v2 request + protected executor
    request = rb.execution_request(ground[0], site, proposal=pb, dependencies=(pb.get("template") or {}).get(
        "dependencies", []), human_limits=None) if ground else None
    problems = rb.validate_request(request) if request else ["NO_GROUND_PROPOSAL"]
    say(16, "rover_request", f"REAL_CODE: {request and request['state']}; not executable: {problems}")
    handoff = None
    if (rover_snapshot is not None or rover_local) and request is not None:
        from multiagent import integration_battery as ib, rover_handoff as rh
        demo_like = {"execution_request": request, "observation_gate": {"target": obs["gate"]["target"]},
                     "coordinator": {"ground": coord.states()}}
        with rh.rover_contract(rover_snapshot, reviewed=reviewed) as rover_side:
            source = getattr(rover_side, "tag", None)
            _, final = ib.handoff_for(demo_like, rover_side, conversion_owner="ROVER_ADAPTER")
            _, offline = ib.handoff_for(demo_like, rover_side, conversion_owner="MULTIAGENT_FRAMES2D")
        st = {s["stage"]: s for s in offline["stages"]}
        handoff = {"final": final["classification"], "offline_test": offline["classification"],
                   "executor_admit": st["executor_admit"]["reasons"], "commands": len(final["commands"]) +
                   len(offline["commands"]), "snapshot": final.get("rover_snapshot") or source}
        say(16, "rover_v2", f"REAL_CODE (rover snapshot {handoff['snapshot']}), TEST_FIXTURE limits/authorization: "
            f"final contract {final['classification']}; offline test path {offline['classification']}")
        say(17, "executor", f"REAL_CODE: admission {st['executor_admit']['status']} {st['executor_admit']['reasons']}")
    else:
        say(17, "executor", "rover hand-off not requested: the v2 hand-off is not run (--rover-handoff, or a historical "
            "--rover-snapshot DIR)")
    result["steps"]["rover"] = {"proposal": pb["status"], "request_state": request and request["state"],
                                "request_problems": problems, "handoff": handoff}
    # 18 ------------------------------------------------------------------------------------- zero commands
    result["commands"] = (pa.get("commands_sent") or 0) + (pb.get("commands_sent") or 0) + len(req["commands"]) + \
        ((handoff or {}).get("commands") or 0)
    say(18, "result", f"commands {result['commands']}; submitted to any executor: False; SITL/Gazebo NOT_EXECUTED")
    result.update(status="COMPLETED_OFFLINE", plan_source=plan_source, coordinator=coord.summary(),
                  observation={k: obs.get(k) for k in ("status", "target_site_frame", "provenance")},
                  labels={"agents": plan_source["kind"], "sensor": "SYNTHETIC_SENSOR", "events": "TEST_FIXTURE",
                          "executor": "DRY_RUN", "simulation": "NOT_EXECUTED"}, console=say.lines)
    if out is not None:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True, default=str))
    return result
