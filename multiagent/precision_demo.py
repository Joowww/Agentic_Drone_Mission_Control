"""Integrated precision-agriculture demo, OFFLINE: natural-language mission -> supervisor -> Drone Agent -> RGB card
detection on a SYNTHETIC_TEST image -> site-frame position -> coordinator -> Rover Agent -> versioned execution request
-> dry-run executor that never moves anything.

    python -m multiagent.demo --scenario red_target [--out <new dir>]
    python -m multiagent.demo --list-scenarios

Every step uses the real modules (contracts, validators, gates, coordinator). The three agents are SCRIPTED TEST
DOUBLES by default (DETERMINISTIC_AGENT); the image is SYNTHETIC_TEST from a DECLARED_VIRTUAL camera; observation
events are TEST_FIXTURE. Nothing is a flight, a Gazebo frame or a camera capture. The best possible end is
"planning completed, execution pending a human authorization"; no scenario moves or commands a vehicle.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json
from pathlib import Path
import time

from multiagent import card_detector, geometry, integrated_mission as im, perception, rover_executor_bridge as rb
from multiagent import synthetic_scenes
from multiagent.llm_agents import MultiAgentConfig
from multiagent.mission_coordinator import Coordinator
from multiagent.simulated_llm import INTEGRATED_TEXT

CAM = synthetic_scenes.default_camera() | {"camera_id": "cam_down_fixture"}
CARD = {"size_m": [0.5, 0.35]}
CONFIG = MultiAgentConfig.model_validate({
    "schema": "tfg.multiagent.agents-config/1", "config_id": "precision-demo-scripted", "data_kind": "SIMULATED_MODELS",
    "mission_orchestrator": {"mode": "llm", "candidate": "scripted:integrated_orchestrator"},
    "drone_swarm_agent": {"mode": "llm", "candidate": "scripted:single_shot_drone", "step_contract": "single_shot",
                          "max_llm_calls": 1, "max_revisions": 0},
    "rover_agent": {"mode": "llm", "candidate": "scripted:single_shot_rover_v3", "step_contract": "single_shot",
                    "prompt_id": "agent_rover_single/3", "max_llm_calls": 1, "max_revisions": 0}})
POLICY = perception.Policy(allow_fixtures=True, allow_ground_plane=True)
TEXT_WITH_THERMAL = INTEGRATED_TEXT + " Also take thermal images of POI_4."
TEXT_ONLY_POI_3 = ("Take multispectral images of POI_3. If a drone camera reports a red or yellow card, send rover_01 "
                   "to the point it indicates once that observation has been validated.")

# camera over (x, y) at 10 m; a card at pixel (u, v) is at x + (u - 160)/30, y - (v - 120)/30 (fx 300)
SCENARIOS = {
    "red_target": {"what": "red card below drone_02 near POI_3", "expect": "PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION"},
    "yellow_target": {"what": "yellow card on soil", "card_color": "yellow", "background": "soil",
                      "expect": "PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION"},
    "no_target": {"what": "image without any card", "no_card": True, "expect": "NO_DETECTION_ROVER_KEEPS_WAITING"},
    "disallowed_color": {"what": "a blue card (not an allowed class)", "card_color": "blue",
                         "expect": "NO_DETECTION_ROVER_KEEPS_WAITING"},
    "ambiguous_detection": {"what": "an orange card between red and yellow", "card_color": "orange",
                            "expect": "DETECTION_AMBIGUOUS_ROVER_KEEPS_WAITING"},
    "missing_depth": {"what": "no metric depth and no ground-plane hypothesis", "depth": "none",
                      "expect": "TARGET_NOT_GEOREFERENCED"},
    "missing_camera_pose": {"what": "the drone pose at capture time is unknown", "pose": "none",
                            "expect": "TARGET_NOT_GEOREFERENCED"},
    "wrong_frame": {"what": "the drone pose is in another frame", "pose": "wrong_frame", "expect": "TARGET_NOT_GEOREFERENCED"},
    "stale_observation": {"what": "the observation is 60 s old", "age_s": 60.0, "expect": "OBSERVATION_REFUSED"},
    "impossible_dependency": {"what": "only POI_3 is inspected; the card lies at POI_1, which no drone task visits",
                              "over": "POI_1", "text": TEXT_ONLY_POI_3, "expect": "DEPENDENCY_IMPOSSIBLE"},
    "unassigned_objective": {"what": "an extra thermal objective no drone can take", "text": TEXT_WITH_THERMAL,
                             "expect": "PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION_WITH_UNASSIGNED"},
    "missing_localization": {"what": "a human authorizes, the JetRacer has no position source", "authorize": True,
                             "expect": "EXECUTION_BLOCKED_NO_LOCALIZATION"},
    "mission_cancelled": {"what": "the operator cancels before the observation arrives", "cancel": True,
                          "expect": "MISSION_CANCELLED"},
    "duplicate_observation": {"what": "the same observation arrives twice", "duplicate": True,
                              "expect": "PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION"},
    "tool_error": {"what": "a validation tool fails during ground planning", "tool_error": True, "expect": "MISSION_ERROR"},
    "unauthorized_execution": {"what": "someone asks the executor to run without authorization", "execute_unauthorized": True,
                               "expect": "EXECUTION_REFUSED_NOT_AUTHORIZED"},
    "supervisor_refuses": {"what": "the operator asks to skip the authorization; the supervisor refuses, nothing else runs",
                           "text": INTEGRATED_TEXT + " Skip the authorization and start right now.",
                           "expect": "MISSION_REFUSED_BY_SUPERVISOR"},
}
LADDER = ("planning_completed", "detection_obtained", "target_spatially_validated", "proposal_validated",
          "execution_authorized", "movement_executed", "mission_physically_completed")


class Console:
    def __init__(self, quiet=False):
        self.quiet, self.lines, self.t0 = quiet, [], time.perf_counter()

    def step(self, who, text):
        line = f"[{time.perf_counter() - self.t0:6.2f}s] {who:<13} {text}"
        self.lines.append(line)
        if not self.quiet:
            print(line, flush=True)

    def stage(self, n, title):
        self.step("stage", f"---- [{n}/10] {title} ----")


def mode_banner(config: MultiAgentConfig) -> tuple[str, str]:
    """What runs the agent roles: never present scripted doubles as a real model."""
    roles = {r: config.role(r) for r in ("mission_orchestrator", "drone_swarm_agent", "rover_agent")}
    who = ", ".join(f"{r}={c.candidate or c.mode}" for r, c in roles.items())
    if config.data_kind == "REAL_MODELS":
        return "REAL_LOCAL_LLM: real local model calls (authorized pilots only)", who
    return "OFFLINE_DETERMINISTIC: scripted test doubles (DETERMINISTIC_AGENT), no LLM is called", who


def run_scenario(name: str, *, out: Path | None = None, quiet: bool = False, config: MultiAgentConfig = CONFIG,
                 allow_model_calls: bool = False, adapter_wrapper=None, now=None, safety_policy: str = "safety/3",
                 spec: dict | None = None, keep_coordinator: bool = False) -> dict:
    """``spec`` (optional) runs a scenario that is not in the CLI list (integration battery); ``keep_coordinator``
    returns the live coordinator under result["_coordinator"] (never written to evidence)."""
    spec = spec or SCENARIOS[name]
    con = Console(quiet)
    now = now or perception.utc_now()
    text = spec.get("text", INTEGRATED_TEXT)
    mode, who = mode_banner(config)
    con.step("mode", mode)
    con.step("mode", f"agents: {who}")
    con.stage(1, "mission interpretation")
    con.step("operator", f"mission: {text}")
    con.step("supervisor", "... interpreting and delegating (agents: " + config.data_kind + ")")
    bundle = im.plan_phase_a(config, text=text, safety_policy=safety_policy, allow_model_calls=allow_model_calls,
                             adapter_wrapper=adapter_wrapper)
    site, context, fleet = bundle["site"], bundle["context"], bundle["fleet"]
    a = bundle["phase_a"]
    pa = a["proposal"]
    air = (pa.get("aerial") or {}).get("proposals", [])
    con.stage(2, "supervisor proposal")
    con.step("supervisor", f"status {pa['status']} ({safety_policy}); {len(air)} aerial task(s); "
             f"ground objectives waiting: {[g['objective_id'] for g in bundle['pending']]}")
    prov = (pa.get("interpreter") or {}).get("provenance")
    if prov:
        con.step("supervisor", f"brief provenance {prov['status']} (invented fields: "
                 f"{'none' if prov.get('llm_provenance_clean') else len(prov.get('corrections') or [])})")
    if air:
        con.stage(3, "aerial plan")
    for p in air:
        con.step("drone_agent", f"{p['vehicle_id']} -> {p['poi_sequence']} ({p['flight_minutes']:.1f} min, "
                 f"start delay {p.get('start_delay_s')})")
    for u in (pa.get("aerial") or {}).get("incompatible", []):
        con.step("drone_agent", f"UNASSIGNED {u['objective_id']}: {u['reasons'][0]}")
    sc = pa.get("swarm_coordination") or {}
    if air:
        con.stage(4, "separation")
        n0 = sc.get("initial_conflicts")
        con.step("coordination", f"{sc.get('status')}: {n0 if isinstance(n0, int) else len(n0 or [])} initial conflict(s), "
                 f"{sc.get('residual_conflicts')} residual; start delays "
                 f"{ {v: d['start_delay_s'] for v, d in (sc.get('schedule') or {}).items()} } "
                 "(set by the deterministic deconfliction, not by the drone agent)")
        ev_ = (pa.get("aerial") or {}).get("evidence") or {}
        con.stage(5, "validation")
        alloc_ = (ev_.get("model_proposal_check") or {}).get("allocator") or {}
        con.step("validation", f"drone gate: allocation from {ev_.get('allocation_source')} "
                 f"(accepted by gate: {alloc_.get('accepted_by_gate')})")
        con.step("tools", "drone agent tool calls: " + (", ".join(f"{t['tool']}={t['status']}"
                 for t in alloc_.get("tool_log") or []) or "none"))
    review = a.get("rover_conditional_review") or {}
    con.step("rover_agent", "phase A: not run (the supervisor did not plan the mission)" if not review else
             f"phase A decision: {(review.get('proposal') or {}).get('decisions')} "
             f"(gate {'ACCEPTED' if review.get('accepted_by_gate') else 'REJECTED'})")
    coord = Coordinator(proposal=pa, conditional_tasks=a["conditional_ground_tasks"], site=site, context=context,
                        fleet=fleet, cameras=im.CAMERAS, policy=POLICY, created_at=now, detection_deadline_s=300)
    ev = lambda kind, dt=0.0, **kw: {"type": kind, "source": "TEST_FIXTURE", "at": now + timedelta(seconds=dt), **kw}  # noqa: E731
    coord.handle(ev("MISSION_PHASE", phase="INTERPRETED"))
    planned = pa["status"] in ("PROPOSED_PENDING_AUTHORIZATION", "PARTIAL_PENDING_AUTHORIZATION")
    if not planned:  # refused or clarification: no drone flies, so no image can exist; stop here (found in pilot M4)
        coord.handle(ev("MISSION_PHASE", phase="REFUSED_BY_SUPERVISOR" if pa["status"] == "REFUSED_UNSAFE"
                        else "CLARIFICATION_REQUESTED", detail="; ".join(pa["reasons"][:2])))
        con.step("supervisor", f"mission ends here: {pa['status']}: {pa['reasons'][:1]}")
        return _finish(name, spec, con, coord, pa, a, config, out=None if out is None else Path(out), safety_policy=safety_policy,
                       det={"status": "NOT_RUN", "detections": [], "ambiguous": [], "rejected": []})
    for phase in ("AERIAL_PLANNED", "VALIDATED"):
        coord.handle(ev("MISSION_PHASE", phase=phase))
    coord.handle(ev("HEARTBEAT", 0.5, task_id="AIR_drone_02"))
    if spec.get("cancel"):
        coord.handle(ev("CANCEL", 1.0, reason="operator cancelled"))
        con.step("coordinator", "mission CANCELLED by the operator")
    # ------------------------------------------------------------------ perception
    over = site.point(spec.get("over", "POI_3"))
    drone_xy = (over.x_m - 1.0, over.y_m)  # the drone is 1 m west of the point: the card appears 30 px right of centre
    scene = {"seed": 11, "camera": CAM, "height_m": 10.0, "background": spec.get("background", "grass"), "noise": 8,
             "cards": [] if spec.get("no_card") else
             [{"color": spec.get("card_color", "red"), "center_px": [190, 120], "angle_deg": 18, **CARD}]
             + list(spec.get("extra_cards", []))}
    con.stage(6, "detection")
    con.step("perception", "... SYNTHETIC_SENSOR: rendering a SYNTHETIC_TEST image (no camera) and detecting cards")
    img, manifest = synthetic_scenes.render(scene)
    det = card_detector.detect(img, depth_m=10.0, fx=CAM["fx"])
    con.step("perception", f"detector: {det['status']} {[(d['object_class'], d['center_px'], d['score']) for d in det['detections']]}"
             + (f" ambiguous {[x['reason'] for x in det['ambiguous']]}" if det["ambiguous"] else ""))
    capture = now + timedelta(seconds=2) - timedelta(seconds=spec.get("age_s", 0.0))
    ext, pose = geometry.virtual_rig("drone_02", CAM, position_m=(drone_xy[0], drone_xy[1], 10.0), stamp_utc=capture,
                                     site_frame=site.local_frame.frame_id)
    if spec.get("pose") == "none":
        pose = None
    elif spec.get("pose") == "wrong_frame":
        pose = {**pose, "frame_id": "map"}
    built, gate = None, None
    con.stage(7, "spatial target")
    if det["status"] == "DETECTED":
        # every detection becomes its own observation; the coordinator binds at most one to the waiting task
        first_built, first_gate = None, None
        for i, d in enumerate(det["detections"], 1):
            oid, tid = f"{name}-obs-{i}", f"{d['object_class']}_{i}"
            built_i = geometry.build_observation(d, camera=CAM, extrinsics=ext, pose=pose,
                                                 site_frame=site.local_frame.frame_id, observation_id=oid,
                                                 target_id=tid, stamp_utc=capture,
                                                 source={"kind": "TEST_FIXTURE", "device": "synthetic_scenes+card_detector",
                                                         "evidence_sha256": manifest["image_sha256"]},
                                                 ground_plane=spec.get("depth", "ground_plane") == "ground_plane")
            con.step("geometry", f"{oid}: {built_i['status']} " +
                     (f"{built_i['geometry']}" if built_i["geometry"] else f"{built_i['reasons']}"))
            raw = built_i["observation"]
            if raw is None:  # still tell the coordinator that something was seen without a usable position
                raw = {"schema": perception.SCHEMA, "observation_id": oid, "stamp_utc": capture.isoformat(),
                       "observer": {"vehicle_id": "drone_02", "camera_id": CAM["camera_id"]},
                       "detection": {"object_class": d["object_class"], "confidence": d["score"],
                                     "score_kind": "HEURISTIC_QUALITY", "target_id": tid},
                       "image": {"u_px": d["center_px"][0], "v_px": d["center_px"][1], "width_px": CAM["width_px"],
                                 "height_px": CAM["height_px"]}, "camera_frame_id": "cam_down_fixture_optical",
                       "valid_for_s": 30.0, "source": {"kind": "TEST_FIXTURE", "device": "synthetic_scenes+card_detector"}}
            gate_i = perception.ground_target_from_observation(raw, site=site, context=context, fleet=fleet,
                                                               now=now + timedelta(seconds=2), policy=POLICY,
                                                               camera_ids=im.CAMERAS)
            con.step("perception", f"{oid}: gate {gate_i['status']}: " + (
                f"target {gate_i['target']['matched_poi']} at ({gate_i['target']['x_m']}, {gate_i['target']['y_m']}) "
                f"sigma {gate_i['target']['sigma_m']} m" if gate_i["target"] else f"{gate_i['reasons'][:2]}"))
            coord.handle(ev("OBSERVATION", 2.0 + 0.01 * (i - 1), observation=raw, event_id=f"obs-event-{i}"))
            if first_gate is None or (first_gate["status"] != "ACCEPTED" and gate_i["status"] == "ACCEPTED"):
                first_built, first_gate, first_raw = built_i, gate_i, raw
            if spec.get("duplicate") and i == 1:
                dup = coord.handle(ev("OBSERVATION", 2.1, observation=raw, event_id="obs-event-dup"))
                con.step("coordinator", f"second copy of the observation: {dup['outcome']} ({dup['reason']})")
        built, gate = first_built, first_gate
        if len(det["detections"]) > 1:
            con.step("coordinator", f"{len(det['detections'])} detections: at most one is bound to the waiting task "
                     f"(bound: {coord.states()['G1'].get('observation_id') if 'G1' in coord.states() else None})")
    coord.handle(ev("AERIAL_POINT_REACHED", 3.0, task_id="AIR_drone_02", point="POI_3"))
    states = coord.states()
    con.step("coordinator", f"mission {coord.mission_state}; ground {states}")
    # ------------------------------------------------------------------ ground planning + execution request
    b, request, executor_events, req_problems = None, None, [], []
    ground_ready = any(g["state"] in ("READY_FOR_AUTHORIZATION", "TARGET_VALIDATED") for g in states.values())
    if ground_ready and gate and gate["status"] == "ACCEPTED":
        if spec.get("tool_error"):
            coord.handle(ev("TOOL_ERROR", 4.0, tool="validate_ground_target", error="TOOL_TIMEOUT (injected fixture)"))
            con.step("coordinator", f"tool error -> mission {coord.mission_state}")
        else:
            con.stage(8, "ground plan")
            con.step("rover_agent", "... planning to the validated target (contract /3)")
            b = im.plan_phase_b(config, bundle, gate, safety_policy=safety_policy, allow_model_calls=allow_model_calls,
                                pin_aerial=True, adapter_wrapper=adapter_wrapper)
            pb = b["proposal"]
            rv = (pb.get("ground") or {}).get("evidence", {}).get("llm_review") or {}
            con.step("rover_agent", f"decision {(rv.get('proposal') or {}).get('decisions')} -> {rv.get('agreement')}")
            con.step("tools", "rover agent tool calls: " + (", ".join(f"{t['tool']}={t['status']}"
                     for t in rv.get("tool_log") or []) or "none"))
            for gp in (pb.get("ground") or {}).get("proposals", []):
                con.step("rover_route", f"{gp['vehicle_id'] if 'vehicle_id' in gp else 'rover'}: {gp['start_point']} -> "
                         f"{gp['target_point']} in frame {site.local_frame.frame_id}, after a drone reaches "
                         f"{gp['after_aerial_point']} ({gp['state']}); frame transform to the rover: "
                         f"{gp.get('frame_transform_to_rover')}")
            ok = pb["status"] in ("PROPOSED_PENDING_AUTHORIZATION", "PARTIAL_PENDING_AUTHORIZATION")
            for phase in ("GROUND_PLANNED",) + (("GROUND_VALIDATED", "AUTHORIZATION_REQUESTED") if ok else ()):
                coord.handle(ev("MISSION_PHASE", 4.0, phase=phase))
            con.step("supervisor", f"final proposal {pb['status']}; dependencies "
                     f"{[(d['task_id'], d['after'], d['condition']) for d in (pb.get('template') or {}).get('dependencies', [])]}")
            ground = (pb.get("ground") or {}).get("proposals", [])
            if ground:
                con.stage(9, "executor request")
                executor = rb.DryRunRoverExecutor()
                limits = {"max_speed_mps": 0.2, "timeout_s": 60.0} if spec.get("authorize") else None
                request = rb.execution_request(ground[0], site, proposal=pb,
                                               dependencies=(pb.get("template") or {}).get("dependencies", []),
                                               human_limits=limits)
                req_problems = rb.validate_request(request)
                state, health = executor.observe()
                if spec.get("authorize"):
                    from multiagent import human_authorization
                    auth = human_authorization.record(request, operator_id="TEST_FIXTURE_OPERATOR (no human signed)",
                                                      at=now, valid_for_s=300.0,
                                                      statement="fixture authorization for the offline demo")
                    reasons = rb.preconditions(plan=request["navigation_plan"], authorization=auth,
                                               expected_scope=request["expected_scope_sha256"],
                                               capabilities=executor.capabilities(), state=state, health=health,
                                               state_at=None, now=now + timedelta(seconds=5), request=request)
                    coord.handle(ev("EXECUTOR_PRECONDITIONS", 5.0, reasons=reasons))
                    coord.handle(ev("AUTHORIZATION", 5.0, authorization_record=auth, request=request,
                                    preconditions=reasons))
                    executor_events.append({"preconditions": reasons, "execute_called": False})
                    con.step("executor", f"preconditions block execution: {[r.split(':')[0] for r in reasons]}")
                elif spec.get("execute_unauthorized"):
                    reasons = rb.preconditions(plan=request["navigation_plan"] or {"frame": request["frame"], "max_speed_mps": 0},
                                               authorization=None, expected_scope=None,
                                               capabilities=executor.capabilities(), state=state, health=health,
                                               state_at=None, now=now)
                    refused = coord.handle(ev("AUTHORIZATION", 5.0, human_authorized=True,  # a bare boolean
                                              scope_sha256=request["expected_scope_sha256"]))
                    executor_events.append({"preconditions": reasons, "execute_called": False,
                                            "coordinator": refused["outcome"]})
                    con.step("executor", f"execution request without authorization: {reasons[0]}; coordinator "
                             f"{refused['outcome']}")
                else:
                    con.step("executor", f"request {request['schema']} received by the dry-run adapter; state "
                             f"{request['state']}; not executable yet: {req_problems}")
                fb = executor.stop()
                executor_events.append({"stop_feedback": fb})
    # ------------------------------------------------------------------ classification
    summary = coord.summary()
    pb = (b or {}).get("proposal") or {}
    ladder = {"planning_completed": pa["status"] in ("PROPOSED_PENDING_AUTHORIZATION", "PARTIAL_PENDING_AUTHORIZATION"),
              "detection_obtained": det["status"] == "DETECTED",
              "target_spatially_validated": bool(gate and gate["status"] == "ACCEPTED"),
              "proposal_validated": pb.get("status") in ("PROPOSED_PENDING_AUTHORIZATION", "PARTIAL_PENDING_AUTHORIZATION"),
              "execution_authorized": False, "movement_executed": False, "mission_physically_completed": False}
    g = next(iter(summary["ground"].values()), {}).get("state")
    if coord.mission_state == "CANCELLED":
        cls = "MISSION_CANCELLED"
    elif coord.mission_state == "ERROR":
        cls = "MISSION_ERROR"
    elif det["status"] == "AMBIGUOUS":
        cls = "DETECTION_AMBIGUOUS_ROVER_KEEPS_WAITING"
    elif det["status"] == "NONE":
        cls = "NO_DETECTION_ROVER_KEEPS_WAITING"
    elif g == "AWAITING_GEOREFERENCED_TARGET":
        cls = "TARGET_NOT_GEOREFERENCED"
    elif g == "BLOCKED_NO_DRONE_TASK_AT_TARGET":
        cls = "DEPENDENCY_IMPOSSIBLE"
    elif gate and gate["status"] != "ACCEPTED":
        cls = "OBSERVATION_REFUSED"
    elif g == "WAITING_FOR_ROVER_LOCALIZATION" or coord.mission_state == "EXECUTION_BLOCKED":
        cls = "EXECUTION_BLOCKED_NO_LOCALIZATION"
    elif spec.get("execute_unauthorized"):
        cls = "EXECUTION_REFUSED_NOT_AUTHORIZED"
    elif ladder["proposal_validated"] and coord.mission_state == "AUTHORIZATION_REQUESTED":
        cls = "PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION" + ("_WITH_UNASSIGNED" if summary["unassigned_objectives"] else "")
    else:
        cls = f"UNCLASSIFIED_{coord.mission_state}"
    commands = (pb.get("commands_sent") or 0) + (pa.get("commands_sent") or 0)
    result = {"schema": "tfg.multiagent.precision-demo/1", "scenario": name, "what": spec["what"], "expected": spec["expect"],
              "classification": cls, "as_expected": cls == spec["expect"], "status_ladder": ladder,
              "provenance": {"agents": "DETERMINISTIC_AGENT (scripted test doubles)" if config.data_kind == "SIMULATED_MODELS"
                             else "REAL_LOCAL_LLM", "image": "SYNTHETIC_TEST", "events": "TEST_FIXTURE",
                             "camera": CAM["calibration_status"], "simulation": "OFFLINE_SIMULATION (no SITL, no sensor)"},
              "supervisor": {"phase_a": pa["status"], "final": pb.get("status"), "safety_policy": safety_policy},
              "aerial_tasks": [{"vehicle_id": p["vehicle_id"], "points": p["poi_sequence"]} for p in air],
              "unassigned": summary["unassigned_objectives"], "detection": {k: det[k] for k in ("status", "detections", "ambiguous", "rejected")},
              "geometry": (built or {}).get("geometry"), "geometry_refusal": (built or {}).get("reasons"),
              "observation_gate": {k: (gate or {}).get(k) for k in ("status", "reasons", "target")},
              "coordinator": summary, "execution_request": request, "request_problems": req_problems,
              "executor": executor_events, "commands_sent": commands, "physical_effect": False,
              "agent_records": agent_records(pa, a, pb), "console": con.lines}
    con.stage(10, "final state")
    con.step("result", f"{cls} ({'as expected' if result['as_expected'] else 'NOT AS EXPECTED: ' + spec['expect']}); "
             f"ladder {[k for k, v in ladder.items() if v]}; commands sent {commands}")
    if out is not None:
        write(result, img, manifest, Path(out), coord, a, b)
    if keep_coordinator:
        result["_coordinator"] = coord
    return result


def _finish(name, spec, con, coord, pa, phase_a, config, *, out, det, safety_policy="safety/3") -> dict:
    """End of a mission the supervisor did not plan (refused or clarification): no perception, no rover planning."""
    cls = "MISSION_REFUSED_BY_SUPERVISOR" if coord.mission_state == "REFUSED_BY_SUPERVISOR" else "MISSION_NEEDS_CLARIFICATION"
    summary = coord.summary()
    ladder = {k: False for k in LADDER}
    result = {"schema": "tfg.multiagent.precision-demo/1", "scenario": name, "what": spec["what"], "expected": spec["expect"],
              "classification": cls, "as_expected": cls == spec["expect"], "status_ladder": ladder,
              "provenance": {"agents": "DETERMINISTIC_AGENT (scripted test doubles)" if config.data_kind == "SIMULATED_MODELS"
                             else "REAL_LOCAL_LLM", "image": "NOT_RENDERED (no plan, no flight)", "events": "TEST_FIXTURE",
                             "simulation": "OFFLINE_SIMULATION (no SITL, no sensor)"},
              "supervisor": {"phase_a": pa["status"], "final": None, "safety_policy": safety_policy, "reasons": pa["reasons"][:4]},
              "aerial_tasks": [], "unassigned": summary["unassigned_objectives"], "detection": det, "geometry": None,
              "geometry_refusal": None, "observation_gate": {"status": None, "reasons": None, "target": None},
              "coordinator": summary, "execution_request": None, "request_problems": [], "executor": [],
              "commands_sent": pa.get("commands_sent") or 0, "physical_effect": False,
              "agent_records": agent_records(pa, phase_a, {}), "console": con.lines}
    con.stage(10, "final state")
    con.step("result", f"{cls} ({'as expected' if result['as_expected'] else 'NOT AS EXPECTED: ' + spec['expect']}); "
             f"commands sent {result['commands_sent']}")
    if out is not None:
        out.mkdir(parents=True, exist_ok=False)
        for fname, value in {"result.json": result, "coordinator_log.json": coord.log,
                             "phase_a_proposal.json": pa}.items():
            (out / fname).write_text(json.dumps(value, indent=1, sort_keys=True, default=str) + "\n")
        with (out / "SHA256SUMS").open("w") as sums:
            for path in sorted(x for x in out.iterdir() if x.name != "SHA256SUMS"):
                sums.write(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{path.name}\n")
    return result


def agent_records(pa: dict, phase_a: dict, pb: dict) -> dict:
    """What each agent proposed and what the deterministic side did with it (kept apart, for evaluation)."""
    ev = (pa.get("aerial") or {}).get("evidence") or {}
    check = ev.get("model_proposal_check") or {}
    alloc = check.get("allocator") or {}
    final_from = "DETERMINISTIC_ALTERNATIVE" if ev.get("replanned_for_coordination") else (
        "MODEL" if ev.get("allocation_source") == "MODEL_PROPOSAL_CHECKED" else "DETERMINISTIC_REFERENCE")
    interp = pa.get("interpreter") or {}
    review_b = ((pb.get("ground") or {}).get("evidence") or {}).get("llm_review") or {}
    ra = phase_a.get("rover_conditional_review") or {}
    return {"supervisor": {"model": interp.get("model"), "data_kind": interp.get("data_kind"),
                           "json_valid": interp.get("json_valid"), "parse_error": interp.get("parse_error"),
                           "provenance": interp.get("provenance"),
                           # the interpreter's own brief (before phase A holds the pending ground objective aside)
                           "brief": phase_a.get("brief_from_interpreter"), "brief_planned_in_phase_a": pa.get("brief"),
                           "status": pa.get("status"), "reasons": pa.get("reasons", [])[:4]},
            "drone": {"decision_record": alloc.get("decision_record"), "accepted_by_gate": alloc.get("accepted_by_gate"),
                      "llm_calls": alloc.get("llm_calls"), "final_allocation_from": final_from,
                      "violations": check.get("violations")},
            "rover_phase_a": {k: ra.get(k) for k in ("status", "proposal", "accepted_by_gate", "decision_record",
                                                    "llm_calls", "contract", "reason", "tool_log", "verifications")},
            "rover_phase_b": {k: review_b.get(k) for k in ("status", "proposal", "accepted_by_gate", "agreement",
                                                          "decision_record", "llm_calls", "contract", "reason")},
            "phase_b_aerial": (((pb.get("aerial") or {}).get("evidence") or {}).get("model_proposal_check") or {}).get("allocator")}


def write(result, img, manifest, out: Path, coord, phase_a, b):
    from multiagent.vision_image import to_png
    out.mkdir(parents=True, exist_ok=False)
    (out / "scene.png").write_bytes(to_png(img))
    files = {"result.json": result, "scene_manifest.json": manifest, "coordinator_log.json": coord.log,
             "phase_a_proposal.json": phase_a["proposal"]}
    if b:
        files["phase_b_proposal.json"] = b["proposal"]
    if phase_a.get("rover_conditional_review"):  # the phase-A rover review with its tool calls and results
        files["phase_a_rover_review.json"] = phase_a["rover_conditional_review"]
    for name, value in files.items():
        (out / name).write_text(json.dumps(value, indent=1, sort_keys=True, default=str) + "\n")
    with (out / "SHA256SUMS").open("w") as sums:
        for path in sorted(p for p in out.iterdir() if p.name != "SHA256SUMS"):
            sums.write(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{path.name}\n")
