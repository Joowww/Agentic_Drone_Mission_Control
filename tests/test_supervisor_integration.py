"""Integrated tests of the multi-vehicle supervisor: text -> LangGraph supervisor -> agents -> .plan files ->
validation -> approval -> gate -> executor adapters -> results. Offline: the executors are the test double (labelled
TEST_DOUBLE) or the REAL request boundaries in preparation-only mode (nothing is submitted, no simulator is touched).
"""
from __future__ import annotations

import ast
from datetime import timedelta
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from multiagent.supervisor import approval as appr
from multiagent.supervisor import executors as ex
from multiagent.supervisor import plans as pl
from multiagent.supervisor import results as res
from multiagent.supervisor.graph import Supervisor, _now

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "multiagent/fixtures/supervisor/agri_parcel_3v.scenario.json"
TEXT_C = ("Inspecciona una parcela agrícola con dos drones y un rover. Divide la zona en dos sectores aéreos. "
          "El rover debe visitar tres puntos terrestres. Todos deben regresar a sus posiciones iniciales.")
H2 = ROOT / "simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24"


def scenario(tmp_path, **mods) -> Path:
    data = json.loads(SCENARIO.read_text())
    data["rover_limits"].update(mods.get("rover", {}))
    data["parcel"].update(mods.get("parcel", {}))
    data["availability_overrides"] = mods.get("avail", {})
    path = tmp_path / f"scenario_{len(list(tmp_path.glob('scenario_*')))}.json"
    path.write_text(json.dumps(data))
    return path


def plan(tmp_path, text, scen=None, intent=None):
    sup = Supervisor(scen or SCENARIO, out_root=tmp_path / "missions")
    out = sup.plan(text, model_intent=intent)
    return sup, out, Path(out["mission_dir"])


def read(path):
    return json.loads(Path(path).read_bytes())


def approve_all(mdir, session="S1", mode="OFFLINE_TEST", vehicles=None, at=None):
    manifest = read(mdir / "manifest.json")
    at = at or _now()
    recs = {}
    for v in manifest["vehicles"]:
        if vehicles and v["vehicle_id"] not in vehicles:
            continue
        recs[v["vehicle_id"]] = appr.record(
            manifest, v["vehicle_id"], operator_id="operator-test", session_id=session,
            session_expires_at=at + timedelta(hours=1), at=at, valid_for_s=1800,
            statement=f"approve {v['vehicle_id']} (test)",
            source="TEST_FIXTURE" if mode == "OFFLINE_TEST" else "OPERATOR_CLI")
        pl.write_json_once(mdir / "approvals" / f"{v['vehicle_id']}.approval.json", recs[v["vehicle_id"]])
    return recs


def states(glob):
    return {v["vehicle_id"]: v["execution_state"] for v in glob["vehicles"]}


