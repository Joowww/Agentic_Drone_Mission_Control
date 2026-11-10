"""Milestone record of a sealed integrated pilot (M4c-r1): verified, read-only, written apart from the evidence.

    python -m multiagent.benchmark.milestone --results <sealed results dir> --out <new dir>

Reads the sealed files, verifies every SHA256SUMS, the manifest against its registration commit, and each
exchange's prompt/reply digests; then extracts the 20 items of the record and the plan-quality checks. Never calls a
model, never rewrites a sealed byte; what the evidence does not contain is reported as NOT_RECORDED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from multiagent.benchmark import run as bench

SCHEMA = "tfg.multiagent.milestone-record/1"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _load(d: Path, name: str):
    return json.loads((d / name).read_text())


def verify(results: Path) -> dict:
    results = Path(results)
    seals = {}
    for sums in sorted(results.rglob("SHA256SUMS")):
        bad = []
        for line in sums.read_text().splitlines():
            digest, name = line.split("  ", 1)
            path = sums.parent / name.removeprefix("./")
            if not path.is_file() or _sha(path.read_bytes()) != digest:
                bad.append(name)
        seals[str(sums.parent.relative_to(results)) or "."] = bad or "OK"
    summary, manifest_bytes = _load(results, "summary.json"), (results / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    reg = manifest.get("registered_commit_hint")
    pilot_path = f"multiagent/benchmark/pilots/{manifest['pilot_id']}.json"
    from multiagent import historical_identifiers as hist
    registration = hist.PILOT_MANIFEST_REGISTRATIONS.get(manifest["pilot_id"])
    if registration is None:
        # Fixed abbreviation: git's automatic length depends on the size of the clone; the sealed record uses 9.
        committed = subprocess.run(["git", "log", "--abbrev=9", "--format=%h", "--diff-filter=A", "--", pilot_path],
                                   cwd=bench.ROOT, capture_output=True, text=True).stdout.split()
        registration = committed[-1] if committed else reg
    at_registration = subprocess.run(["git", "show", f"{registration}:{pilot_path}"], cwd=bench.ROOT,
                                     capture_output=True).stdout if registration else b""
    exchanges = [json.loads(l) for l in (results / "exchanges.jsonl").read_text().splitlines()]
    digests = [{"n": e["n"], "role": e["role"],
                "prompt_sha256_ok": _sha(e["prompt"].encode()) == e["prompt_sha256"],
                "reply_sha256_ok": _sha(e["raw_reply"].encode()) == e["raw_reply_sha256"]} for e in exchanges]
    ok = all(v == "OK" for v in seals.values()) and _sha(manifest_bytes) == summary["manifest_sha256"] and \
        at_registration == manifest_bytes and all(d["prompt_sha256_ok"] and d["reply_sha256_ok"] for d in digests)
    return {"ok": ok, "seals": seals, "manifest_sha256": _sha(manifest_bytes),
            "manifest_equals_summary_digest": _sha(manifest_bytes) == summary["manifest_sha256"],
            "manifest_registration_commit": registration, "manifest_equals_registered": at_registration == manifest_bytes,
            "exchange_digests": digests}


def deconfliction_replay(results: Path) -> dict:
    """REPLAY with the deterministic code (no model): rebuild the recorded routes from the declared context, check
    they equal the sealed route_local, re-run the deconfliction and test every smaller delay on the declared grid."""
    from multiagent import integrated_mission as im
    from multiagent.agent_tools import _quiet
    from multiagent.deconfliction import conflicts_between, deconflict, timeline
    from multiagent.swarm import Objective, SwarmProblem, route_candidate
    pa = _load(Path(results) / "demo", "phase_a_proposal.json")
    ctx = im.load_context(im.CONTEXT)
    site, fleet = im._site_fleet(ctx)
    brief = _load(Path(results) / "demo", "result.json")["agent_records"]["supervisor"]["brief"]
    problem = SwarmProblem(site, fleet, ctx, [Objective(o["objective_id"], o["point_id"], o["required_sensor"])
                                              for o in brief["aerial_objectives"]], list(ctx.drones),
                           ctx.wind_speed_kmh, {}, None)
    plans, same_routes = {}, True
    for prop in pa["aerial"]["proposals"]:
        c = _quiet(route_candidate, problem, problem.drone(prop["vehicle_id"]), prop["poi_sequence"])
        same_routes &= [list(x) for x in c["route_local"]] == [list(x) for x in prop["route_local"]]
        plans[prop["vehicle_id"]] = {k: c[k] for k in ("route_local", "labels", "leg_minutes")}
    policy = ctx.separation_policy
    again = deconflict(plans, policy)
    recorded = pa["swarm_coordination"]["schedule"]
    delayed = max(recorded, key=lambda v: recorded[v]["start_delay_s"])
    first = next(v for v in recorded if v != delayed)
    other = timeline(first, **{k: plans[first][k] for k in ("route_local", "labels", "leg_minutes")}, policy=policy,
                     start_s=recorded[first]["start_delay_s"])
    smaller = {}
    steps = int(recorded[delayed]["start_delay_s"] // policy.start_delay_step_s)
    for k in range(steps):
        d = k * policy.start_delay_step_s
        segs = timeline(delayed, **{x: plans[delayed][x] for x in ("route_local", "labels", "leg_minutes")},
                        policy=policy, start_s=d)
        smaller[d] = len(conflicts_between(segs, other, policy))
    return {"kind": "REPLAY_WITH_DETERMINISTIC_CODE_NO_MODEL", "routes_equal_sealed": same_routes,
            "schedule_reproduced": {v: again["schedule"][v]["start_delay_s"] for v in again["schedule"]} ==
            {v: recorded[v]["start_delay_s"] for v in recorded},
            "grid_step_s": policy.start_delay_step_s, "delayed_vehicle": delayed,
            "conflicts_at_each_smaller_delay": smaller,
            "every_smaller_delay_conflicts": bool(smaller) and all(n > 0 for n in smaller.values())}


def plan_quality(results: Path) -> list[dict]:
    """Checks of the final plan, each with the evidence it reads. The model's assignment and the deterministic
    schedule are told apart."""
    results = Path(results)
    pa, pb, r = (_load(results / "demo", n) for n in ("phase_a_proposal.json", "phase_b_proposal.json", "result.json"))
    sc = pa["swarm_coordination"]
    alloc = pa["aerial"]["evidence"]["model_proposal_check"]["allocator"]
    model_assignment = alloc["rounds"][-1]["proposal"]["assignments"]
    final = {p["vehicle_id"]: p["objective_ids"] for p in pa["aerial"]["proposals"]}
    brief = r["agent_records"]["supervisor"]["brief"]
    objectives = {o["objective_id"] for o in brief["aerial_objectives"]}
    covered = {o for ids in final.values() for o in ids}
    deps = pb["template"]["dependencies"]
    ground = pb["ground"]["proposals"][0]
    req = r["execution_request"]

    def check(name, ok, evidence):
        return {"check": name, "ok": bool(ok), "evidence": evidence}
    return [
        check("separation conflict recorded", sc["initial_conflicts"] > 0 and
              pa["aerial"]["evidence"]["coordination"]["initial_conflicts"],
              f"{sc['initial_conflicts']} initial conflicts (e.g. take-off climbs 8.0 m apart, 8.5 m required)"),
        check("the delay clears every conflict (residual 0)",
              sc["status"] == "DECONFLICTED_BY_START_DELAY" and sc["residual_conflicts"] == 0,
              {"schedule": sc["schedule"], "delays_tried": pa["aerial"]["evidence"]["coordination"].get("delays_tried")}),
        check("the delay is the smallest on the declared grid (deterministic replay)",
              (lambda d: d["routes_equal_sealed"] and d["schedule_reproduced"] and d["every_smaller_delay_conflicts"])(
                  deconfliction_replay(results)), deconfliction_replay(results)),
        check("the conflict was resolved by the DETERMINISTIC validator, not by the model",
              alloc["rounds"][-1].get("separation") == "DECONFLICTED_BY_START_DELAY" and
              "start_delay" not in json.dumps(alloc["rounds"][-1]["proposal"]),
              "the model proposed only the assignment; the start delay comes from deconfliction"),
        check("the final assignment is the model's", final == model_assignment and
              pa["aerial"]["evidence"]["allocation_source"] == "MODEL_PROPOSAL_CHECKED", final),
        check("no objective missing", covered == objectives and not pa["aerial"]["incompatible"],
              {"objectives": sorted(objectives), "covered": sorted(covered)}),
        check("dependencies kept", {(d["after"], d["condition"]) for d in deps} >=
              {("AIR_drone_02", "POI_REACHED"), ("AIR_drone_01", "COMPLETED")} and req["dependencies"], deps),
        check("limits stay explicit (none invented)", req["navigation_plan"] is None and
              r["request_problems"] == ["NO_NAVIGATION_PLAN: speed and timeout were not set by a human"],
              "speed and timeout absent until a human sets them"),
        check("the supervisor's brief kept the operator's information", brief["drones"] == [] and
              brief["battery_percent"] == {} and brief["rover"] == "rover_01" and
              r["agent_records"]["supervisor"]["provenance"]["status"] == "VALID",
              {"aerial": [(o["point_id"], o["required_sensor"]) for o in brief["aerial_objectives"]],
               "ground": brief["ground_objectives"]}),
        check("target handed to the rover agent", r["observation_gate"]["target"]["matched_poi"] == "POI_3" and
              ground["target_point"] == "POI_3" and ground["after_aerial_point"] == "POI_3" and
              r["agent_records"]["rover_phase_b"]["agreement"] == "AGREES",
              {"gate": r["observation_gate"]["target"], "ground_task": {k: ground[k] for k in
                                                                      ("task_id", "target_point", "after_aerial_point", "state")}}),
        check("zero commands", r["commands_sent"] == 0 and pa["commands_sent"] == 0 and pb["commands_sent"] == 0 and
              pa["vehicles_contacted"] == 0 and pb["vehicles_contacted"] == 0 and r["physical_effect"] is False and
              ground["ros2_commands_sent"] == 0, "commands_sent, vehicles_contacted, physical_effect"),
    ]


def record(results: Path) -> dict:
    results = Path(results).resolve()
    summary, manifest = _load(results, "summary.json"), _load(results, "manifest.json")
    exchanges = [json.loads(l) for l in (results / "exchanges.jsonl").read_text().splitlines()]
    r = _load(results / "demo", "result.json")
    pa, pb = _load(results / "demo", "phase_a_proposal.json"), _load(results / "demo", "phase_b_proposal.json")
    rec = r["agent_records"]
    alloc = pa["aerial"]["evidence"]["model_proposal_check"]["allocator"]
    review_b = pb["ground"]["evidence"]["llm_review"]
    latency = {e["n"]: e["latency_s"] for e in summary["budget"]["log"]}
    replay = results / "analysis/replay.json"
    rover_a_tool = (json.loads(replay.read_text()).get("phase_a_rover_tool_replay") if replay.is_file() else None)
    calls = [{"n": e["n"], "role": e["role"], "at_utc": e["at_utc"], "prompt_sha256": e["prompt_sha256"],
              "prompt": e["prompt"], "raw_reply": e["raw_reply"], "raw_reply_sha256": e["raw_reply_sha256"],
              "finish_reason": e["finish_reason"], "tokens": e["usage"], "latency_s": latency.get(e["n"])}
             for e in exchanges]
    return {
        "schema": SCHEMA, "milestone": "first integrated mission with real Qwen in the three agent roles",
        "source": str(results.relative_to(bench.ROOT)), "verification": verify(results),
        "01_date_utc": {"started": summary["started_utc"], "finished": summary["finished_utc"]},
        "02_commit": {"run": summary["commit"], "manifest": manifest["pilot_id"]},
        "03_model": manifest["model"]["candidate"], "04_digest": manifest["model"]["digest"],
        "05_prompts": {f"call_{c['n']}_{c['role']}": {"sha256": c["prompt_sha256"], "text": c["prompt"]} for c in calls},
        "06_configuration": {"agents": manifest["agents"], "generation": manifest["generation"],
                             "safety_policy": manifest["safety_policy"], "budget": manifest["budget"],
                             "isolation_profile": manifest.get("isolation_profile")},
        "07_scenario": {"text": manifest["dataset"]["text"], "case": manifest["dataset"]["case"],
                        "image": "SYNTHETIC_TEST (demo/scene_manifest.json)", "events": "TEST_FIXTURE"},
        "08_raw_replies": {f"call_{c['n']}_{c['role']}": c["raw_reply"] for c in calls},
        "09_tools_invoked": {
            "drone_swarm_agent": alloc.get("tool_log"),
            "rover_agent_phase_a": {"requested_in_reply": json.loads(exchanges[2]["raw_reply"]).get("verify"),
                                    "tool_log": "NOT_RECORDED in the run (defect fixed in a516dfc77)"},
            "rover_agent_phase_b": review_b.get("tool_log")},
        "10_tool_results": {
            "drone_swarm_agent": [{"tool": v["tool"], "status": v["status"], "data": v["data"]}
                                  for rd in alloc["rounds"] for v in rd.get("verifications") or []],
            "rover_agent_phase_a": {"NOT_RECORDED": True, "labelled_replay": rover_a_tool},
            "rover_agent_phase_b": [{"tool": v["tool"], "status": v["status"], "data": v["data"]}
                                    for v in review_b.get("verifications") or []]},
        "11_deterministic_validators": {
            "provenance": {k: rec["supervisor"]["provenance"][k] for k in ("status", "llm_provenance_clean", "corrections")},
            "safety_policy": manifest["safety_policy"], "supervisor_phase_a": rec["supervisor"]["status"],
            "drone_gate": {"accepted": alloc["accepted_by_gate"], "separation": alloc["rounds"][-1].get("separation"),
                           "findings": alloc["rounds"][-1].get("findings")},
            "deconfliction": pa["swarm_coordination"],
            "rover_gate_phase_a": rec["rover_phase_a"]["accepted_by_gate"],
            "rover_gate_phase_b": {"accepted": rec["rover_phase_b"]["accepted_by_gate"],
                                   "agreement_with_deterministic_agent": rec["rover_phase_b"]["agreement"]},
            "perception_gate": r["observation_gate"], "coordinator": r["coordinator"]["mission"]},
        "12_first_proposals": {"drone": alloc["decision_record"]["llm_proposals"][0]["proposal"],
                               "rover_phase_a": rec["rover_phase_a"]["decision_record"]["llm_proposals"][0]["proposal"],
                               "rover_phase_b": rec["rover_phase_b"]["decision_record"]["llm_proposals"][0]["proposal"]},
        "13_revisions": {"drone": len(alloc["rounds"]) - 1,
                         "rover_phase_a": len(rec["rover_phase_a"]["decision_record"]["llm_proposals"]) - 1,
                         "rover_phase_b": len(rec["rover_phase_b"]["decision_record"]["llm_proposals"]) - 1},
        "14_final_plan": {"aerial": [{k: p[k] for k in ("task_id", "vehicle_id", "poi_sequence", "objective_ids",
                                                        "start_delay_s")} for p in pa["aerial"]["proposals"]],
                          "ground": [{k: g[k] for k in ("task_id", "target_point", "after_aerial_point", "state")}
                                     for g in pb["ground"]["proposals"]],
                          "dependencies": pb["template"]["dependencies"]},
        "15_tokens": {f"call_{c['n']}_{c['role']}": c["tokens"] for c in calls},
        "16_latency_s": {f"call_{c['n']}_{c['role']}": c["latency_s"] for c in calls},
        "17_errors": {"parse_errors": [rec["supervisor"].get("parse_error")] + [
            p.get("parse_error") for p in alloc["rounds"]], "finish_reasons": [c["finish_reason"] for c in calls]},
        "18_fallbacks": {"criteria": summary["criteria"]["fallbacks"], "role_outcomes": summary["role_outcomes"]},
        "19_execution_state": {"classification": r["classification"], "status_ladder": r["status_ladder"],
                               "request_state": r["execution_request"]["state"],
                               "request_problems": r["request_problems"], "executor": r["executor"]},
        "20_zero_commands": {"result.commands_sent": r["commands_sent"], "summary.commands_sent": summary["commands_sent"],
                             "phase_a.vehicles_contacted": pa["vehicles_contacted"],
                             "phase_b.vehicles_contacted": pb["vehicles_contacted"],
                             "physical_effect": r["physical_effect"],
                             "ground.ros2_commands_sent": [g["ros2_commands_sent"] for g in pb["ground"]["proposals"]]},
        "plan_quality": plan_quality(results),
    }


def write(results: Path, out: Path) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    rec = record(results)
    (out / "milestone.json").write_text(json.dumps(rec, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return rec


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--results", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    args = a.parse_args(argv)
    rec = write(args.results, args.out)
    print(json.dumps({"verified": rec["verification"]["ok"],
                      "plan_quality": {q["check"]: q["ok"] for q in rec["plan_quality"]}}, indent=1))
    return 0 if rec["verification"]["ok"] and all(q["ok"] for q in rec["plan_quality"]) else 1


if __name__ == "__main__":
    sys.exit(main())
