"""Cross-repository compatibility: the supervisor's .plan files and result.json are checked with SafeFlight Desktop's
OWN importer and result reader (models/MissionPlan.py, SitlResult.py, SitlTrust.py on feature/mission-plan-import,
pinned commit). The Desktop files are read with ``git show`` into a temporary directory and run in an isolated
interpreter; the Desktop repository is never modified. Skipped when the repository is not reachable."""
from __future__ import annotations

from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from inputs import qgc_rover_plan_export as rx
from multiagent.supervisor import approval as appr
from multiagent.supervisor import executors as ex
from multiagent.supervisor import plans as pl
from multiagent.supervisor import results as res
from multiagent.supervisor.graph import Supervisor, _now

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path(os.environ.get("SAFEFLIGHT_DESKTOP_REPO", "/mnt/c/Users/joelm/SafeFlightDesktop-GitHub"))
DESKTOP_COMMIT = os.environ.get("SAFEFLIGHT_DESKTOP_COMMIT", "bdaec12")
MODULES = ("MissionPlan", "SitlResult", "SitlTrust", "MapView", "AppPaths")
TEXT = ("Inspecciona una parcela agrícola con dos drones y un rover. Divide la zona en dos sectores aéreos. "
        "El rover debe visitar tres puntos terrestres. Todos deben regresar a sus posiciones iniciales.")

CHECK = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I does not add the script directory
from models import MissionPlan as mp, SitlResult as sr, SitlTrust as st
req = json.loads(sys.argv[1]); out = {}
for name, path in req["plans"].items():
    plan = mp.load_plan(path)
    out[name] = {"status": plan.status, "vehicle": plan.vehicle, "errors": [str(e) for e in plan.errors],
                 "warnings": [str(w) for w in plan.warnings]}
    rpath = req["results"].get(name)
    if rpath:
        key = bytes.fromhex(req["key"]) if req.get("key") else None
        verifier = st.make_verifier(key) if key else None
        a = sr.load_result(rpath, plan, verify_provenance=verifier)
        out[name]["result"] = {"outcome": a.outcome, "problems": [str(p) for p in getattr(a, "problems", [])][:5]}