# ---------------------------------------------------------------------------------------------- scenario C
def test_c_three_vehicles_plan_files_manifest_and_validation(tmp_path):
    sup, out, mdir = plan(tmp_path, TEXT_C)
    assert out["status"] == "PLANNED", out["reasons"]
    manifest = read(mdir / "manifest.json")
    assert {v["vehicle_id"]: v["plan"]["path"] for v in manifest["vehicles"]} == {
        "drone_01": "plans/drone_1.plan", "drone_02": "plans/drone_2.plan", "rover_01": "plans/rover.plan"}
    assert pl.check_manifest(mdir)[1] == []
    for v in manifest["vehicles"]:
        data = (mdir / v["plan"]["path"]).read_bytes()
        assert pl.sha256_bytes(data) == v["plan"]["sha256"]
        assert not os.stat(mdir / v["plan"]["path"]).st_mode & stat.S_IWUSR  # read-only after writing
        body = json.loads(data)["mission"]
        cmds = [i["command"] for i in body["items"]]
        assert body["firmwareType"] == 3
        if v["role"] == "rover":
            assert body["vehicleType"] == 10 and 22 not in cmds and 21 not in cmds
            assert all(i["params"][6] == 0 for i in body["items"] if i["command"] == 16)
        else:
            assert body["vehicleType"] == 2 and cmds[0] == 22 and cmds[-1] == 21 and cmds.count(16) == 3
    # the two sectors are disjoint and cover the declared parcel points
    proposal = read(mdir / "proposal.json")
    seqs = [t["poi_sequence"] for t in proposal["plan"]["aerial_tasks"]]
    assert sorted(p for s in seqs for p in s) == [f"POI_{i}" for i in range(1, 7)]
    assert proposal["plan"]["ground_task"]["point_sequence"] == ["POI_1", "POI_3", "POI_5"]
    # rover waits for both drones (air-ground proximity resolved by ordering)
    assert {d["after"] for d in manifest["dependencies"]} == {"AIR_drone_01", "AIR_drone_02"}
    assert proposal["global_validation"]["status"] == "PASS"
    assert all(v["validation"] == "PASS" for v in manifest["vehicles"])
    decisions = [d["decision"] for d in read(mdir / "decisions.json")]
    assert {"SECTORS_ASSIGNED", "AERIAL_PLAN_DECONFLICTED", "AIR_GROUND_ORDERING"} <= set(decisions)
    assert read(mdir / "results/global_result.json")["status"] == "PLANNED_PENDING_APPROVAL"
    # traceability: delegation to each specialised agent is in the trace
    agents = {json.loads(line)["agent"] for line in (mdir / "trace/trace.jsonl").read_text().splitlines()}
    assert {"hermes_supervisor", "DroneAgent_drone_01", "DroneAgent_drone_02", "RoverAgent_rover_01"} <= agents
    assert read(mdir / "trace/opik_dry_run.json")["status"] in ("DRY_RUN_NOT_SENT", "OPIK_DRY_RUN_UNAVAILABLE")


def test_c_test_double_all_complete_is_never_reported_as_real_completion(tmp_path):
    sup, out, mdir = plan(tmp_path, TEXT_C)
    approve_all(mdir)
    glob = sup.execute(mdir, mode="OFFLINE_TEST", executor="test-double", session_id="S1")
    assert glob["status"] == "COMPLETED_TEST_DOUBLE"
    assert set(states(glob).values()) == {"COMPLETED"}
    for vid in ("drone_01", "drone_02", "rover_01"):
        result = read(mdir / "results" / vid / "result.json")
        assert result["synthetic"] is True and result["verdict"]["result"] == "pass"
        assert not (mdir / "results" / vid / "result.receipt.json").exists()
    # dependency order honoured: the rover ran last
    events = read(mdir / "execution/state.json")["events"]
    assert [e["vehicle_id"] for e in events] == ["drone_02", "drone_01", "rover_01"] or \
        [e["vehicle_id"] for e in events][-1] == "rover_01"
    with pytest.raises(PermissionError):
        res.write_receipt(mdir / "results/drone_01", read(mdir / "results/drone_01/result.json"), b"k" * 32)


def test_c_real_executors_prepare_h2_sequence_and_block_rover(tmp_path):
    sup, out, mdir = plan(tmp_path, TEXT_C)
    approve_all(mdir)
    glob = sup.execute(mdir, mode="OFFLINE_TEST", executor="real", session_id="S1")
    assert states(glob) == {"drone_01": "READY_TO_REQUEST_EXECUTION", "drone_02": "READY_TO_REQUEST_EXECUTION",
                            "rover_01": "BLOCKED"}
    assert glob["status"] == "EXECUTION_BLOCKED"
    st = read(mdir / "execution/state.json")
    boundary = st["obs"]["drone_01"]["request"]["boundary"]
    assert boundary["submitted"] is False and boundary["execution_path"]["realization"] == "SEQUENTIAL_H2"
    assert boundary["would_call"]["function"] == "tools.preflight_sequences.start_preflight_sequence"
    rover = st["obs"]["rover_01"]["request"]
    assert rover["plan_request"]["schema"] == "tfg.rover.plan-mission-execution/1"
    assert rover["plan_request"]["plan"]["sha256"] == read(mdir / "manifest.json")["vehicles"][2]["plan"]["sha256"]
    assert rover["admission_check"]["status"] == "FORMALLY_VALID_PENDING_LIVE_EVIDENCE"
    assert rover["admission_check"]["formal"] == []
    assert rover["single_goal_status"].startswith("NOT_APPLICABLE")
    assert not any((mdir / "results" / v / "result.json").exists() for v in ("drone_01", "drone_02", "rover_01"))


