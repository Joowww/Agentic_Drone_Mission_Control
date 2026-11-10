"""Drone Agent -> Hermes adapter -> Hermes validation -> H2 prevalidation (preflight) -> execution REQUEST, with the
real code and nothing submitted. The H2 effectful calls (start_preflight_sequence, check_simulation_ready,
execute_approved_mission) are replaced by tripwires in the in-process test and never reached."""
import copy
import json
from pathlib import Path

import pytest

from multiagent import drone_execution_bridge as db, hermes_mission_adapter as ha, integrated_mission as im

CTX = im.load_context(im.CONTEXT)
SITE, FLEET = im._site_fleet(CTX)
SEALED = json.loads((Path(ha.__file__).parent / "benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9/demo/"
                     "phase_b_proposal.json").read_text())
STATEMENT = "TEST_FIXTURE: offline test statement; not an operator authorization"


def adapted(p=None):
    return ha.adapt_proposal(copy.deepcopy(p or SEALED), context=CTX, site=SITE, fleet=FLEET,
                             source={"kind": "REPLAY_OF_SEALED_RUN"})


def test_without_an_operator_statement_the_request_stays_pending(tmp_path):
    out = db.request_execution(adapted(), mission_dir=tmp_path / "m", request_key="k1")
    assert out["status"] == "PENDING_AUTHORIZATION" and out["submitted"] is False and out["commands"] == []
    assert out["execution_path"]["realization"] == "SEQUENTIAL_H2" and out["would_call"] is None
    assert [m["vehicle_id"] for m in out["missions"]] == ["drone_02", "drone_01"]      # agenda order
    for m in out["missions"]:
        assert m["hermes_validation"]["execution_status"] == "APPROVED" and m["executor_compatibility_errors"] == []


def test_with_a_statement_the_h2_admission_check_passes_and_names_the_call_without_making_it(tmp_path):
    out = db.request_execution(adapted(), mission_dir=tmp_path / "m", request_key="k2", authorization_statement=STATEMENT)
    assert out["status"] == "READY_TO_REQUEST_EXECUTION" and out["submitted"] is False
    assert out["would_call"]["function"] == "tools.preflight_sequences.start_preflight_sequence"
    assert [Path(p).name for p in out["would_call"]["args"]["mission_paths"]] == ["drone_02.json", "drone_01.json"]
    assert [v["simulated_vehicle"] for v in out["admission_check"]["vehicle_selection"]] == ["v2", "v1"]
    assert out["authorization"]["authenticated"] is False                 # H2's model: declared, not authenticated
    sha = {d["vehicle_id"]: d["mission_sha256"] for d in adapted()["drones"]}
    assert out["admission_check"]["mission_sha256"] == [sha["drone_02"], sha["drone_01"]]


def test_the_boundary_never_reaches_an_effect(tmp_path, monkeypatch):
    import tools.multiagent_drone_sequence as boundary
    import tools.preflight_sequences as seq
    import tools.simulation_mission_executor as exe
    import tools.simulation_status as status

    def tripwire(*a, **k):
        raise AssertionError("an effectful H2 function was called")
    for mod, name in ((seq, "start_preflight_sequence"), (exe, "execute_approved_mission"),
                      (status, "check_simulation_ready"), (seq, "reserve_sequence")):
        monkeypatch.setattr(mod, name, tripwire)
    before = sorted(p.name for p in seq.SEQUENCE_ROOT.iterdir()) if seq.SEQUENCE_ROOT.exists() else []
    files = ha.mission_files(adapted())
    by = {d["vehicle_id"]: d for d in adapted()["drones"]}
    out = boundary.prepare({"mode": "OFFLINE_TEST", "mission_dir": str(tmp_path / "m"), "request_key": "k3",
                            "authorization_statement": STATEMENT,
                            "missions": [{"vehicle_id": v, "mission_json": b.decode(), "mission_sha256": by[v]["mission_sha256"],
                                          "start_delay_s": by[v]["start_delay_s"]} for v, b in files.items()]})
    assert out["status"] == "READY_TO_REQUEST_EXECUTION"
    after = sorted(p.name for p in seq.SEQUENCE_ROOT.iterdir()) if seq.SEQUENCE_ROOT.exists() else []
    assert before == after and sorted(p.name for p in (tmp_path / "m").iterdir()) == ["drone_01.json", "drone_02.json"]
    assert seq.MISSION_ROOT.name == "missions"                            # the module root is restored


