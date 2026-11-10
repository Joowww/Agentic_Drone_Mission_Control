"""Sealed evidence of the ROVER_ADAPTER integration round (07/11/2026, afternoon), in a NEW directory.

Offline only: the rover's code from immutable snapshots, no model, no simulator, no vehicle, no Opik. Reuses the previous
generator's sections (hand-off traces, battery, scenarios, mission inputs, junit) and adds: the contract comparison
between the two snapshots, the final ROVER_ADAPTER contract (synthetic case, negatives in both conversion modes,
double-conversion guard, M4c-r1 read-only), the .plan semantics round trip, the SITL topic table, the smoke results
and the git relations.

  python -m multiagent.benchmark.rover_adapter_evidence --out <new dir> --scratch <dir> --junit <xml> --smoke <json>
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from multiagent import rover_goal_contract as gc, rover_handoff as rh, rover_handoff_fixtures as fx
from multiagent.benchmark import integration_v2_evidence as v2e

ROOT = Path(__file__).resolve().parents[2]
NEGATIVES = ("transform_not_accredited", "pose_of_another_rover", "boot_changed", "uncertainty_too_high",
             "localization_stale", "localization_lost", "observation_expired", "observation_withdrawn",
             "aerial_dependency_failed", "authorization_revoked", "scope_of_another_plan", "goal_already_in_rover_frame",
             "owner_not_declared")


def _git(*a) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def contract_comparison(scratch: Path) -> dict:
    out = {}
    for label, reviewed in (("committed", False), ("reviewed", True)):
        snap = rh.ensure_snapshot(scratch / label, reviewed=reviewed)
        out[label] = {"tag": (snap / ".snapshot_commit").read_text().split()[0],
                      "files": {f: hashlib.sha256((snap / f).read_bytes()).hexdigest() for f in rh.CONTRACT_FILES},
                      "adapter_present": (snap / "tools/rover_payload_executor_adapter.py").is_file()}
    out["differing_files"] = sorted(f for f in rh.CONTRACT_FILES
                                    if out["committed"]["files"][f] != out["reviewed"]["files"][f])
    return out


def _negative(name, t):
    loc = fx.localization
    from multiagent import frames2d as f
    return {
        "transform_not_accredited": ({}, dict(graph=f.FrameGraph([fx.transform(t, accredited=False, source_sha256="")]))),
        "pose_of_another_rover": ({}, dict(localization=loc(t, vehicle_id="rover_02"))),
        "boot_changed": ({}, dict(localization=loc(t, boot_id="rover-boot-2"))),
        "uncertainty_too_high": ({}, dict(localization=loc(t, sigma_m=0.6))),
        "localization_stale": ({}, dict(localization=loc(t, observed_at=t - timedelta(seconds=30)))),
        "localization_lost": ({}, dict(localization=None)),
        "observation_expired": ({}, dict(ground_state="BLOCKED_OBSERVATION_EXPIRED")),
        "observation_withdrawn": ({}, dict(ground_state="BLOCKED_TARGET_WITHDRAWN")),
        "aerial_dependency_failed": ({}, dict(ground_state="BLOCKED_DEPENDENCY_LOST")),
        "authorization_revoked": ({}, dict(receipt_provider=rh.fixture_receipt_provider("OFFLINE_TEST",
                                                                                         revocation_status="REVOKED"))),
        "scope_of_another_plan": ({"signed_limits": {"max_speed_mps": 1.0, "timeout_s": 60.0}}, {}),
        "goal_already_in_rover_frame": ({}, dict(site_goal={"frame": "odom", "x_m": 5.5, "y_m": -7.0, "sigma_m": 0.12})),
        "owner_not_declared": ({}, dict(conversion_owner=None)),
    }[name]


def adapter_cases(scratch: Path, out: Path) -> dict:
    out.mkdir()
    rows = {}
    for label, reviewed in (("committed", False), ("reviewed", True)):
        with rh.RoverSnapshot(rh.ensure_snapshot(scratch / label, reviewed=reviewed)) as rover_side:
            def run(name, owner, req_kw=None, **kw):
                t = datetime.now(timezone.utc)
                inp = fx.synthetic_inputs(t, conversion_owner=owner, **kw)
                tr = rh.handoff(fx.request(t, **(req_kw or {})), inp, rover_side)
                (out / f"{label}__{owner}__{name}.json").write_text(json.dumps(tr, indent=1, sort_keys=True, default=str))
                return tr
            for owner in ("ROVER_ADAPTER", "MULTIAGENT_FRAMES2D"):
                tr = run("synthetic_complete", owner)
                rec = (tr.get("envelope") or {}).get("goal_handoff") or {}
                rows[f"{label}/{owner}/synthetic_complete"] = {
                    "classification": tr["classification"], "commands": len(tr["commands"]),
                    "applied_conversions": len(rec.get("applied_conversions") or []),
                    "transform_status": (rec.get("transform_required") or {}).get("status"),
                    "conversion_problems": gc.conversion_problems(rec) if rec else None}
                for name in NEGATIVES:
                    req_kw, kw = _negative(name, datetime.now(timezone.utc))
                    if name == "owner_not_declared" and owner == "MULTIAGENT_FRAMES2D":
                        continue
                    tr = run(name, owner if "conversion_owner" not in kw else kw.pop("conversion_owner"), req_kw, **kw)
                    rows[f"{label}/{owner}/{name}"] = {"classification": tr["classification"],
                                                       "commands": len(tr["commands"]),
                                                       "categories": tr["error_categories"],
                                                       "codes": sorted({e["code"] for e in tr["errors"]})}
            req, inp = fx.historical(datetime.now(timezone.utc))
            tr = rh.handoff(req, inp, rover_side)
            (out / f"{label}__M4c-r1_final_contract.json").write_text(json.dumps(tr, indent=1, sort_keys=True, default=str))
            rows[f"{label}/M4c-r1"] = {"classification": tr["classification"], "commands": len(tr["commands"]),
                                       "categories": tr["error_categories"], "provenance": tr["provenance"]}
    return rows


def plan_semantics(out: Path) -> dict:
    from multiagent import integrated_mission as im, plan_semantics as ps
    from models.qgc_import import QGroundControlImportContext
    out.mkdir()
    ctx = im.load_context(im.CONTEXT)
    site, _ = im._site_fleet(ctx)
    ic = QGroundControlImportContext(battery_percent=90, battery_consumption_percent_per_minute=1.0, wind_speed_kmh=0,
                                     wind_direction_from_deg=0, minimum_battery_reserve_percent=20,
                                     maximum_wind_speed_kmh=30, maximum_altitude_m=50)
    plan = ROOT / "multiagent/fixtures/plans/red_target_aerial.plan"
    manifest = plan.with_name(plan.name + ".semantics.json")
    shutil.copyfile(plan, out / plan.name)
    shutil.copyfile(manifest, out / manifest.name)
    m = json.loads(manifest.read_text())
    with_m = ps.import_with_manifest(plan, manifest, site=site, context=ctx, import_context=ic)
    without = ps.import_with_manifest(plan, None, site=site, context=ctx, import_context=ic)
    from types import SimpleNamespace as NS
    sensors = {w["waypoint_id"]: w["sensor"] for w in m["waypoints"]}
    # the intended mission as the manifest records it (semantic_loss needs the ordered waypoint ids and actions)
    intended = NS(route=NS(waypoints=[NS(waypoint_id=w["waypoint_id"], action=w["action"]) for w in m["waypoints"]]))
    res = {"not_representable_in_plan": m["not_representable_in_plan"],
           "with_manifest": {"semantics": with_m["semantics"]["status"], "status": with_m["status"],
                             "loss": ps.semantic_loss(intended, sensors, with_m)},
           "without_manifest": {"semantics": without["semantics"]["status"], "status": without["status"],
                                "loss": ps.semantic_loss(intended, sensors, without)}}
    (out / "round_trip.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=str))
    return {"with_manifest_loss": len(res["with_manifest"]["loss"]),
            "without_manifest_loss": len(res["without_manifest"]["loss"]),
            "not_representable_rows": len(res["not_representable_in_plan"])}


def sitl_topics() -> dict:
    from multiagent import sitl_events as se
    return {"namespaces": se.KNOWN_NAMESPACES, "ingestible_statuses": list(se.INGESTIBLE),
            "topics": {t: {"vehicle_id": s.vehicle_id, "msg_type": s.msg_type, "status": s.status,
                           "direction": s.direction, "evidence": s.evidence}
                       for t, s in ((t, se.KNOWN_TOPICS.spec(t)) for t in se.KNOWN_TOPICS.topics)}}


def git_relations(revision: str = "HEAD") -> dict:
    """Relations of ``revision`` (HEAD by default) with main, the rover branch and the integrated source branches.

    The source branches are identified by their pinned tips (historical_identifiers.INTEGRATED_BRANCH_TIPS), not by
    branch names that may be absent or moved in a given clone; a tip whose object is absent is recorded as False."""
    from multiagent.historical_identifiers import INTEGRATED_BRANCH_TIPS
    head, rover_side = _git("rev-parse", revision), "2e206f1fa"
    mb = _git("merge-base", head, rover_side)
    rel = {"head": head, "main": _git("rev-parse", "main"), "rover_side": _git("rev-parse", rover_side), "merge_base_rover": mb,
           "ahead_of_main": int(_git("rev-list", "--count", f"main..{head}")),
           "rover_only_since_base": int(_git("rev-list", "--count", f"{head}..{rover_side}")),
           "ours_only_since_base": int(_git("rev-list", "--count", f"{rover_side}..{head}")),
           "files_changed_on_both_sides": sorted(set(_git("diff", "--name-only", mb, head).splitlines())
                                                 & set(_git("diff", "--name-only", mb, rover_side).splitlines()))}
    for b, tip in INTEGRATED_BRANCH_TIPS.items():
        rel[f"{b} ancestor of {revision}"] = subprocess.run(["git", "merge-base", "--is-ancestor", tip, head],
                                                            cwd=ROOT, capture_output=True).returncode == 0
    return rel


def generate(out: Path, scratch: Path, junit: Path, smoke: Path) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    scratch = Path(scratch)
    (out / "provenance.json").write_text(json.dumps(v2e.provenance(), indent=1, sort_keys=True))
    res = {"git": git_relations(), "contracts": contract_comparison(scratch)}
    (out / "git_relations.json").write_text(json.dumps(res["git"], indent=1, sort_keys=True))
    (out / "contract_comparison.json").write_text(json.dumps(res["contracts"], indent=1, sort_keys=True))
    res["adapter_cases"] = adapter_cases(scratch, out / "rover_adapter")
    (out / "rover_adapter_summary.json").write_text(json.dumps(res["adapter_cases"], indent=1, sort_keys=True,
                                                               default=str))
    for label, reviewed in (("committed", False), ("reviewed", True)):
        s = rh.write_evidence(out / f"handoff_{label}", scratch / label, reviewed=reviewed)
        res[f"handoff_{label}"] = {"all_as_expected": s["all_as_expected"], "no_command": s["no_command_anywhere"]}
    res["mission_inputs"] = v2e.mission_inputs(out / "mission_inputs")
    res["plan_semantics"] = plan_semantics(out / "plan_semantics")
    (out / "sitl_topics.json").write_text(json.dumps(sitl_topics(), indent=1, sort_keys=True))
    from multiagent import integration_battery as ib
    for label, reviewed in (("committed", False), ("reviewed", True)):
        rows = ib.run_all(scratch / label, reviewed=reviewed)
        (out / f"battery_{label}.json").write_text(json.dumps(rows, indent=1, sort_keys=True, default=str))
        res[f"battery_{label}"] = {"as_expected": sum(r["as_expected"] for r in rows), "missions": len(rows),
                                   "commands": sum(r["commands"] for r in rows)}
    for policy in ("safety/3", "safety/4"):
        rows = v2e.scenarios(policy)
        (out / f"scenarios_{policy.replace('/', '')}.json").write_text(json.dumps(rows, indent=1, sort_keys=True))
        res[f"scenarios_{policy}"] = {"as_expected": sum(r["as_expected"] for r in rows), "scenarios": len(rows),
                                      "commands": sum(r["commands"] for r in rows)}
    shutil.copyfile(junit, out / "pytest_multiagent.xml")
    shutil.copyfile(smoke, out / "integration_smoke.json")
    summary = {"schema": "tfg.multiagent.rover-adapter-evidence/1",
               "results": {k: v for k, v in res.items() if k != "adapter_cases"},
               "adapter_case_count": len(res["adapter_cases"]),
               "commands_anywhere": sum(r.get("commands", 0) for r in res["adapter_cases"].values())}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True, default=str))
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.relative_to(out)}\n"
                                            for p in files))
    return summary


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--scratch", type=Path, required=True)
    a.add_argument("--junit", type=Path, required=True)
    a.add_argument("--smoke", type=Path, required=True)
    args = a.parse_args(argv)
    s = generate(args.out, args.scratch, args.junit, args.smoke)
    print(json.dumps(s, indent=1, sort_keys=True, default=str))
    return 0 if s["commands_anywhere"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