print(json.dumps(out))
'''


@pytest.fixture(scope="module")
def desktop(tmp_path_factory):
    if not (DESKTOP / ".git").exists():
        pytest.skip("SafeFlight Desktop repository not reachable")
    root = tmp_path_factory.mktemp("desktop")
    (root / "models").mkdir()
    (root / "models/__init__.py").write_text("")
    for m in MODULES:
        p = subprocess.run(["git", "-C", str(DESKTOP), "show", f"{DESKTOP_COMMIT}:models/{m}.py"],
                           capture_output=True, timeout=60)
        if p.returncode != 0:
            pytest.skip(f"Desktop module {m} not available at {DESKTOP_COMMIT}")
        (root / "models" / f"{m}.py").write_bytes(p.stdout)
    (root / "check.py").write_text(CHECK)

    def run(plans: dict, results: dict | None = None, key: str | None = None) -> dict:
        env = {"PATH": os.environ.get("PATH", ""), "SAFEFLIGHT_CONFIG_DIR": str(root / "cfg"),
               "HOME": str(root)}
        p = subprocess.run([sys.executable, "-I", str(root / "check.py"), json.dumps({"plans": plans, "results": results or {},
                                                                        "key": key})],
                           cwd=root, env=env, capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stderr
        return json.loads(p.stdout)
    return run


def test_desktop_imports_the_three_plans_with_the_right_vehicle(tmp_path, desktop):
    sup = Supervisor(ROOT / "multiagent/fixtures/supervisor/agri_parcel_3v.scenario.json", out_root=tmp_path)
    mdir = Path(sup.plan(TEXT)["mission_dir"])
    plans = {n: str(mdir / "plans" / n) for n in ("drone_1.plan", "drone_2.plan", "rover.plan")}
    out = desktop(plans)
    assert out["drone_1.plan"]["vehicle"] == "ArduCopter" and out["drone_2.plan"]["vehicle"] == "ArduCopter"
    assert out["rover.plan"]["vehicle"] == "ArduRover"
    for name, r in out.items():
        assert r["status"] == "PENDING" and r["errors"] == [], (name, r)


def test_desktop_reads_test_double_results_as_synthetic(tmp_path, desktop):
    sup = Supervisor(ROOT / "multiagent/fixtures/supervisor/agri_parcel_3v.scenario.json", out_root=tmp_path)
    mdir = Path(sup.plan(TEXT)["mission_dir"])
    manifest = json.loads((mdir / "manifest.json").read_bytes())
    for v in manifest["vehicles"]:
        rec = appr.record(manifest, v["vehicle_id"], operator_id="op", session_id="S", at=_now(),
                          session_expires_at=_now() + timedelta(hours=1), valid_for_s=600, statement="ok")
        pl.write_json_once(mdir / "approvals" / f"{v['vehicle_id']}.approval.json", rec)
    sup.execute(mdir, mode="OFFLINE_TEST", executor="test-double", session_id="S",
                double=ex.OfflineTestDouble({"drone_02": "FAILED"}))
    plans = {"drone_1.plan": str(mdir / "plans/drone_1.plan"), "drone_2.plan": str(mdir / "plans/drone_2.plan")}
    results = {"drone_1.plan": str(mdir / "results/drone_01/result.json"),
               "drone_2.plan": str(mdir / "results/drone_02/result.json")}
    out = desktop(plans, results)
    assert out["drone_1.plan"]["result"]["outcome"] == "SYNTHETIC_PASS"
    assert out["drone_2.plan"]["result"]["outcome"] == "SYNTHETIC_FAIL"


def test_desktop_marks_real_guided_result_unverified_never_validated(tmp_path, desktop):
    """A real H2 report bound to a plan: the executor flew the mission JSON, not the .plan (transformed), so even with
    a valid receipt Desktop must not reach VALIDATED."""
    h2 = ROOT / "simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24/child_1_2f7db1f6/report.json"
    sha = json.loads(h2.read_bytes())["mission_sha256"]
    plan_path = tmp_path / "drone_1.plan"
    sup = Supervisor(ROOT / "multiagent/fixtures/supervisor/agri_parcel_3v.scenario.json", out_root=tmp_path / "m")
    mdir = Path(sup.plan(TEXT)["mission_dir"])
    plan_path.write_bytes((mdir / "plans/drone_1.plan").read_bytes())
    obs = ex.observe_preflight_report(h2, vehicle_id="drone_01", task_id="AIR_drone_01", approved_mission_sha256=sha,
                                      plan_sha256=pl.sha256_file(plan_path))
    run_dir = tmp_path / "run"
    result = res.safeflight_result(obs, {"vehicle_id": "drone_01", "vehicle_class": "ArduCopter"},
                                   plan_name="drone_1.plan", run_id="h2.drone_01", group_id="g",
                                   created_at="2026-11-24T00:00:00Z", producer={"name": "t"},
                                   environment={"simulator": "gazebo", "ardupilot_version": "4.8.0-dev"},
                                   evidence=res.copy_evidence(obs, run_dir))
    pl.write_json(run_dir / "result.json", result)
    key = bytes(range(100, 132))
    res.write_receipt(run_dir, result, key)
    out = desktop({"drone_1.plan": str(plan_path)}, {"drone_1.plan": str(run_dir / "result.json")}, key.hex())
    assert out["drone_1.plan"]["result"]["outcome"] == "UNVERIFIED"


# ------------------------------------------------------------------ rover exporter (no Desktop needed)
WPS = [{"waypoint_id": "P1", "latitude": -35.3632, "longitude": 149.1650},
       {"waypoint_id": "P2", "latitude": -35.3631, "longitude": 149.1652}]


def test_rover_export_and_verifier():
    plan, log = rx.build_rover_plan(start=(-35.3633, 149.1652), waypoints=WPS, speed_mps=1.0,
                                    planned_home_amsl_m=584.0, return_to_start=True)
    data = rx.plan_bytes(plan)
    assert [i["command"] for i in plan["mission"]["items"]] == [178, 16, 16, 16]
    assert rx.verify_rover_plan(data, start=(-35.3633, 149.1652), waypoints=WPS, speed_mps=1.0,
                                return_to_start=True)["status"] == "FILE_MATCHES_EXPECTATIONS"
    bad = json.loads(data)
    bad["mission"]["items"].insert(0, {"command": 22, "doJumpId": 0, "params": [0] * 7})
    v = rx.verify_rover_plan(json.dumps(bad).encode(), start=(-35.3633, 149.1652), waypoints=WPS, speed_mps=1.0,
                             return_to_start=True)
    assert v["status"] == "FAILED"
    assert not next(c for c in v["checks"] if c["check"].startswith("no aerial"))["ok"]


@pytest.mark.parametrize("kw,needle", [
    ({"autopilot": "PX4"}, "ArduPilot ground rovers only"), ({"vehicle_type": "multirotor"}, "ground rovers only"),
    ({"speed_mps": None}, "speed limit"), ({"speed_mps": 0}, "speed limit"),
    ({"planned_home_amsl_m": float("nan")}, "AMSL"), ({"waypoints": []}, "at least one"),
    ({"start": (0, 0)}, "start coordinate"),
    ({"waypoints": [{"waypoint_id": "Z", "latitude": 0, "longitude": 0}]}, "current position")])
def test_rover_export_refusals(kw, needle):
    args = dict(start=(-35.3633, 149.1652), waypoints=WPS, speed_mps=1.0, planned_home_amsl_m=584.0,
                return_to_start=False)
    args.update(kw)
    with pytest.raises(rx.RoverExportRefused) as exc:
        rx.build_rover_plan(**args)
    assert any(needle in r for r in exc.value.reasons)
