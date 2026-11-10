"""Offline integration battery: each mission runs the REAL modules end to end and is judged on what they return.

    python -m multiagent.integration_battery [--out <new dir>]                    # this repository's rover code
    python -m multiagent.integration_battery --snapshot <dir> [--reviewed]        # a pinned historical revision

Chain per scenario: scripted supervisor / Drone Agent / Rover Agent (DETERMINISTIC_AGENT doubles, NOT Qwen: the
real-LLM run is M4c-r1, shown by `python -m multiagent.demo --replay`) -> safety policy and validators -> synthetic
image -> card detector -> geometry -> perception gate -> coordinator -> rover-execution-request -> site->odom frames
-> the rover's v2 adapter/validator and executor admission (real code of this repository imported in-process; a
pinned snapshot only to reproduce sealed evidence) -> dry-run adapter ->
coordinator events. Nothing is printed instead of computed; nothing moves; every row checks zero commands.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

from multiagent import human_authorization as ha, precision_demo as pd, rover_executor_bridge as rb
from multiagent import rover_handoff as rh, rover_handoff_fixtures as fx, rover_sitl_interfaces as si
from multiagent import frames2d as f

AGENTS = "DETERMINISTIC_AGENT (scripted doubles through the real contracts; NOT Qwen)"
P = "PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION"
TWO_CARDS = {**pd.SCENARIOS["red_target"], "what": "a red card at POI_3 and a yellow card elsewhere in the same image",
             "extra_cards": [{"color": "yellow", "center_px": [90, 60], "angle_deg": 0, **pd.CARD}]}

# name -> demo scenario (or spec), what the hand-off does, what follows in the coordinator, expectations
BATTERY = {
    "red_card": dict(demo="red_target", handoff="complete", expect=dict(demo=P, handoff="READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED",
                                                                       coordinator="EXECUTION_BLOCKED")),
    "yellow_card": dict(demo="yellow_target", handoff="complete", expect=dict(demo=P, handoff="READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED",
                                                                             coordinator="EXECUTION_BLOCKED")),
    "two_cards": dict(spec=TWO_CARDS, handoff="complete", expect=dict(demo=P, handoff="READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED",
                                                                     coordinator="EXECUTION_BLOCKED", detections=2)),
    "no_detection": dict(demo="no_target", expect=dict(demo="NO_DETECTION_ROVER_KEEPS_WAITING")),
    "ambiguous_detection": dict(demo="ambiguous_detection", expect=dict(demo="DETECTION_AMBIGUOUS_ROVER_KEEPS_WAITING")),
    "missing_depth": dict(demo="missing_depth", expect=dict(demo="TARGET_NOT_GEOREFERENCED")),
    "missing_pose": dict(demo="missing_camera_pose", expect=dict(demo="TARGET_NOT_GEOREFERENCED")),
    "rover_without_localization": dict(demo="red_target", handoff="no_localization",
                                       expect=dict(demo=P, handoff="BLOCKED_BEFORE_SUBMISSION", coordinator="AUTHORIZATION_REQUESTED",
                                                   ground="WAITING_FOR_ROVER_LOCALIZATION")),
    "wrong_transform": dict(demo="red_target", handoff="expired_transform",
                            expect=dict(demo=P, handoff="BLOCKED_BEFORE_SUBMISSION", coordinator="AUTHORIZATION_REQUESTED")),
    "separation_conflict_resolved_by_delay": dict(demo="red_target", expect=dict(demo=P, separation="DECONFLICTED_BY_START_DELAY")),
    "stale_observation": dict(demo="stale_observation", expect=dict(demo="OBSERVATION_REFUSED")),
    "duplicate_target": dict(demo="duplicate_observation", expect=dict(demo=P)),
    "aerial_dependency_failed": dict(demo="impossible_dependency", expect=dict(demo="DEPENDENCY_IMPOSSIBLE")),
    "no_authorization": dict(demo="red_target", handoff="unsigned",
                             expect=dict(demo=P, handoff="BLOCKED_BEFORE_SUBMISSION", coordinator="AUTHORIZATION_REQUESTED")),
    "expired_plan": dict(demo="red_target", handoff="expired_record",
                         expect=dict(demo=P, handoff="BLOCKED_BEFORE_SUBMISSION", coordinator="AUTHORIZATION_REQUESTED")),
    "executor_refuses": dict(demo="red_target", handoff="complete", after="EXECUTOR_REFUSED",
                             expect=dict(demo=P, handoff="READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED", coordinator="EXECUTION_BLOCKED")),
    "uncertain_stop": dict(demo="red_target", handoff="complete", after="STOP_UNCERTAIN",
                           expect=dict(demo=P, handoff="READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED", coordinator="UNKNOWN")),
    "mission_cancelled": dict(demo="mission_cancelled", expect=dict(demo="MISSION_CANCELLED")),
}


def _request_from(result: dict, now: datetime, *, sign=True, at=None):
    """The run's own request, with TEST_FIXTURE human limits and record (the run itself had none)."""
    r = result["execution_request"]
    task = {"task_id": r["task_id"], "vehicle_id": r["vehicle_id"], "target_point": r["target"]["point_id"],
            "start_point": r["target"]["start_point"]}
    req = rb.execution_request(task, fx.SITE, proposal={"proposal_sha256": r["proposal_sha256"]},
                               dependencies=r["dependencies"], human_limits=fx.HUMAN_LIMITS)
    if not sign:
        return req
    rec = ha.record(req, operator_id="TEST_FIXTURE_OPERATOR", at=at or now - timedelta(seconds=1), valid_for_s=300,
                    statement="offline battery fixture; no human approved a mission")
    return rb.execution_request(task, fx.SITE, proposal={"proposal_sha256": r["proposal_sha256"]},
                                dependencies=r["dependencies"], human_limits=fx.HUMAN_LIMITS, authorization=rec)


