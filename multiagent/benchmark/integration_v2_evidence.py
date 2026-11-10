"""Sealed evidence of the Rover Agent <-> rover executor integration (v2 contract), generated into a NEW directory.

Everything runs offline against immutable rover snapshots (git archive of a pinned commit; the reviewed one adds its
protected review patch, sha256-verified, inside the snapshot only). No model is called, no simulator is started, no
vehicle exists, no command can be produced. Data kinds: TEST_FIXTURE, SYNTHETIC_SENSOR (rendered images), the sealed
M4c-r1 request read without modification, and Hermes' own .plan exporter/importer.

  python -m multiagent.benchmark.integration_v2_evidence --out <new dir> --scratch <scratch dir> [--junit <xml>]

Layout: provenance.json, handoff_committed/, handoff_reviewed/, handoff_extra.json (the rover ledger, conversion owner),
mission_inputs/ (QGC .plan round trip, foreign site, NL), battery_{committed,reviewed}.json (18 missions),
scenarios_safety3.json / scenarios_safety4.json (17 scenarios), summary.json, SHA256SUMS (every file, recursive).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from multiagent import integration_battery as ib, precision_demo as pd, rover_handoff as rh, rover_handoff_fixtures as fx

ROOT = Path(__file__).resolve().parents[2]


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n")


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def provenance() -> dict:
    return {"schema": "tfg.multiagent.integration-v2-evidence/1", "generated_utc": datetime.now(timezone.utc).isoformat(),
            "multiagent_commit": _git("rev-parse", "HEAD"), "multiagent_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "multiagent_tree_clean": _git("status", "--porcelain", "--", "multiagent", "tests") == "",
            "rover_committed": {"commit": rh.ROVER_CONTRACT_COMMIT, "contract_sha256": rh.contract_digest(rh.ROVER_CONTRACT_COMMIT)},
            "rover_reviewed": {**rh.REVIEWED, "contract_sha256_before_patch": rh.contract_digest(rh.REVIEWED["commit"])},
            "rover_working_tree": "never read for execution, never written (snapshots come from git objects)",
            "python": platform.python_version(),
            "data_kinds": ["TEST_FIXTURE", "SYNTHETIC_SENSOR", "sealed M4c-r1 request (read-only)", "Hermes .plan I/O"],
            "not_done": ["no LLM call", "no SITL/Gazebo", "no MAVLink", "no vehicle", "no Opik publication",
                         "no real authorization (fixture records only, refused in OPERATIONAL mode)"]}


def handoff_extra(snapshot: Path, ledger_dir: Path) -> dict:
    """Cases that need the reviewed snapshot (the rover's ledger) or a different conversion owner."""
    out = {}
    for label, reviewed in (("committed", False), ("reviewed", True)):
        with rh.RoverSnapshot(rh.ensure_snapshot(snapshot / label, reviewed=reviewed)) as rover_side:
            cases = {"conversion_owner_rover_adapter": {"conversion_owner": "ROVER_ADAPTER"}}
            if reviewed:
                cases["rover_ledger_fixture_grant"] = {
                    "receipt_provider": rh.rover_ledger_receipt_provider("OFFLINE_TEST", ledger_dir / "granted.json")}
                cases["rover_ledger_revoked_grant"] = {
                    "receipt_provider": rh.rover_ledger_receipt_provider("OFFLINE_TEST", ledger_dir / "revoked.json",
                                                                         revoke=True)}
            for name, kw in cases.items():
                now = datetime.now(timezone.utc)
                trace = rh.handoff(fx.request(now), fx.synthetic_inputs(now, snapshot_label=label, **kw), rover_side)
                st = {s["stage"]: s for s in trace["stages"]}
                out[f"{label}/{name}"] = {"classification": trace["classification"], "commands": trace["commands"],
                                          "rover_v2": {k: st["rover_v2"].get(k) for k in ("status", "reasons")},
                                          "conversion": st["frames"].get("conversion"),
                                          "executor_request": {k: st["executor_request"].get(k) for k in ("status", "reasons")}}
    return out


def mission_inputs(out: Path) -> dict:
    from inputs.qgroundcontrol_exporter import export_qgroundcontrol_plan
    from models.mission_definition import MissionDefinition
    from models.qgc_import import QGroundControlImportContext
    from planning.site_geometry import local_to_geo
    from multiagent import integrated_mission as im, mission_inputs as mi
    from multiagent.orchestrator import MissionOrchestrator
    from multiagent.tracing import Tracer
    out.mkdir()
    ctx = im.load_context(im.CONTEXT)
    site, _ = im._site_fleet(ctx)
    g = site.geo_reference
    ic = QGroundControlImportContext(battery_percent=90, battery_consumption_percent_per_minute=1.0, wind_speed_kmh=0,
                                     wind_direction_from_deg=0, minimum_battery_reserve_percent=20,
                                     maximum_wind_speed_kmh=30, maximum_altitude_m=50)
    example = ROOT / "missions/examples/agri_demo_001_sector_b.json"

    def geo(pid):
        p = site.point(pid)
        return local_to_geo(p.x_m, p.y_m, origin_latitude=g.latitude, origin_longitude=g.longitude,
                            y_axis_bearing_deg=0.0)

    base = json.loads(example.read_text())
    hl, hn = geo("TAKEOFF_B")
    base["vehicle"]["vehicle_id"] = "qgc_vehicle"
    base["route"] = {"mode": "waypoints", "home": {"latitude": hl, "longitude": hn, "altitude_m": 0.0},
                     "waypoints": [{"waypoint_id": p, "latitude": geo(p)[0], "longitude": geo(p)[1], "altitude_m": 5.0,
                                    "speed_kmh": 10.0, "action": "navigate"} for p in ("POI_1", "POI_3")],
                     "return_to_home": True}
    plan_path = export_qgroundcontrol_plan(MissionDefinition.model_validate(base), out / "poi1_poi3.plan",
                                           planned_home_amsl_m=584.0)
    r = mi.from_qgc_plan(plan_path, site=site, context=ctx, import_context=ic)
    _dump(out / "qgc_mission_input.json", r)
    p = MissionOrchestrator(ctx, mi.StructuredInterpreter(r), tracer=Tracer(mission_id="evidence-qgc"), pipeline="v2",
                            safety_policy="safety/4").run("structured mission input")
    planned = {"status": p["status"], "commands_sent": p["commands_sent"],
               "poi": sorted(pt for t in p["aerial"]["proposals"] for pt in t["poi_sequence"])}
    _dump(out / "qgc_multiagent_plan.json", planned)
    foreign = mi.from_mission_definition(MissionDefinition.model_validate(json.loads(example.read_text())), site=site,
                                         context=ctx, source={"kind": "MISSION_DEFINITION", "path": str(example.name)})
    _dump(out / "foreign_site_mission_input.json", foreign)
    nl = mi.from_natural_language("Survey POI_3 with drone_02 and return home.")
    _dump(out / "natural_language_mission_input.json", nl)
    return {"qgc_status": r["status"], "qgc_plan": planned, "qgc_findings": sorted({f["kind"] for f in r["findings"]}),
            "foreign_site": foreign["status"], "foreign_finding": foreign["findings"][0]["kind"],
            "natural_language": nl["status"],
            "as_expected": (r["status"] == "OK" and planned["status"] == "PROPOSED_PENDING_AUTHORIZATION"
                            and planned["poi"] == ["POI_1", "POI_3"] and planned["commands_sent"] == 0
                            and foreign["status"] == "REJECTED" and nl["status"] == "TO_INTERPRET")}


def scenarios(policy: str) -> list[dict]:
    rows = []
    for name in pd.SCENARIOS:
        r = pd.run_scenario(name, quiet=True, safety_policy=policy)
        rows.append({"scenario": name, "classification": r["classification"], "expected": pd.SCENARIOS[name]["expect"],
                     "as_expected": r["as_expected"], "commands": r["commands_sent"]})
    return rows


def generate(out: Path, scratch: Path, junit: Path | None = None) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    scratch = Path(scratch)
    _dump(out / "provenance.json", provenance())
    res = {}
    for label, reviewed in (("committed", False), ("reviewed", True)):
        s = rh.write_evidence(out / f"handoff_{label}", scratch / label, reviewed=reviewed)
        res[f"handoff_{label}"] = {"all_as_expected": s["all_as_expected"], "no_command": s["no_command_anywhere"],
                                   "cases": len(s["cases"])}
    ledger = scratch / "ledgers"
    ledger.mkdir(exist_ok=True)
    extra = handoff_extra(scratch, ledger)
    _dump(out / "handoff_extra.json", extra)
    res["handoff_extra"] = {k: v["classification"] for k, v in extra.items()}
    res["mission_inputs"] = mission_inputs(out / "mission_inputs")
    for label, reviewed in (("committed", False), ("reviewed", True)):
        rows = ib.run_all(scratch / label, reviewed=reviewed)
        _dump(out / f"battery_{label}.json", rows)
        res[f"battery_{label}"] = {"missions": len(rows), "as_expected": sum(r["as_expected"] for r in rows),
                                   "commands": sum(r["commands"] for r in rows)}
    for policy in ("safety/3", "safety/4"):
        rows = scenarios(policy)
        _dump(out / f"scenarios_{policy.replace('/', '')}.json", rows)
        res[f"scenarios_{policy}"] = {"scenarios": len(rows), "as_expected": sum(r["as_expected"] for r in rows),
                                      "commands": sum(r["commands"] for r in rows)}
    if junit is not None:
        shutil.copyfile(junit, out / "pytest_multiagent.xml")
    summary = {"schema": "tfg.multiagent.integration-v2-evidence-summary/1", "results": res}
    _dump(out / "summary.json", summary)
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.relative_to(out)}\n"
                                            for p in files))
    return summary


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--out", type=Path, required=True, help="NEW directory (never overwritten)")
    a.add_argument("--scratch", type=Path, required=True, help="where the immutable rover snapshots live")
    a.add_argument("--junit", type=Path, help="pytest junit xml of the multiagent suite, copied into the evidence")
    args = a.parse_args(argv)
    s = generate(args.out, args.scratch, args.junit)
    print(json.dumps(s, indent=1, sort_keys=True))
    r = s["results"]
    ok = (all(r[k]["all_as_expected"] and r[k]["no_command"] for k in ("handoff_committed", "handoff_reviewed"))
          and r["mission_inputs"]["as_expected"]
          and all(r[k]["as_expected"] == r[k]["missions"] and r[k]["commands"] == 0
                  for k in ("battery_committed", "battery_reviewed"))
          and all(r[k]["as_expected"] == r[k]["scenarios"] and r[k]["commands"] == 0
                  for k in ("scenarios_safety/3", "scenarios_safety/4")))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
