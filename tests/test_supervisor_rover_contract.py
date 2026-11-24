"""Offline compatibility of the supervisor's rover requests and plans with tfg.rover.plan-mission-execution/1 (the
rover controller's prepared contract). Nothing here starts, arms or moves anything; no rover module is imported."""
from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import subprocess

import pytest

from multiagent.supervisor import approval as appr
from multiagent.supervisor import plans as pl
from multiagent.supervisor import rover_contract as rc
from multiagent.supervisor.graph import Supervisor, _now

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "multiagent/fixtures/supervisor/agri_parcel_3v.scenario.json"
TEXT = ("Planifica la inspección de una parcela agrícola utilizando dos drones y un rover. Divide el terreno en dos "
        "sectores aéreos y asigna tres puntos terrestres al rover. Todos deben regresar a su punto de origen.")
LIVE = {"execution_binding": {k: f"fixture-{k}" for k in rc.BINDING_FIELDS},
        "frame_evidence": {"reference": "fixture", "sha256": "0" * 64},
        "authority": {k: f"fixture-approval-{k}" for k in rc.AUTHORITY_FIELDS}}


@pytest.fixture(scope="module")
def mission(tmp_path_factory):
    sup = Supervisor(SCENARIO, out_root=tmp_path_factory.mktemp("m"))
    out = sup.plan(TEXT)
    mdir = Path(out["mission_dir"])
    manifest = json.loads((mdir / "manifest.json").read_bytes())
    rover = next(v for v in manifest["vehicles"] if v["role"] == "rover")
    ground = json.loads((mdir / "proposal.json").read_bytes())["plan"]["ground_task"]
    data = (mdir / rover["plan"]["path"]).read_bytes()
    return sup, mdir, manifest, rover, ground, data


def test_generated_request_has_every_contract_field_and_is_formally_valid(mission):
    _, mdir, manifest, rover, ground, data = mission
    req = rc.build_request(vehicle=rover, plan_path=rover["plan"]["path"], plan_bytes=data, ground=ground,
                           manifest=manifest)
    assert set(rc.MANDATORY) <= set(req)
    assert req["plan"] == {"path": "plans/rover.plan", "sha256": rover["plan"]["sha256"], "firmware_type": 3,
                           "vehicle_type": 10}
    assert [i["index"] for i in req["route"]] == list(range(5)) and req["route"][0]["command"] == 178
    check = rc.check_request(req, data, plan_path=mdir / rover["plan"]["path"])
    assert check["status"] == "FORMALLY_VALID_PENDING_LIVE_EVIDENCE" and check["formal"] == []
    assert {p.split(":")[0] for p in check["pending"]} == {"EXECUTION_BINDING_MISSING", "FRAME_EVIDENCE_MISSING",
                                                           "LIMITS_INCOMPLETE", "AUTHORITY_MISSING"}
    # the supervisor never fills live identity or authority itself
    assert req["execution_binding"] is None and req["frame_evidence"] is None and req["authority"] is None


def test_complete_request_is_admissible_in_format_only(mission):
    _, mdir, manifest, rover, ground, data = mission
    req = rc.build_request(vehicle=rover, plan_path=rover["plan"]["path"], plan_bytes=data, ground=ground,
                           manifest=manifest)
    req.update(LIVE)
    req["limits"].update(lateral_m=0.15, stop="HOLD_THEN_DISARM")
    check = rc.check_request(req, data)
    assert check["status"] == "ADMISSIBLE" and "never authorizes" in check["note"]


def _mutate(data: bytes, fn) -> bytes:
    plan = json.loads(data)
    fn(plan["mission"])
    return json.dumps(plan).encode()