def handoff_for(demo: dict, rover_side: rh.RoverSnapshot, *, mode: str = "complete", now: datetime | None = None,
                conversion_owner: str = "MULTIAGENT_FRAMES2D"):
    """The hand-off of a demo run's request with TEST_FIXTURE limits, record, transform and localization (``mode``
    removes one of them). ``conversion_owner``: the battery's offline test mode by default (stated here, never
    inferred); ROVER_ADAPTER gives the final contract. Returns (request, trace)."""
    now = now or datetime.now(timezone.utc)
    hand_now = datetime.now(timezone.utc)  # the rover side validates on the real clock: fixture times are taken now
    tgt = demo["observation_gate"]["target"]
    req = _request_from(demo, now, sign=mode != "unsigned",
                        at=now - timedelta(seconds=400) if mode == "expired_record" else None)
    graph = f.FrameGraph([fx.transform(hand_now, not_before=hand_now - timedelta(hours=2),
                                       expires=hand_now - timedelta(hours=1))]
                         if mode == "expired_transform" else [fx.transform(hand_now)])
    inp = fx.synthetic_inputs(hand_now, ground_state=demo["coordinator"]["ground"]["G1"]["state"], graph=graph,
                              site_goal={"frame": tgt["map_frame"], "x_m": tgt["x_m"], "y_m": tgt["y_m"],
                                         "sigma_m": tgt["sigma_m"]},
                              localization=None if mode == "no_localization" else fx.localization(hand_now),
                              conversion_owner=conversion_owner)
    return req, rh.handoff(req, inp, rover_side)


