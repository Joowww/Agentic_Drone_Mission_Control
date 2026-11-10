"""Rover Agent plan -> bridge -> the rover v2 contract -> the rover executor admission, with the rover's REAL code from an
immutable snapshot of the pinned commit, in its own process. Nothing reaches a vehicle; no command anywhere."""
from datetime import datetime, timedelta, timezone

import pytest

from multiagent import frames2d as f, rover_handoff as rh, rover_handoff_fixtures as fx, rover_sitl_interfaces as si
from tests.test_multiagent_coordinator import coord, ev, signed, through_validated


@pytest.fixture(scope="module")
def rover_side(tmp_path_factory):
    try:
        snap = rh.ensure_snapshot(tmp_path_factory.mktemp("rover_side") / f"snapshot_{rh.ROVER_CONTRACT_COMMIT}")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"rover contract commit {rh.ROVER_CONTRACT_COMMIT} not available: {exc}")
    with rh.RoverSnapshot(snap) as c:
        yield c


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def stages(out):
    return {s["stage"]: s for s in out["stages"]}


def no_command(out):
    assert out["commands"] == [] and out["movement_executed"] is False
    assert all(s.get("movement_authorized") in (None, False) for s in out["stages"])
    assert stages(out)["dry_run"]["physical_effect"] is False


def test_the_snapshot_is_the_pinned_contract(rover_side):
    now = datetime.now(timezone.utc)
    info = rover_side.call("info")["result"]
    assert info == {"v2_schema": "tfg.rover.mission-execution/2", "operational_rover_enabled": False}
    assert rh.contract_digest("57a0e303a") == rh.contract_digest("1514053da")  # contract files unchanged


def test_the_historical_m4c_r1_plan_is_blocked_for_the_right_reasons(rover_side):
    now = datetime.now(timezone.utc)
    req, inp = fx.historical(now)
    out = rh.handoff(req, inp, rover_side)
    s = stages(out)
    assert out["classification"] == "BLOCKED_BEFORE_SUBMISSION"
    assert s["request"]["reasons"] == ["NO_NAVIGATION_PLAN: speed and timeout were not set by a human"]
    assert s["coordinator"]["status"] == "PASS"                       # the sealed ground task was READY
    assert s["authorization"]["reasons"] == ["NO_HUMAN_AUTHORIZATION_RECORD"]
    assert "NAVIGATION_PLAN_PENDING" in s["rover_bridge"]["reasons"] and s["rover_v2"]["status"] == "WAITING"
    assert "ROVER_LOCALIZATION_NOT_ACCREDITED" in s["frames"]["reasons"]
    assert s["executor_request"]["status"] == "NOT_REACHED"
    assert s["executor_admit"]["reasons"] == ["OPERATIONAL_ROVER_POLICY_DISABLED"]
    no_command(out)


def test_the_synthetic_case_crosses_every_interface_and_stops_at_the_executor_policy(rover_side):
    now = datetime.now(timezone.utc)
    out = rh.handoff(fx.request(now), fx.synthetic_inputs(now), rover_side)
    s = stages(out)
    assert out["classification"] == "READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED", [(k, v["reasons"]) for k, v in s.items()]
    for name in ("request", "coordinator", "authorization", "rover_bridge", "frames", "rover_v2", "executor_request"):
        assert s[name]["status"] == "PASS", (name, s[name]["reasons"])
    goal = s["executor_request"]["request"]["goal"]
    assert (round(goal["x_m"], 9), round(goal["y_m"], 9), goal["frame"], goal["transform"]) == \
        (5.5, -7.0, "odom", "IDENTITY_SAME_ACCREDITED_FRAME")
    assert s["executor_request"]["request"]["limits"]["max_forward_mps"] == 0.3  # the human's limit, not a default
    assert s["executor_admit"]["status"] == "BLOCKED" and s["dry_run"]["status"] == "REFUSED"
    # The rover's own discrepancy stays visible: its payload violates its schema in exactly one field
    assert s["rover_v2"]["schema_errors"] and all(e.startswith("['authorization']") for e in s["rover_v2"]["schema_errors"])
    no_command(out)


def test_fixtures_cannot_be_used_in_operational_mode(rover_side):
    now = datetime.now(timezone.utc)
    with pytest.raises(PermissionError):
        rh.fixture_receipt_provider("OPERATIONAL")
    out = rh.handoff(fx.request(now), fx.synthetic_inputs(now, mode="OPERATIONAL", receipt_provider=None), rover_side)
    assert stages(out)["authorization"]["reasons"] == ["FIXTURE_AUTHORIZATION_NOT_ACCEPTED_IN_OPERATIONAL_MODE"]
    assert out["classification"] == "BLOCKED_BEFORE_SUBMISSION"
    no_command(out)


def expired_transform():
    return f.FrameGraph([fx.transform(NOW, not_before=NOW - timedelta(hours=2), expires=NOW - timedelta(hours=1))])


