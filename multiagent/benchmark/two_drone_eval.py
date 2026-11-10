"""Offline evaluation of the multi-agent -> Hermes -> two-drone (H2) integration, sealed in a NEW directory.

Inputs: the sealed M4c-r1 plan (read-only), the phase-A plans of the 17 precision-demo scenarios (scripted agents,
OFFLINE_DETERMINISTIC), declared negative mutations, declared camera cases (SYNTHETIC images), and the end-to-end demo.
No model is called, nothing is executed, nothing is published.

  python -m multiagent.benchmark.two_drone_eval --out <new dir> [--rover-snapshot <dir> --rover-reviewed]
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SEALED = ROOT / "multiagent/benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9/demo/phase_b_proposal.json"
STATEMENT = "TEST_FIXTURE: offline evaluation statement; not an operator authorization"


def _mutations(sealed: dict) -> dict:
    def a(p, vid):
        return next(t for t in p["aerial"]["proposals"] if t["vehicle_id"] == vid)
    out = {}
    p = copy.deepcopy(sealed); a(p, "drone_01").update(objective_ids=["A2"], poi_sequence=["POI_3"]); out["duplicate_objective"] = p
    p = copy.deepcopy(sealed); p["brief"]["altitude_m"] = 500.0; out["altitude_beyond_site_limit"] = p
    p = copy.deepcopy(sealed); a(p, "drone_01").update(objective_ids=["A2"], poi_sequence=["POI_3"])
    a(p, "drone_02").update(objective_ids=["A1"], poi_sequence=["POI_1"]); out["sensor_not_available"] = p
    p = copy.deepcopy(sealed); p["template"]["dependencies"].append(
        {"task_id": "GROUND_rover_01", "after": "AIR_drone_09", "condition": "COMPLETED"}); out["unmet_dependency"] = p
    p = copy.deepcopy(sealed); a(p, "drone_02")["mission_sha256"] = "0" * 64; out["modified_after_validation"] = p
    p = copy.deepcopy(sealed); a(p, "drone_01")["start_delay_s"] = 0.0; out["schedule_inconsistent"] = p
    p = copy.deepcopy(sealed); p["status"] = "NEEDS_CLARIFICATION"; out["not_planned"] = p
    return out


def evaluate(out: Path, rover_snapshot: Path | None = None, reviewed: bool = False) -> dict:
    from multiagent import (drone_execution_bridge as db, drone_schedule as ds, hermes_mission_adapter as ha,
                            integrated_mission as im, precision_demo as pd, two_drone_demo as tdd)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    ctx = im.load_context(im.CONTEXT)
    site, fleet = im._site_fleet(ctx)
    sealed = json.loads(SEALED.read_text())
    launch = ROOT / "simulation/ros2_gazebo/launch/tfg_demo_2drones.launch.py"
    spawn = ds.launch_spawn_positions(launch)
    rows = []

    def case(name, kind, proposal, context, s, f, source, cancelled=False):
        a = ha.adapt_proposal(proposal, context=context, site=s, fleet=f, source=source, cancelled=cancelled)
        row = {"case": name, "kind": kind, "adapter": a["status"], "findings": sorted({x["kind"] for x in a["findings"]}),
               "drones": len(a["drones"]), "identical_rebuild": all(d.get("mission_sha256") == d["recorded_mission_sha256"]
                                                                     for d in a["drones"] if d.get("mission_sha256")),
               "commands": len(a["commands"])}
        if a["status"] == "PLANNING_VALID":
            plans = ds.plans_from_adapter(a)
            pol = context.separation_policy
            rep = ds.reproduce_deconfliction(plans, pol)
            sitl = ds.sitl_effective_deconfliction(plans, spawn, pol) if len(plans) > 1 else None
            row.update(separation=rep["status"], initial_conflicts=len(rep["initial_conflicts"]),
                       delays={v: s_["start_delay_s"] for v, s_ in rep["schedule"].items()},
                       sitl_delays=None if sitl is None else {v: s_["start_delay_s"] for v, s_ in sitl["schedule"].items()})
            with tempfile.TemporaryDirectory() as tmp:
                pend = db.request_execution(a, mission_dir=Path(tmp) / "p", request_key=f"eval-{name}")
                ready = db.request_execution(a, mission_dir=Path(tmp) / "r", request_key=f"eval-{name}",
                                             authorization_statement=STATEMENT)
            row.update(request_without_statement=pend["status"], request_with_fixture_statement=ready["status"],
                       submitted=pend["submitted"] or ready["submitted"],
                       realization=(ready.get("execution_path") or {}).get("realization"),
                       commands=row["commands"] + len(pend["commands"]) + len(ready["commands"]))
        rows.append(row)
    src = {"kind": "REPLAY_OF_SEALED_RUN", "agents_recorded_as": "REAL_LOCAL_LLM", "new_llm_calls": 0}
    case("m4c_r1_sealed_plan", "REPLAY", sealed, ctx, site, fleet, src)
    for name, p in _mutations(sealed).items():
        case(name, "NEGATIVE_MUTATION", p, ctx, site, fleet, src)
    case("cancelled", "NEGATIVE_MUTATION", sealed, ctx, site, fleet, src, cancelled=True)
    case("no_georeference", "NEGATIVE_MUTATION", sealed, ctx, site.model_copy(update={"geo_reference": None}), fleet, src)
    for name, spec in pd.SCENARIOS.items():
        bundle = im.plan_phase_a(pd.CONFIG, text=spec.get("text", pd.INTEGRATED_TEXT), safety_policy="safety/4")
        case(f"scenario_{name}", "SCRIPTED_AGENTS", bundle["phase_a"]["proposal"], bundle["context"], bundle["site"],
             bundle["fleet"], {"kind": "LIVE", "agents": "OFFLINE_DETERMINISTIC"})
    # camera cases (the same declared cases as tests/test_multiagent_camera_observation.py)
    cam_rows = _camera_cases()
    demo = {}
    for label, replay in (("scripted", False), ("replay_m4c_r1", True)):
        r = tdd.run(replay_plan=replay, rover_snapshot=rover_snapshot, reviewed=reviewed, quiet=True)
        demo[label] = {"status": r["status"], "commands": r["commands"], "plan_source": r.get("plan_source"),
                       "rover": r["steps"].get("rover"), "second_drone": (r["steps"].get("schedule") or {}).get(
                           "second_decision"), "observation": (r.get("observation") or {}).get("status")}
    two = [r for r in rows if r.get("delays") and len(r["delays"]) == 2]
    metrics = {
        "missions_transformed_to_hermes": sum(r["drones"] for r in rows if r["adapter"] == "PLANNING_VALID"),
        "plans_planning_valid": sum(r["adapter"] == "PLANNING_VALID" for r in rows),
        "plans_rejected_or_pending": sum(r["adapter"] != "PLANNING_VALID" for r in rows),
        "rejection_kinds": dict(Counter(k for r in rows for k in r["findings"])),
        "two_drone_plans": len(two),
        "plans_with_initial_conflicts": sum(r["initial_conflicts"] > 0 for r in two),
        "delays_introduced_s": sorted({d for r in two for d in r["delays"].values() if d > 0}),
        "sitl_geometry_same_delays": all(r["delays"] == r["sitl_delays"] for r in two),
        "unmet_dependencies": sum("UNMET_DEPENDENCY" in r["findings"] for r in rows),
        "requests_pending_without_statement": sum(r.get("request_without_statement") == "PENDING_AUTHORIZATION"
                                                  for r in rows),
        "requests_submitted": sum(bool(r.get("submitted")) for r in rows),
        "observations_valid": sum(c["status"] == "OBSERVED" for c in cam_rows),
        "observations_refused": sum(c["status"] == "REFUSED" for c in cam_rows),
        "observation_refusal_kinds": dict(Counter(c["reason"] for c in cam_rows if c["status"] == "REFUSED")),
        "rover_objectives_assigned": sum(1 for d in demo.values() if (d["rover"] or {}).get("proposal") ==
                                         "PROPOSED_PENDING_AUTHORIZATION"),
        "rover_requests_blocked": sum(1 for d in demo.values() if (d["rover"] or {}).get("request_problems")),
        "commands": sum(r["commands"] for r in rows) + sum(d["commands"] for d in demo.values()),
    }
    summary = {"schema": "tfg.multiagent.two-drone-eval/1", "data_kinds": ["REPLAY of REAL_LOCAL_LLM (sealed)",
               "OFFLINE_DETERMINISTIC agents", "SYNTHETIC images", "TEST_FIXTURE events and statements"],
               "not_done": ["no model call", "no SITL/Gazebo", "no vehicle", "no submission", "no Opik"],
               "metrics": metrics, "spawn_xy": spawn}
    (out / "plans.json").write_text(json.dumps(rows, indent=1, sort_keys=True, default=str))
    (out / "camera.json").write_text(json.dumps(cam_rows, indent=1, sort_keys=True, default=str))
    (out / "demo.json").write_text(json.dumps(demo, indent=1, sort_keys=True, default=str))
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True, default=str))
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.relative_to(out)}\n"
                                            for p in files))
    return summary


def _camera_cases() -> list:
    from datetime import datetime, timezone
    from multiagent import camera_observation as co, geometry, integrated_mission as im, perception, synthetic_scenes
    ctx = im.load_context(im.CONTEXT)
    site, fleet = im._site_fleet(ctx)
    frame = site.local_frame.frame_id
    cam = synthetic_scenes.default_camera() | {"camera_id": "cam_down_fixture"}
    pol = perception.Policy(allow_fixtures=True, allow_ground_plane=True)
    now = datetime.now(timezone.utc)
    poi = site.point("POI_3")

    def scene(color="red"):
        return synthetic_scenes.render({"seed": 11, "camera": cam, "height_m": 10.0, "background": "grass", "noise": 8,
                                        "cards": [{"color": color, "center_px": [190, 120], "angle_deg": 18,
                                                   "size_m": [0.5, 0.35]}]})

    def rig(vehicle="drone_02", dt=0.0, **kw):
        ext, pose = geometry.virtual_rig(vehicle, cam, position_m=(poi.x_m - 1.0, poi.y_m, 10.0),
                                         stamp_utc=now + timedelta(seconds=dt), site_frame=frame)
        return ext, {**pose, "accredited": True, **kw}
    info = {"header": {"frame_id": "cam_down_fixture_optical"}, "width": cam["width_px"], "height": cam["height_px"],
            "k": [cam["fx"], 0, cam["cx"], 0, cam["fy"], cam["cy"], 0, 0, 1], "d": [], "calibration_status": "DECLARED_VIRTUAL"}
    cases = {"valid": {}, "uncalibrated": {"camera_info": {**info, "k": []}},
             "virtual_camera_operational": {"mode": "OPERATIONAL"}, "pose_not_accredited": {"pose": rig(accredited=False)[1]},
             "image_stale": {"image_dt": -5.0, "now_dt": 0.0}, "desynchronised": {"pose": rig(dt=0.5)[1]},
             "other_drone": {"pose": rig(vehicle="drone_01")[1]}, "frame_incompatible": {"frame": "cam_front_optical"},
             "ambiguous": {"img": scene("orange")}, "uncertainty_too_high": {"pose": rig(position_sigma_m=0.6)[1]},
             "cancelled": {"cancelled": True}}
    rows = []
    for name, kw in cases.items():
        img, manifest = kw.get("img") or scene()
        r = co.observe(image=img, image_stamp=now + timedelta(seconds=kw.get("image_dt", 0.0)),
                       image_frame_id=kw.get("frame", "cam_down_fixture_optical"), camera_info=kw.get("camera_info", info),
                       pose=kw.get("pose") or rig()[1], now=now + timedelta(seconds=kw.get("now_dt", 0.5)),
                       cfg=co.CameraConfig("cam_down_fixture", "drone_02", "cam_down_fixture_optical", rig()[0]),
                       state=co.AdapterState(), site=site, context=ctx, fleet=fleet, policy=pol, camera_ids=im.CAMERAS,
                       mission_cancelled=kw.get("cancelled", False), mode=kw.get("mode", "OFFLINE_TEST"),
                       observation_id=f"eval-{name}", ingestion_source="TEST_FIXTURE_INGESTION",
                       image_source={"kind": "SYNTHETIC_TEST", "manifest_sha256": manifest["image_sha256"]})
        rows.append({"case": name, "status": r["status"], "reason": (r["reasons"] or [""])[0].split(":")[0],
                     "target": r.get("target_site_frame")})
    return rows


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--rover-snapshot", type=Path)
    a.add_argument("--rover-reviewed", action="store_true")
    args = a.parse_args(argv)
    s = evaluate(args.out, args.rover_snapshot, args.rover_reviewed)
    print(json.dumps(s["metrics"], indent=1, sort_keys=True))
    return 0 if s["metrics"]["commands"] == 0 and s["metrics"]["requests_submitted"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