# ---------------------------------------------------------------------------------------------- scenario A / B
def test_a_one_drone_plan_and_single_vehicle_request(tmp_path):
    sup, out, mdir = plan(tmp_path, "Inspecciona la parcela con un dron y regresa al punto de inicio.")
    assert out["status"] == "PLANNED"
    manifest = read(mdir / "manifest.json")
    assert [v["vehicle_id"] for v in manifest["vehicles"]] == ["drone_01"]
    approve_all(mdir)
    glob = sup.execute(mdir, mode="OFFLINE_TEST", executor="real", session_id="S1")
    assert glob["status"] == "READY_TO_REQUEST_EXECUTION"
    boundary = read(mdir / "execution/state.json")["obs"]["drone_01"]["request"]["boundary"]
    assert boundary["execution_path"]["entry"] == "tools.virtual_preflight.run_virtual_preflight"


def test_b_rover_route_plan_without_aerial_commands(tmp_path):
    sup, out, mdir = plan(tmp_path, "El rover debe visitar tres puntos terrestres y regresar a su posición inicial.")
    assert out["status"] == "PLANNED"
    data = (mdir / "plans/rover.plan").read_bytes()
    items = json.loads(data)["mission"]["items"]
    assert [i["command"] for i in items] == [178, 16, 16, 16, 16]  # speed, 3 points, explicit return
    approve_all(mdir)
    glob = sup.execute(mdir, mode="OFFLINE_TEST", executor="real", session_id="S1")
    assert states(glob) == {"rover_01": "BLOCKED"} and glob["status"] == "EXECUTION_BLOCKED"


def test_b_single_goal_route_maps_to_the_one_goal_controller_request(tmp_path):
    sup, out, mdir = plan(tmp_path, "El rover debe ir a POI_3.")
    assert out["status"] == "PLANNED"
    assert "RETURN_NOT_REQUESTED" in [d["decision"] for d in read(mdir / "decisions.json")]
    approve_all(mdir)
    sup.execute(mdir, mode="OFFLINE_TEST", executor="real", session_id="S1")
    req = read(mdir / "execution/state.json")["obs"]["rover_01"]["request"]
    assert req["single_goal_request"]["schema"] == "tfg.multiagent.rover-execution-request/1"
    assert req["single_goal_request"]["target"]["point_id"] == "POI_3"
    assert req["single_goal_status"].startswith("PENDING_CONTROLLER")
    assert req["status"] == "BLOCKED"  # a single goal never stands for a .plan mission


# ---------------------------------------------------------------------------------------------- scenario D
def test_d_unavailable_drone_replans_sectors_and_records_deviation(tmp_path):
    scen = scenario(tmp_path, avail={"drone_02": {"available": False, "reason": "maintenance (synthetic)"}})
    _, out, mdir = plan(tmp_path, TEXT_C, scen)
    assert out["status"] == "PLANNED"
    decisions = [d["decision"] for d in read(mdir / "decisions.json")]
    assert "VEHICLE_UNAVAILABLE" in decisions and "MERGE_SECTORS_TO_AVAILABLE_DRONES" in decisions
    assert read(mdir / "proposal.json")["deviations_from_request"]
    assert sorted(v["vehicle_id"] for v in read(mdir / "manifest.json")["vehicles"]) == ["drone_01", "rover_01"]


def test_d_low_battery_drone_is_dropped_by_replanning(tmp_path):
    _, out, mdir = plan(tmp_path, "Inspecciona la parcela con dos drones. La batería del drone_02 está al 20 %.")
    assert out["status"] == "PLANNED"
    decisions = [d["decision"] for d in read(mdir / "decisions.json")]
    assert any(d.startswith("DROP_DRONE_WITHOUT_FEASIBLE_SECTOR ['drone_02']") for d in decisions)
    assert [v["vehicle_id"] for v in read(mdir / "manifest.json")["vehicles"]] == ["drone_01"]