NEGATIVE = {
    "wrong_scope": (dict(req=dict(signed_limits={"max_speed_mps": 1.0, "timeout_s": 60.0})), "authorization", "SCOPE_MISMATCH"),
    "other_vehicle": (dict(req=dict(signed_vehicle="rover_02")), "authorization", "ROVER_ID_MISMATCH"),
    "no_authorization": (dict(req=dict(sign=False)), "authorization", "NO_HUMAN_AUTHORIZATION_RECORD"),
    "expired_authorization": (dict(req=dict(at=NOW - timedelta(seconds=400))), "authorization", "OUTSIDE_VALIDITY_WINDOW"),
    "target_expired": (dict(inp=dict(ground_state="BLOCKED_OBSERVATION_EXPIRED")), "coordinator", "GROUND_TASK_NOT_READY"),
    "aerial_dependency_lost": (dict(inp=dict(ground_state="BLOCKED_DEPENDENCY_LOST")), "coordinator", "GROUND_TASK_NOT_READY"),
    "observation_refused_still_waiting": (dict(inp=dict(ground_state="CONDITIONAL_AWAITING_OBSERVATION")), "coordinator",
                                          "GROUND_TASK_NOT_READY"),
    "mission_cancelled": (dict(inp=dict(ground_state="CANCELLED")), "coordinator", "GROUND_TASK_NOT_READY"),
    "rover_without_position": (dict(inp=dict(localization=None)), "frames", "ROVER_LOCALIZATION_NOT_ACCREDITED"),
    "incompatible_frame": (dict(inp=dict(localization="MAP")), "frames", "ROVER_LOCALIZATION_FRAME_MISMATCH"),
    "no_transform": (dict(inp=dict(graph=f.FrameGraph([]))), "frames", "UNKNOWN_FRAME"),
    "expired_transform": (dict(inp=dict(graph="EXPIRED")), "frames", "CHAIN_NOT_USABLE"),
    "speed_and_duration_not_set": (dict(req=dict(limits=None)), "request", "NO_NAVIGATION_PLAN"),
    "executor_parameters_not_declared": (dict(inp=dict(executor_params=None)), "executor_request",
                                         "EXECUTOR_PARAMETERS_NOT_DECLARED"),
    "no_operator_receipt": (dict(inp=dict(receipt_provider=None)), "rover_v2", "AUTHENTICATED_OPERATOR_RECEIPT_UNAVAILABLE"),
}


@pytest.mark.parametrize("name", sorted(NEGATIVE))
def test_negative_cases_give_structured_errors_and_no_command(rover_side, name):
    now = datetime.now(timezone.utc)
    change, stage_name, reason = NEGATIVE[name]
    inp_kw = dict(change.get("inp", {}))
    if inp_kw.get("localization") == "MAP":
        inp_kw["localization"] = fx.localization(now, frame="map")
    if inp_kw.get("graph") == "EXPIRED":
        inp_kw["graph"] = expired_transform()
    out = rh.handoff(fx.request(now, **change.get("req", {})), fx.synthetic_inputs(now, **inp_kw), rover_side)
    s = stages(out)
    assert any(r.startswith(reason) or reason in r for r in s[stage_name]["reasons"]), (name, s[stage_name])
    assert out["classification"] != "UNEXPECTED"
    no_command(out)
    pre = out["coordinator_events"][0]
    assert pre["type"] == "EXECUTOR_PRECONDITIONS" and pre["reasons"]


def test_a_plan_modified_after_signing_is_refused_by_both_sides(rover_side):
    now = datetime.now(timezone.utc)
    req = fx.request(now)
    req["navigation_plan"] = {**req["navigation_plan"], "target_x_m": req["navigation_plan"]["target_x_m"] + 0.5}
    out = rh.handoff(req, fx.synthetic_inputs(now), rover_side)
    s = stages(out)
    assert "PLAN_SHA256_MISMATCH" in s["authorization"]["reasons"]
    assert "BRIDGE_SCOPE_HASH_MISMATCH" in s["rover_bridge"]["reasons"]
    no_command(out)


def test_the_coordinator_interprets_the_handoff_errors():
    c = through_validated(coord())
    c.handle(ev("HEARTBEAT", task_id="AIR_drone_02"))
    c.handle(ev("OBSERVATION", 1, observation=__import__("tests.test_multiagent_coordinator", fromlist=["obs"]).obs("h", dt=1)))
    c.handle(ev("AERIAL_POINT_REACHED", 2, task_id="AIR_drone_02", point="POI_3"))
    for phase in ("GROUND_PLANNED", "GROUND_VALIDATED", "AUTHORIZATION_REQUESTED"):
        c.handle(ev("MISSION_PHASE", 3, phase=phase))
    blocked = ["executor_admit: OPERATIONAL_ROVER_POLICY_DISABLED"]
    assert c.handle(ev("EXECUTOR_PRECONDITIONS", 4, reasons=blocked))["outcome"] == "APPLIED"
    out = c.handle(ev("AUTHORIZATION", 5, **signed(5), preconditions=blocked))
    assert out["outcome"] == "APPLIED" and c.mission_state == "EXECUTION_BLOCKED"   # blocked, never executing
    c.handle(ev("EXECUTOR_FEEDBACK", 6, feedback_type=si.feedback_type("STOP_REQUESTED_NO_STANDSTILL_OBSERVED")))
    assert c.mission_state == "UNKNOWN"   # an uncertain STOP is never assumed
    assert c.summary()["commands_sent"] == 0 and c.summary()["executing"] == []


def test_the_evidence_cases_classify_as_declared(rover_side):
    from multiagent import rover_handoff_fixtures as fxm
    now = datetime.now(timezone.utc)
    for name, (req, inp, expected) in fxm.cases(now).items():
        out = rh.handoff(req, inp, rover_side)
        assert out["classification"] == expected, name
        no_command(out)