def run_one(name: str, rover_side: rh.RoverSnapshot) -> dict:
    case = BATTERY[name]
    now = datetime.now(timezone.utc)
    demo = pd.run_scenario(case.get("demo", name), quiet=True, now=now, safety_policy="safety/4",
                           spec=case.get("spec"), keep_coordinator=True)
    coord = demo.pop("_coordinator", None)
    row = {"scenario": name, "agents": AGENTS, "demo_scenario": case.get("demo", "battery-only spec"),
           "demo_classification": demo["classification"], "detections": len(demo["detection"]["detections"]),
           "separation": (demo.get("coordinator") or {}).get("separation"), "handoff": None,
           "coordinator_final": coord.mission_state if coord else None, "commands": demo["commands_sent"]}
    mode = case.get("handoff")
    if mode and demo.get("execution_request"):
        req, trace = handoff_for(demo, rover_side, mode=mode, now=now)
        row["handoff"] = trace["classification"]
        row["handoff_first_block"] = next((f"{s['stage']}: {s['reasons'][:1]}" for s in trace["stages"]
                                           if s["status"] != "PASS"), None)
        row["commands"] += len(trace["commands"])
        # the coordinator receives the hand-off's structured outcome
        t = now + timedelta(seconds=6)  # within the drone reports' freshness (stale after 10 s)
        pre = trace["coordinator_events"][0]["reasons"]
        if mode == "no_localization":
            pre = pre + ["NO_POSITION_SOURCE: no accredited rover localization"]
        coord.handle({"type": "EXECUTOR_PRECONDITIONS", "source": "TEST_FIXTURE", "at": t, "reasons": pre})
        if trace["classification"] == "READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED":
            coord.handle({"type": "AUTHORIZATION", "source": "TEST_FIXTURE", "at": t + timedelta(seconds=1),
                          "authorization_record": req["authorization"], "request": req, "preconditions": pre})
        if case.get("after") == "EXECUTOR_REFUSED":
            coord.handle({"type": "EXECUTOR_FEEDBACK", "source": "TEST_FIXTURE", "at": t + timedelta(seconds=2),
                          "feedback_type": trace["coordinator_events"][1]["feedback_type"]})
        if case.get("after") == "STOP_UNCERTAIN":
            coord.handle({"type": "EXECUTOR_FEEDBACK", "source": "TEST_FIXTURE", "at": t + timedelta(seconds=2),
                          "feedback_type": si.feedback_type("STOP_REQUESTED_NO_STANDSTILL_OBSERVED")})
        row["coordinator_final"] = coord.mission_state
        row["ground_final"] = coord.states()["G1"]["state"]
    exp = case["expect"]
    checks = {"demo": demo["classification"] == exp["demo"], "no_command": row["commands"] == 0}
    if "handoff" in exp:
        checks["handoff"] = row["handoff"] == exp["handoff"]
    if "coordinator" in exp:
        checks["coordinator"] = row["coordinator_final"] == exp["coordinator"]
    if "ground" in exp:
        checks["ground"] = row.get("ground_final") == exp["ground"]
    if "separation" in exp:
        checks["separation"] = row["separation"] == exp["separation"]
    if "detections" in exp:
        checks["detections"] = row["detections"] == exp["detections"]
    row.update(expected=exp, checks=checks, as_expected=all(checks.values()))
    return row


def run_all(snapshot: Path | None = None, *, reviewed: bool = False) -> list[dict]:
    """Every battery mission through the rover side: this repository's rover code by default, or a historical
    snapshot (``snapshot``) to reproduce sealed evidence."""
    with rh.rover_contract(snapshot, reviewed=reviewed) as rover_side:
        return [run_one(name, rover_side) for name in BATTERY]


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--snapshot", type=Path, help="historical pinned rover revision extracted here (to reproduce sealed "
                                                 "evidence); default: this repository's rover code, imported in-process")
    a.add_argument("--out", type=Path, help="new directory for sealed evidence")
    a.add_argument("--reviewed", action="store_true", help="the rover's commit + its protected review patch (in the snapshot)")
    args = a.parse_args(argv)
    if args.reviewed and args.snapshot is None:
        a.error("--reviewed applies only to a historical --snapshot")
    rows = run_all(args.snapshot, reviewed=args.reviewed)
    for r in rows:
        print(f"{'OK ' if r['as_expected'] else 'BAD'} {r['scenario']:40s} {r['demo_classification']:52s} "
              f"handoff={r['handoff']} coordinator={r['coordinator_final']} commands={r['commands']}")
    if args.out:
        args.out.mkdir(parents=True, exist_ok=False)
        if args.snapshot is None:
            from multiagent import rover_contract_local as rl
            source = {"rover_contract": rl.provenance()}
        else:
            source = {"rover_commit": rh.ROVER_CONTRACT_COMMIT, "rover_contract_sha256": rh.contract_digest()}
        summary = {"schema": "tfg.multiagent.integration-battery/1", "agents": AGENTS, **source,
                   "all_as_expected": all(r["as_expected"] for r in rows),
                   "no_command_anywhere": all(r["commands"] == 0 for r in rows), "rows": rows}
        (args.out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True, default=str) + "\n")
        with (args.out / "SHA256SUMS").open("w") as sums:
            sums.write(f"{hashlib.sha256((args.out / 'summary.json').read_bytes()).hexdigest()}  ./summary.json\n")
    return 0 if all(r["as_expected"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