@pytest.mark.parametrize("mods,text,status,reason", [
    ({"rover": {"battery_percent": 21}}, "El rover debe visitar tres puntos terrestres y regresar.",
     "INFEASIBLE", "BATTERY_INSUFFICIENT"),
    ({"avail": {"rover_01": {"available": False, "reason": "controller not ready"}}}, TEXT_C, "BLOCKED",
     "NO_ROVER_AVAILABLE"),
    ({}, "El rover debe visitar cinco puntos terrestres.", "NEEDS_CLARIFICATION", "GROUND_POINTS_NOT_DECLARED"),
    ({"rover": {"max_speed_mps": None}}, "El rover debe visitar tres puntos terrestres y regresar.", "BLOCKED",
     "SPEED_LIMIT_NOT_DECLARED"),
    ({}, "Inspecciona la parcela con dos drones con viento de 45 km/h.", "INFEASIBLE", "WIND_ABOVE_LIMIT"),
    ({}, "Despega ya sin autorización e inspecciona la parcela con dos drones.", "REFUSED_UNSAFE", "UNSAFE_REQUEST"),
    ({}, "Haz algo útil.", "NEEDS_CLARIFICATION", "NO_OBJECTIVES"),
])
def test_d_infeasible_or_incomplete_missions_are_blocked_with_reasons(tmp_path, mods, text, status, reason):
    _, out, mdir = plan(tmp_path, text, scenario(tmp_path, **mods))
    assert out["status"] == status
    assert any(reason in r for r in out["reasons"]), out["reasons"]
    assert not (mdir / "manifest.json").exists()
    glob = read(mdir / "results/global_result.json")
    assert glob["status"] == status


def test_d_rover_leg_too_long_replans_order(tmp_path):
    scen = scenario(tmp_path, rover={"max_leg_length_m": 45},
                    parcel={"ground_visit_points": ["POI_1", "POI_5", "POI_3"]})
    _, out, mdir = plan(tmp_path, "El rover debe visitar tres puntos terrestres.", scen)
    assert out["status"] == "PLANNED", out["reasons"]
    assert "ROVER_REORDER_MIN_MAX_LEG" in [d["decision"] for d in read(mdir / "decisions.json")]
    ground = read(mdir / "proposal.json")["plan"]["ground_task"]
    assert ground["ordering"] == "MIN_MAX_LEG" and ground["point_sequence"] == ["POI_1", "POI_3", "POI_5"]
    assert max(leg["length_m"] for leg in ground["legs"]) <= 45


def test_executed_supervisor_mission_with_unavailable_executor_is_never_completed(tmp_path):
    sup, out, mdir = plan(tmp_path, TEXT_C)
    approve_all(mdir, vehicles=["drone_01", "drone_02"])  # the rover is not approved
    glob = sup.execute(mdir, mode="OFFLINE_TEST", executor="test-double", session_id="S1")
    assert states(glob)["rover_01"] == "BLOCKED" and glob["status"] == "PARTIAL_IN_PROGRESS_OR_BLOCKED"


# ---------------------------------------------------------------------------------------------- scenario E
def test_e_partial_result_two_complete_third_fails(tmp_path):
    sup, out, mdir = plan(tmp_path, TEXT_C)
    approve_all(mdir)
    glob = sup.execute(mdir, mode="OFFLINE_TEST", executor="test-double", session_id="S1",
                       double=ex.OfflineTestDouble({"rover_01": "FAILED"}))
    assert states(glob) == {"drone_01": "COMPLETED", "drone_02": "COMPLETED", "rover_01": "FAILED"}
    assert glob["status"] == "PARTIAL"
    assert read(mdir / "results/rover_01/result.json")["verdict"]["result"] == "fail"