@pytest.mark.parametrize("mutation,reason", [
    (lambda m: m["items"].insert(1, {"command": 22, "frame": 3, "params": [0] * 7, "doJumpId": 99}), "AERIAL_ITEM"),
    (lambda m: m.update(vehicleType=2), "INCOMPATIBLE_VEHICLE"),
    (lambda m: m["items"].append({"command": 20, "frame": 2, "params": [0] * 7, "doJumpId": 9}), "UNSUPPORTED_ITEM"),
    (lambda m: m.update(cruiseSpeed=5.0), "PLAN_SPEED_EXCEEDS_LIMIT"),
    (lambda m: m["items"][1]["params"].__setitem__(6, 2.0), "WAYPOINT_INVALID"),
])
def test_plan_problems_are_rejected(mission, mutation, reason):
    _, _, manifest, rover, ground, data = mission
    bad = _mutate(data, mutation)
    req = rc.build_request(vehicle=rover, plan_path="plans/rover.plan", plan_bytes=bad, ground=ground,
                           manifest=manifest)
    check = rc.check_request(req, bad)
    assert check["status"] == "REJECTED" and any(f.startswith(reason) for f in check["formal"]), check["formal"]


def test_changed_bytes_or_skipped_items_are_rejected(mission):
    _, _, manifest, rover, ground, data = mission
    req = rc.build_request(vehicle=rover, plan_path="plans/rover.plan", plan_bytes=data, ground=ground,
                           manifest=manifest)
    assert "PLAN_HASH_CHANGED" in rc.check_request(req, data + b" ")["formal"][0]
    req["route"] = req["route"][:-1]
    assert any(f.startswith("ROUTE_DIFFERS_FROM_PLAN") for f in rc.check_request(req, data)["formal"])
    assert rc.check_request({"schema": "other"}, data)["status"] == "REJECTED"


def test_rover_controller_own_example_plan_is_blocked_by_its_speed_as_its_contract_states(tmp_path):
    """ardurover_one_meter.plan (commit 940a881cb): cruiseSpeed 0.3 m/s; the first trial limit is 0.10 m/s."""
    p = subprocess.run(["git", "-C", str(ROOT), "show",
                        "940a881cb:missions/examples/ardupilot_compatibility/ardurover_one_meter.plan"],
                       capture_output=True)
    if p.returncode != 0:
        pytest.skip("commit 940a881cb not available in this clone")
    data = p.stdout
    req = {"schema": rc.SCHEMA, "request_id": "x", "vehicle_id": "rover_01",
           "plan": {"path": "ardurover_one_meter.plan", "sha256": pl.sha256_bytes(data), "firmware_type": 3,
                    "vehicle_type": 10},
           "route": rc.route_from_plan(data),
           "limits": {"speed_mps": 0.10, "distance_m": 1.0, "lateral_m": 0.15, "stop": "HOLD_THEN_DISARM"}, **LIVE}
    check = rc.check_request(req, data)
    assert any(f.startswith("PLAN_SPEED_EXCEEDS_LIMIT: cruiseSpeed 0.3") for f in check["formal"]), check
    req["limits"]["speed_mps"] = 0.3
    assert rc.check_request(req, data)["status"] == "ADMISSIBLE"


def test_supervisor_real_executor_path_attaches_the_contract_request(mission, tmp_path):
    sup, mdir, manifest, rover, _, _ = mission
    now = _now()
    rec = appr.record(manifest, "rover_01", operator_id="op", session_id="S", session_expires_at=now + timedelta(hours=1),
                      at=now, valid_for_s=600, statement="ok")
    pl.write_json_once(mdir / "approvals" / "rover_01.approval.json", rec)
    glob = sup.execute(mdir, mode="OFFLINE_TEST", executor="real", session_id="S", vehicle_id="rover_01")
    st = json.loads((mdir / "execution/state.json").read_bytes())
    req = st["obs"]["rover_01"]["request"]
    assert req["plan_request"]["schema"] == rc.SCHEMA and req["status"] == "BLOCKED" and req["submitted"] is False
    assert req["admission_check"]["status"] == "FORMALLY_VALID_PENDING_LIVE_EVIDENCE"
    assert next(v for v in glob["vehicles"] if v["vehicle_id"] == "rover_01")["execution_state"] == "BLOCKED"
