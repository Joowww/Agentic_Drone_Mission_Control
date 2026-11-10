"""Rover Agent -> coordinator -> bridge -> v2 payload -> the rover validation -> protected admission -> dry-run, against TWO
immutable rover snapshots: the committed contract (57a0e303a) and the reviewed one (2e206f1fa + his protected review
patch, sha256-verified, applied only inside the snapshot). Nothing reaches a vehicle."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from multiagent import frames2d as f, rover_gate, rover_handoff as rh, rover_handoff_fixtures as fx


@pytest.fixture(scope="module", params=["committed", "reviewed"])
def rover_side(request, tmp_path_factory):
    reviewed = request.param == "reviewed"
    try:
        snap = rh.ensure_snapshot(tmp_path_factory.mktemp("rover_side") / request.param, reviewed=reviewed)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"snapshot unavailable: {exc}")
    with rh.RoverSnapshot(snap) as c:
        c.label = request.param
        yield c


def run(rover_side, *, req_kw=None, **inp_kw):
    now = datetime.now(timezone.utc)
    inp = fx.synthetic_inputs(now, snapshot_label=rover_side.label, **inp_kw)
    return rh.handoff(fx.request(now, **(req_kw or {})), inp, rover_side)


def S(out):
    return {s["stage"]: s for s in out["stages"]}


def never_moves(out):
    assert out["commands"] == [] and out["movement_executed"] is False
    assert S(out)["dry_run"]["physical_effect"] is False
    if out["envelope"]:
        assert out["envelope"]["commands"] == [] and out["envelope"]["movement_authorized"] is False


# -------------------------------------------------------------------------------- A: bridge_scope_sha256 --
def test_the_bridge_scope_field_is_rejected_by_the_committed_schema_and_accepted_by_the_reviewed_one(rover_side):
    out = run(rover_side)
    assert out["classification"] == "READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED"
    errors = S(out)["rover_v2"]["schema_errors"]
    if rover_side.label == "committed":
        assert errors and all(e.startswith("['authorization']") for e in errors)
    else:
        assert errors == []   # the rover's protected review patch adds the optional field: no change needed on our side
    assert out["envelope"]["scope"]["bridge_scope_sha256"] == out["envelope"]["rover_side"]["v2_payload"]["authorization"][
        "bridge_scope_sha256"]
    never_moves(out)


# ---------------------------------------------------------------- the rover's own authorization ledger (reviewed) --
def test_rover_ledger_a_fixture_grant_is_declared_not_authenticated(rover_side, tmp_path):
    if rover_side.label != "reviewed":
        pytest.skip("the ledger exists only in the reviewed snapshot")
    out = run(rover_side, receipt_provider=rh.rover_ledger_receipt_provider("OFFLINE_TEST", tmp_path / "ledger.json"))
    assert S(out)["rover_v2"]["status"] == "REJECTED" and "OPERATOR_NOT_AUTHENTICATED" in S(out)["rover_v2"]["reasons"]
    never_moves(out)


def test_rover_ledger_a_revoked_grant_is_refused(rover_side, tmp_path):
    if rover_side.label != "reviewed":
        pytest.skip("the ledger exists only in the reviewed snapshot")
    out = run(rover_side, receipt_provider=rh.rover_ledger_receipt_provider("OFFLINE_TEST", tmp_path / "l.json", revoke=True))
    assert any(r.startswith("RECEIPT_REFUSED_BY_LEDGER") and "AUTHORIZATION_NOT_ACTIVE" in r
               for r in S(out)["rover_v2"]["reasons"])
    assert out["classification"] == "BLOCKED_BEFORE_SUBMISSION"
    never_moves(out)
    with pytest.raises(PermissionError):
        rh.rover_ledger_receipt_provider("OPERATIONAL", tmp_path / "x.json")


# --------------------------------------------------------------------------------- B: submission envelope --
def test_the_envelope_keeps_everything_and_is_not_a_command(rover_side):
    env = run(rover_side)["envelope"]
    assert env["schema"] == "tfg.multiagent.rover-submission/1" and env["status"] == "READY_TO_SUBMIT_NOT_EXECUTED"
    assert (env["mission_id"], env["rover_id"], env["target"]["point_id"]) == ("GROUND_rover_01", "rover_01", "POI_3")
    assert env["plan_id"] and env["observation"]["observation_id"] == "red_target-obs-1" and env["observation"]["sha256"]
    assert env["dependencies"] and env["coordinator_state"] == "READY_FOR_AUTHORIZATION"
    assert env["limits"]["human"] == {"max_speed_mps": 0.3, "timeout_s": 60.0}
    assert env["scope"]["rover_plan_sha256"] and env["scope"]["rover_scope_sha256"] and env["validity"]
    assert env["authorization"]["record_source"] == "TEST_FIXTURE" and env["authorization"]["mode"] == "OFFLINE_TEST"
    assert env["rover_side"]["v2_decision"] == "READY_TO_SUBMIT"


def test_the_rover_agent_cannot_declare_itself_authorized():
    objectives = [{"objective_id": "G1", "point_id": "POI_3", "after_aerial": True}]
    good = {"decisions": [{"objective_id": "G1", "decision": "PLAN_TO_DECLARED_POI", "target_point": "POI_3",
                           "reason": None}]}
    kw = dict(objectives=objectives, awaiting=[], rover_available=True, declared_pois={"POI_3"}, aerial_points={"POI_3"})
    assert rover_gate.check_v3(good, **kw)["accepted"]
    for bad in ({**good, "authorized": True},
                {"decisions": [{**good["decisions"][0], "human_authorized": True}]},
                {"decisions": [{**good["decisions"][0], "commands": ["drive"]}]}):
        r = rover_gate.check_v3(bad, **kw)
        assert not r["accepted"] and any(x["kind"] == "AGENT_CLAIMS_AUTHORITY" for x in r["findings"])


# ------------------------------------------------------------------------------ C: one conversion boundary --
def test_multiagent_frames2d_converts_once_and_records_it(rover_side):
    out = run(rover_side)
    conv = S(out)["frames"]["conversion"]
    assert conv["converted_by"] == "multiagent.frames2d" and conv["from"]["frame"] == fx.SITE_FRAME
    goal = S(out)["executor_request"]["request"]["goal"]
    assert (round(goal["x_m"], 9), round(goal["y_m"], 9)) == (round(conv["to"]["x_m"], 9), round(conv["to"]["y_m"], 9))
    assert goal["transform"] == "IDENTITY_SAME_ACCREDITED_FRAME"   # the rover's executor does not convert again
    assert out["envelope"]["rover_side"]["v2_payload"]["goal"]["frame"] == fx.SITE_FRAME  # v2 keeps the ORIGINAL frame


def test_if_rover_owns_the_conversion_this_side_does_not_convert(rover_side):
    out = run(rover_side, conversion_owner="ROVER_ADAPTER")
    conv = S(out)["frames"]["conversion"]
    assert conv["owner"] == "ROVER_ADAPTER" and conv["applied_here"] is False and conv["transform"]
    assert S(out)["frames"]["goal_rover"] is None
    assert S(out)["executor_request"]["status"] == "NOT_REACHED"
    assert any("CONVERSION_DELEGATED_TO_ROVER_ADAPTER" in r for r in S(out)["executor_request"]["reasons"])
    never_moves(out)


# ------------------------------------------------------------------------------------ negative cases (§4) --
NEG = {
    "wrong_hash_plan_modified": dict(tamper=True, stage="authorization", reason="PLAN_SHA256_MISMATCH"),
    "other_vehicle": dict(req_kw=dict(signed_vehicle="rover_02"), stage="authorization", reason="ROVER_ID_MISMATCH"),
    "scope_of_another_plan": dict(req_kw=dict(signed_limits={"max_speed_mps": 1.0, "timeout_s": 60.0}),
                                  stage="authorization", reason="SCOPE_MISMATCH"),
    "expired_authorization": dict(req_kw=dict(at_delta=-400), stage="authorization", reason="OUTSIDE_VALIDITY_WINDOW"),
    "no_position": dict(inp=dict(localization=None), stage="frames", reason="ROVER_LOCALIZATION_NOT_ACCREDITED"),
    "invalid_frame": dict(inp=dict(localization=lambda now: fx.localization(now, frame="map")), stage="frames",
                          reason="ROVER_LOCALIZATION_FRAME_MISMATCH"),
    "expired_transform": dict(inp=dict(graph=lambda now: f.FrameGraph([fx.transform(
        now, not_before=now - timedelta(hours=2), expires=now - timedelta(hours=1))])), stage="frames",
        reason="CHAIN_NOT_USABLE"),
    "rover_rebooted": dict(inp=dict(localization=lambda now: fx.localization(now, boot_id="rover-boot-0")),
                           stage="frames", reason="ROVER_BOOT_CHANGED"),
    "pose_of_another_rover": dict(inp=dict(localization=lambda now: fx.localization(now, vehicle_id="rover_02")),
                                  stage="frames", reason="ROVER_IDENTITY_MISMATCH"),
    "target_outside_area": dict(inp=dict(authorized_area=[(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]),
                                stage="frames", reason="GOAL_OUTSIDE_AUTHORIZED_AREA"),
    "expired_observation": dict(inp=dict(ground_state="BLOCKED_OBSERVATION_EXPIRED"), stage="coordinator",
                                reason="GROUND_TASK_NOT_READY"),
    "failed_aerial_dependency": dict(inp=dict(ground_state="BLOCKED_DEPENDENCY_LOST"), stage="coordinator",
                                     reason="GROUND_TASK_NOT_READY"),
    "cancelled_mission": dict(inp=dict(ground_state="CANCELLED"), stage="coordinator", reason="GROUND_TASK_NOT_READY"),
    "fixture_in_operational_mode": dict(inp=dict(mode="OPERATIONAL", receipt_provider=None), stage="authorization",
                                        reason="FIXTURE_AUTHORIZATION_NOT_ACCEPTED_IN_OPERATIONAL_MODE"),
}


@pytest.mark.parametrize("name", sorted(NEG))
def test_negative_cases_are_structured_and_never_move(rover_side, name):
    case = NEG[name]
    now = datetime.now(timezone.utc)
    req_kw = dict(case.get("req_kw", {}))
    if "at_delta" in req_kw:
        req_kw["at"] = now + timedelta(seconds=req_kw.pop("at_delta"))
    req = fx.request(now, **req_kw)
    if case.get("tamper"):
        req["navigation_plan"] = {**req["navigation_plan"], "target_x_m": req["navigation_plan"]["target_x_m"] + 0.5}
    inp_kw = {k: (v(now) if callable(v) else v) for k, v in case.get("inp", {}).items()}
    out = rh.handoff(req, fx.synthetic_inputs(now, snapshot_label=rover_side.label, **inp_kw), rover_side)
    stage = S(out)[case["stage"]]
    assert any(case["reason"] in r for r in stage["reasons"]), (name, stage)
    assert out["classification"] == "BLOCKED_BEFORE_SUBMISSION" and out["envelope"] is None
    assert out["coordinator_events"][0]["type"] == "EXECUTOR_PRECONDITIONS" and out["coordinator_events"][0]["reasons"]
    never_moves(out)


def test_a_v1_payload_presented_as_v2_and_an_unknown_field_are_rejected_by_rover(rover_side):
    from multiagent import rover_mission_payload_bridge as mp
    case = mp.contract_fixtures(fx.SITE)["cases"]["complete"]
    v1 = rover_side.call("validate_v2", payload=case["payload"])["result"]
    assert v1["decision"] == "REJECTED" and "SCHEMA_MISMATCH" in v1["reasons"]
    out = run(rover_side)
    payload = dict(out["envelope"]["rover_side"]["v2_payload"])
    payload["teleport"] = True
    schema = rover_side.call("schema_v2", payload=payload)["result"]["errors"]
    assert any("teleport" in e for e in schema)
    tampered = {**payload, "goal": {**payload["goal"], "x_m": payload["goal"]["x_m"] + 1.0}}
    tampered.pop("teleport")
    assert "PLAN_HASH_MISMATCH" in rover_side.call("validate_v2", payload=tampered)["result"]["reasons"]


def test_an_uncertain_stop_after_the_handoff_is_unknown_in_the_coordinator():
    from multiagent import rover_sitl_interfaces as si
    from tests.test_multiagent_coordinator import coord, ev, obs, signed, through_validated
    c = through_validated(coord())
    c.handle(ev("HEARTBEAT", 0.5, task_id="AIR_drone_02"))
    c.handle(ev("OBSERVATION", 1, observation=obs("o", dt=1)))
    c.handle(ev("AERIAL_POINT_REACHED", 2, task_id="AIR_drone_02", point="POI_3"))
    for phase in ("GROUND_PLANNED", "GROUND_VALIDATED", "AUTHORIZATION_REQUESTED"):
        c.handle(ev("MISSION_PHASE", 3, phase=phase))
    c.handle(ev("AUTHORIZATION", 4, **signed(4), preconditions=["executor_admit: OPERATIONAL_ROVER_POLICY_DISABLED"]))
    c.handle(ev("EXECUTOR_FEEDBACK", 5, feedback_type=si.feedback_type("STOP_UNCONFIRMED")))
    assert c.mission_state == "UNKNOWN" and c.summary()["commands_sent"] == 0


def test_the_historical_m4c_r1_plan_is_blocked_on_both_snapshots(rover_side):
    now = datetime.now(timezone.utc)
    req, inp = fx.historical(now)
    inp.snapshot_label = rover_side.label
    out = rh.handoff(req, inp, rover_side)
    assert out["classification"] == "BLOCKED_BEFORE_SUBMISSION" and out["envelope"] is None
    assert S(out)["executor_admit"]["reasons"] == ["OPERATIONAL_ROVER_POLICY_DISABLED"]
    never_moves(out)