def test_e_failed_predecessor_cancels_dependent_rover(tmp_path):
    sup, out, mdir = plan(tmp_path, TEXT_C)
    approve_all(mdir)
    double = ex.OfflineTestDouble({"drone_02": "TIMEOUT"})
    glob = sup.execute(mdir, mode="OFFLINE_TEST", executor="test-double", session_id="S1", double=double)
    assert states(glob)["rover_01"] == "CANCELLED_DEPENDENCY" and glob["status"] == "PARTIAL"
    assert "rover_01" not in double.calls
    assert not (mdir / "results/rover_01/result.json").exists()  # nothing executed: no SafeFlight result
    # running again never repeats an executed vehicle
    double2 = ex.OfflineTestDouble()
    sup.execute(mdir, mode="OFFLINE_TEST", executor="test-double", session_id="S1", double=double2)
    assert "drone_01" not in double2.calls and "drone_02" not in double2.calls


# ---------------------------------------------------------------------------------------------- scenario F
@pytest.fixture
def approved(tmp_path):
    sup, out, mdir = plan(tmp_path, TEXT_C)
    recs = approve_all(mdir)
    return sup, mdir, recs


def _gate(sup, mdir, **kw):
    args = dict(mode="OFFLINE_TEST", executor="test-double", session_id="S1")
    args.update(kw)
    glob = sup.execute(mdir, **args)
    return glob, read(mdir / "execution/state.json")["gates"]


def test_f_no_approval_is_refused(tmp_path):
    sup, out, mdir = plan(tmp_path, TEXT_C)
    glob, gates = _gate(sup, mdir)
    assert all(g["status"] == "REFUSED" for g in gates.values())
    assert all("NOT_APPROVED" in g["reasons"][0] for g in gates.values())
    assert set(states(glob).values()) == {"BLOCKED"}


def test_f_wrong_session_and_expired_session_are_refused(approved):
    sup, mdir, _ = approved
    _, gates = _gate(sup, mdir, session_id="OTHER")
    assert all(any(r.startswith("SESSION_MISMATCH") for r in g["reasons"]) for g in gates.values())
    _, gates = _gate(sup, mdir, now=_now() + timedelta(hours=2))
    assert all("SESSION_EXPIRED" in g["reasons"] for g in gates.values())


def test_f_plan_modified_after_approval_is_refused(approved):
    sup, mdir, _ = approved
    path = mdir / "plans/drone_1.plan"
    path.chmod(0o644)
    path.write_bytes(path.read_bytes().replace(b'"cruiseSpeed"', b'"cruiseSpeed" ', 1))
    glob, _ = _gate(sup, mdir)
    assert set(states(glob).values()) == {"NOT_EXECUTED"} or glob["status"] not in ("COMPLETED", "COMPLETED_TEST_DOUBLE")
    st = read(mdir / "execution/state.json")
    assert any("PLAN_MODIFIED_AFTER_VALIDATION" in p for p in st["blocked"])


def test_f_wrong_vehicle_and_tampered_approval_are_refused(approved):
    sup, mdir, recs = approved
    manifest = read(mdir / "manifest.json")
    plan_sha = manifest["vehicles"][1]["plan"]["sha256"]
    mj = manifest["vehicles"][1]["mission_json"]["sha256"]
    wrong = appr.check(recs["drone_01"], manifest, "drone_02", now=_now(), mode="OFFLINE_TEST", session_id="S1",
                       plan_sha256_on_disk=plan_sha, mission_json_sha256_on_disk=mj)
    assert "VEHICLE_ID_MISMATCH" in wrong and "PLAN_SHA256_MISMATCH" in wrong
    tampered = {**recs["drone_02"], "plan_sha256": "0" * 64}
    found = appr.check(tampered, manifest, "drone_02", now=_now(), mode="OFFLINE_TEST", session_id="S1",
                       plan_sha256_on_disk=plan_sha, mission_json_sha256_on_disk=mj)
    assert any(f.startswith("TAMPERED") for f in found)
    assert appr.check(True, manifest, "drone_02", now=_now(), mode="OFFLINE_TEST", session_id="S1",
                      plan_sha256_on_disk=plan_sha)[0].startswith("NOT_AN_APPROVAL_RECORD")