def test_tampered_bytes_an_invalid_plan_and_the_operational_root_are_refused(tmp_path):
    import tools.multiagent_drone_sequence as boundary
    a = adapted()
    files = ha.mission_files(a)
    by = {d["vehicle_id"]: d for d in a["drones"]}
    missions = [{"vehicle_id": v, "mission_json": b.decode().replace('"altitude_m": 5.0', '"altitude_m": 6.0'),
                 "mission_sha256": by[v]["mission_sha256"], "start_delay_s": by[v]["start_delay_s"]}
                for v, b in files.items()]
    out = boundary.prepare({"mode": "OFFLINE_TEST", "mission_dir": str(tmp_path / "t"), "request_key": "k",
                            "authorization_statement": STATEMENT, "missions": missions})
    assert out["status"] == "REJECTED" and any("PLAN_MODIFIED_AFTER_VALIDATION" in p for p in out["problems"])
    bad = copy.deepcopy(SEALED)
    bad["brief"]["altitude_m"] = 500.0
    assert db.request_execution(adapted(bad), mission_dir=tmp_path / "b", request_key="k")["status"] == "REJECTED"
    out = boundary.prepare({"mode": "OPERATIONAL", "mission_dir": str(tmp_path / "o"), "request_key": "k",
                            "authorization_statement": STATEMENT, "missions": []})
    assert out["status"] == "REJECTED" and out["problems"][0].startswith("MISSION_DIR_OUTSIDE_MISSIONS_ROOT")


def test_a_single_drone_plan_is_routed_to_the_single_vehicle_preflight(tmp_path):
    p = copy.deepcopy(SEALED)
    p["aerial"]["proposals"] = [t for t in p["aerial"]["proposals"] if t["vehicle_id"] == "drone_02"]
    p["tasks"] = [t for t in p["tasks"] if t["task_id"] != "AIR_drone_01"]
    p["template"]["dependencies"] = [d for d in p["template"]["dependencies"] if d["after"] != "AIR_drone_01"]
    out = db.request_execution(adapted(p), mission_dir=tmp_path / "s", request_key="k", authorization_statement=STATEMENT)
    assert out["status"] == "READY_TO_REQUEST_EXECUTION"
    assert out["would_call"]["function"] == "tools.virtual_preflight.run_virtual_preflight"


def test_the_whole_chain_from_a_live_drone_agent_plan(tmp_path):
    """Supervisor + Drone Agent (scripted test doubles, no model) -> adapter -> schedule -> H2 request."""
    from multiagent import drone_schedule as ds, precision_demo as pd
    bundle = im.plan_phase_a(pd.CONFIG, text=pd.INTEGRATED_TEXT, safety_policy="safety/4")
    proposal = bundle["phase_a"]["proposal"]
    a = ha.adapt_proposal(proposal, context=bundle["context"], site=bundle["site"], fleet=bundle["fleet"],
                          source={"kind": "LIVE", "agents": "OFFLINE_DETERMINISTIC (scripted test doubles)"})
    assert a["status"] == "PLANNING_VALID" and {d["vehicle_id"] for d in a["drones"]} == {"drone_01", "drone_02"}
    plans = ds.plans_from_adapter(a)
    assert ds.reproduce_deconfliction(plans, bundle["context"].separation_policy)["schedule"]["drone_01"][
        "start_delay_s"] == 45.0
    out = db.request_execution(a, mission_dir=tmp_path / "live", request_key="live-1")
    assert out["status"] == "PENDING_AUTHORIZATION" and out["commands"] == []