def test_f_fixture_approval_and_test_double_refused_in_operational_mode(approved):
    sup, mdir, _ = approved
    _, gates = _gate(sup, mdir, mode="OPERATIONAL")
    for g in gates.values():
        assert "FIXTURE_APPROVAL_NOT_ACCEPTED_IN_OPERATIONAL_MODE" in g["reasons"]
        assert "TEST_DOUBLE_ONLY_IN_OFFLINE_TEST" in g["reasons"]


def test_f_manifest_tampering_blocks_everything(approved):
    sup, mdir, _ = approved
    path = mdir / "manifest.json"
    path.chmod(0o644)
    data = read(path)
    data["dependencies"] = []
    path.write_text(json.dumps(data))
    glob = sup.execute(mdir, mode="OFFLINE_TEST", executor="test-double", session_id="S1")
    assert any("MANIFEST_MODIFIED" in r for r in glob["reasons"])
    assert glob["status"] != "COMPLETED_TEST_DOUBLE"


def test_f_written_plan_is_never_overwritten(tmp_path):
    pl.write_once(tmp_path / "a.plan", b"x")
    with pytest.raises(pl.WriteOnceError):
        pl.write_once(tmp_path / "a.plan", b"y")


def test_f_unvalidated_plan_cannot_be_approved(tmp_path):
    manifest = {"mission_id": "M", "manifest_sha256": "0" * 64,
                "vehicles": [{"vehicle_id": "d", "validation": "FAIL", "vehicle_class": "ArduCopter",
                              "task_id": "T", "plan": {"sha256": "1" * 64}}]}
    with pytest.raises(ValueError):
        appr.record(manifest, "d", operator_id="o", session_id="s", session_expires_at=_now(), at=_now(),
                    valid_for_s=10, statement="x")


# ---------------------------------------------------------------------------------------------- Hermes intent
def test_hermes_intent_cannot_override_stated_facts(tmp_path):
    _, out, _ = plan(tmp_path, TEXT_C, intent={"drones_requested": 3})
    assert out["status"] == "NEEDS_CLARIFICATION"
    assert "MODEL_DISAGREES_WITH_STATED_FACT: drones_requested text=2 model=3" in out["reasons"]


def test_hermes_intent_fills_unstated_fields_and_is_recorded(tmp_path):
    text = "Inspecciona la parcela con dos drones y un rover. El rover debe visitar tres puntos terrestres."
    _, out, mdir = plan(tmp_path, text, intent={"return_to_start": True, "aerial_sectors": 2})
    assert out["status"] == "PLANNED"
    inferred = [d for d in read(mdir / "decisions.json") if d["decision"] == "MODEL_INFERRED"]
    assert {d["field"] for d in inferred} == {"return_to_start", "aerial_sectors"}
    assert read(mdir / "proposal.json")["plan"]["ground_task"]["return_to_start"] is True


def test_hermes_intent_with_undeclared_points_or_bad_shape_is_a_clarification(tmp_path):
    text = "Inspecciona la parcela con dos drones y un rover. El rover debe visitar tres puntos terrestres."
    _, out, _ = plan(tmp_path, text, intent={"ground_points": ["POI_99"]})
    assert out["status"] == "NEEDS_CLARIFICATION"
    _, out, _ = plan(tmp_path, text, intent={"drones_requested": "many"})
    assert out["status"] == "NEEDS_CLARIFICATION"


# ---------------------------------------------------------------------------------------------- real evidence
def test_real_h2_report_is_bound_to_its_mission_and_maps_to_an_unverified_result(tmp_path):
    report = H2 / "child_1_2f7db1f6/report.json"
    sha = read(report)["mission_sha256"]
    wrong = ex.observe_preflight_report(report, vehicle_id="drone_01", task_id="AIR_drone_01",
                                        approved_mission_sha256="0" * 64, plan_sha256="1" * 64)
    assert wrong["data_kind"] == "REJECTED_EVIDENCE"
    obs = ex.observe_preflight_report(report, vehicle_id="drone_01", task_id="AIR_drone_01",
                                      approved_mission_sha256=sha, plan_sha256="1" * 64)
    assert obs["data_kind"] == "REAL_SITL" and obs["execution_status"] == "COMPLETED" and obs["transformed"]
    assert obs["metrics"]["duration_s"]["value"] > 200
    vehicle = {"vehicle_id": "drone_01", "vehicle_class": "ArduCopter"}
    run_dir = tmp_path / "run"
    evidence = res.copy_evidence(obs, run_dir)
    result = res.safeflight_result(obs, vehicle, plan_name="drone_1.plan", run_id="h2.drone_01", group_id="h2",
                                   created_at="2026-11-24T00:00:00Z", producer={"name": "t"},
                                   environment={"simulator": "gazebo", "ardupilot_version": "4.8.0-dev"},
                                   evidence=evidence)
    assert result["synthetic"] is False and result["verdict"]["result"] == "inconclusive"
    assert result["mission"]["transformed"] is True
    pl.write_json(run_dir / "result.json", result)
    res.write_receipt(run_dir, result, bytes(range(32, 64)))
    assert read(run_dir / "result.receipt.json")["result_sha256"] == pl.sha256_file(run_dir / "result.json")


def test_global_status_rules():
    def v(state, kind, crit="pass"):
        return {"vehicle_id": "x", "mandatory": True, "approval": {"status": "APPROVED"},
                "criteria": [{"id": "c", "result": crit}],
                "execution": {"state": state, "confirmed": state in ("COMPLETED", "FAILED"), "data_kind": kind}}
    assert res.global_status([v("COMPLETED", "REAL_SITL")] * 3, planning_status="PLANNED") == "COMPLETED"
    assert res.global_status([v("COMPLETED", "REAL_SITL"), v("COMPLETED", "TEST_DOUBLE")],
                             planning_status="PLANNED") == "COMPLETED_TEST_DOUBLE"
    assert res.global_status([v("COMPLETED", "REAL_SITL"), v("COMPLETED", "REAL_SITL", "fail")],
                             planning_status="PLANNED") != "COMPLETED"
    assert res.global_status([v("COMPLETED", "REAL_SITL"), v("READY_TO_REQUEST_EXECUTION", None)],
                             planning_status="PLANNED") == "PARTIAL_IN_PROGRESS_OR_BLOCKED"
    assert res.global_status([v("NOT_EXECUTED", None)], planning_status="PLANNED") == "APPROVED_NOT_EXECUTED"


# ---------------------------------------------------------------------------------------------- interfaces
def test_cli_single_command_plan_approve_execute_status(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    run = lambda *a: subprocess.run([sys.executable, "-m", "multiagent.supervisor", *a], cwd=ROOT, env=env,  # noqa: E731
                                    capture_output=True, text=True, timeout=300)
    p = run("plan", "--scenario", str(SCENARIO), "--out", str(tmp_path), "--text", TEXT_C)
    assert p.returncode == 0, p.stderr
    mdir = json.loads(p.stdout)["mission_dir"]
    for vid in ("drone_01", "drone_02", "rover_01"):
        assert run("approve", "--mission", mdir, "--vehicle", vid, "--operator", "op", "--session", "S9",
                   "--statement", "ok").returncode == 0
    p = run("execute", "--mission", mdir, "--session", "S9", "--executor", "test-double", "--outcome",
            "rover_01=ABORTED")
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["status"] == "PARTIAL"
    assert json.loads(run("status", "--mission", mdir).stdout)["status"] == "PARTIAL"
    p = run("execute", "--mission", mdir, "--session", "S9", "--executor", "real", "--outcome", "rover_01=FAILED")
    assert p.returncode != 0  # outcomes are a test-double feature only


def test_mcp_facade_exposes_planning_only(tmp_path, monkeypatch):
    from multiagent.supervisor import mcp_server
    out = tmp_path / "private"
    out.mkdir(mode=0o700)
    monkeypatch.setenv("TFG_SUPERVISOR_OUT", str(out))
    server = mcp_server.build_server()
    import asyncio
    names = sorted(t.name for t in asyncio.run(server.list_tools()))
    assert names == sorted(mcp_server.TOOLS)
    assert not any("approve" in n or "execute" in n for n in names)
    res_ = mcp_server.supervisor_plan_mission(TEXT_C)
    assert res_["status"] == "PLANNED" and res_["movement_authorized"] is False and len(res_["vehicles"]) == 3
    assert mcp_server.supervisor_mission_status(res_["mission_id"])["status"] == "PLANNED_PENDING_APPROVAL"
    monkeypatch.setenv("TFG_SUPERVISOR_OUT", str(ROOT / "x"))
    with pytest.raises(SystemExit):
        mcp_server.out_root()


def test_registry_never_claims_undemonstrated_capabilities():
    sup = Supervisor(SCENARIO, out_root=Path("."))
    by = {v["vehicle_id"]: v for v in sup.registry["vehicles"]}
    assert by["drone_01"]["executor"]["status"] == "DEMONSTRATED_SITL"
    assert by["drone_01"]["capabilities"]["EXECUTE_GUIDED_WAYPOINT_MISSION_SITL"]["evidence_check"] == \
        "VERIFIED_FILES_AND_HASHES"
    assert by["drone_01"]["capabilities"]["EXECUTE_PLAN_AUTO_MISSION_SITL"]["status"] == "NOT_IMPLEMENTED"
    assert by["rover_01"]["executor"]["status"] == "NOT_IMPLEMENTED"
    assert by["rover_01"]["capabilities"]["EXECUTE_GUIDED_SINGLE_GOAL_SITL"]["status"] == "PENDING_CONTROLLER"
    assert by["rover_01"]["actions_forbidden"] == ["TAKEOFF", "LAND"]


def test_supervisor_package_never_imports_vehicle_control():
    forbidden = ("rclpy", "tools.rover_", "tools.vehicle_execution_lock", "tools.ros2_flight_control",
                 "tools.simulation_", "tools.mission_execution_gate", "tools.preflight_sequence")
    for path in (ROOT / "multiagent/supervisor").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for name in names:
                assert not name.startswith(forbidden), f"{path.name} imports {name}"


def test_mcp_stdio_session_like_hermes(tmp_path):
    """The same transport Hermes uses: a stdio MCP client starts the server process and calls the tools."""
    import asyncio
    from multiagent.supervisor import mcp_server
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    out = tmp_path / "private"
    out.mkdir(mode=0o700)

    async def session():
        params = StdioServerParameters(command=sys.executable, args=["-m", "multiagent.supervisor.mcp_server"],
                                       env={"PYTHONPATH": str(ROOT), "TFG_SUPERVISOR_OUT": str(out),
                                            "PATH": os.environ.get("PATH", "")}, cwd=str(ROOT))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = [t.name for t in (await s.list_tools()).tools]
                planned = await s.call_tool("supervisor_plan_mission", {"text": TEXT_C})
                refused = await s.call_tool("approve_plan", {})
                return names, planned, refused

    names, planned, refused = asyncio.run(asyncio.wait_for(session(), 240))
    assert sorted(names) == sorted(mcp_server.TOOLS)
    data = planned.structured_content or json.loads(planned.content[0].text)
    data = data.get("result", data)
    assert data["status"] == "PLANNED" and data["movement_authorized"] is False
    assert refused.is_error


def test_ingest_requires_a_gated_request_and_the_approved_mission(tmp_path):
    sup, out, mdir = plan(tmp_path, TEXT_C)
    report = H2 / "child_1_2f7db1f6/report.json"
    with pytest.raises(ValueError, match="REPORT_WITHOUT_GATED_REQUEST"):
        sup.ingest_report(mdir, vehicle_id="drone_01", report_path=report)
    approve_all(mdir)
    sup.execute(mdir, mode="OFFLINE_TEST", executor="real", session_id="S1")
    # the H2 report is real but belongs to another mission: never attached to this plan
    with pytest.raises(ValueError, match="EVIDENCE_NOT_FOR_THIS_PLAN"):
        sup.ingest_report(mdir, vehicle_id="drone_01", report_path=report)
    with pytest.raises(ValueError, match="only drone"):
        sup.ingest_report(mdir, vehicle_id="rover_01", report_path=report)
    assert read(mdir / "results/global_result.json")["status"] == "EXECUTION_BLOCKED"
