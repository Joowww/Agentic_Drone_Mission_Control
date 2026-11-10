"""ROVER_ADAPTER as the final conversion owner, MULTIAGENT_FRAMES2D as the offline test mode, the double-conversion guard,
the negative matrix in both modes, the coordinator reading the structured errors, and M4c-r1 (read-only) through the
final contract. The rover's code runs from immutable snapshots (committed / reviewed); nothing reaches a vehicle."""
from datetime import timedelta, datetime, timezone
import hashlib
import math

import pytest

from multiagent import frames2d as f, integration_battery as ib, precision_demo as pd
from multiagent import rover_goal_contract as gc, rover_handoff as rh, rover_handoff_fixtures as fx

OWNERS = ["ROVER_ADAPTER", "MULTIAGENT_FRAMES2D"]


@pytest.fixture(scope="module", params=["committed", "reviewed"])
def rover_side(request, tmp_path_factory):
    try:
        snap = rh.ensure_snapshot(tmp_path_factory.mktemp("rover_side") / request.param, reviewed=request.param == "reviewed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"snapshot unavailable: {exc}")
    with rh.RoverSnapshot(snap) as c:
        c.label = request.param
        yield c


def now():
    return datetime.now(timezone.utc)


def run(rover_side, *, req_kw=None, **inp_kw):
    t = now()
    return rh.handoff(fx.request(t, **(req_kw or {})), fx.synthetic_inputs(t, snapshot_label=rover_side.label, **inp_kw), rover_side)


def S(out):
    return {s["stage"]: s for s in out["stages"]}


def never_moves(out):
    assert out["commands"] == [] and out["movement_executed"] is False
    if out["envelope"]:
        assert out["envelope"]["commands"] == [] and out["envelope"]["movement_authorized"] is False


# ------------------------------------------------------------------------------------- owner: always declared --
def test_no_owner_is_ever_picked_by_default(rover_side):
    assert rh.HandoffInputs(mode="OFFLINE_TEST", now=now(), ground_state=None, site_goal=None).conversion_owner is None
    out = run(rover_side, conversion_owner=None)
    assert out["classification"] == "BLOCKED_BEFORE_SUBMISSION"
    assert any(e["code"] == "CONVERSION_OWNER_NOT_DECLARED" for e in out["errors"])
    never_moves(out)


def test_the_offline_test_owner_is_refused_in_operational_mode(rover_side):
    out = run(rover_side, mode="OPERATIONAL", receipt_provider=None)
    assert any(e["code"] == "MULTIAGENT_FRAMES2D_IS_OFFLINE_TEST_ONLY" for e in out["errors"])
    assert S(out)["frames"]["goal_rover"] is None          # nothing converted in a refused mode
    never_moves(out)


# --------------------------------------------------------------------------------- ROVER_ADAPTER (final) --
def test_rover_adapter_gets_the_complete_record_and_nothing_is_converted_here(rover_side):
    out = run(rover_side, conversion_owner="ROVER_ADAPTER")
    assert out["classification"] == "V2_READY_AWAITING_ROVER_ADAPTER"
    rec = out["envelope"]["goal_handoff"]
    assert rec["schema"] == gc.SCHEMA and rec["conversion_owner"] == "ROVER_ADAPTER"
    assert rec["goal_site"] == {**fx.SITE_GOAL, "point_id": "POI_3"}                      # site frame, as planned
    assert rec["frame_identity"] == {"site_frame": fx.SITE_FRAME, "rover_frame_expected": "odom"}
    assert rec["observation"]["observation_id"] == "red_target-obs-1" and rec["observation"]["original_pose"]
    assert rec["observation"]["observed_at"] and rec["observation"]["uncertainty_m"] == 0.12
    assert rec["dependencies"] and rec["localization"]["state"] == "ACCREDITED"
    assert rec["vehicle"] == {"vehicle_id": "rover_01", "boot_id": "rover-boot-1"}
    assert rec["constraints"]["human"] == fx.HUMAN_LIMITS and rec["constraints"]["authorized_area_site_frame"]
    ref = rec["transform_required"]
    assert ref["status"] == "REQUIRED_NOT_APPLIED" and ref["reference"]["accredited"] is True
    assert ref["reference"]["chain_source_sha256"] and ref["reference"]["rover_matrix"]
    assert rec["applied_conversions"] == [] and rec["goal_rover"] is None
    assert any(c.startswith("GOAL_DISTANCE_FROM_ROVER") for c in rec["delegated_checks"])
    assert out["envelope"]["rover_side"]["v2_payload"]["goal"]["frame"] == fx.SITE_FRAME
    ex = S(out)["executor_request"]
    assert ex["status"] == "NOT_REACHED" and any(r.startswith("ROVER_ADAPTER_NOT_IN_SNAPSHOT") for r in ex["reasons"])
    never_moves(out)


def test_the_reference_applied_once_by_the_adapter_equals_the_offline_conversion_and_twice_does_not(rover_side):
    final = run(rover_side, conversion_owner="ROVER_ADAPTER")["envelope"]["goal_handoff"]
    offline = run(rover_side, conversion_owner="MULTIAGENT_FRAMES2D")["envelope"]["goal_handoff"]
    m = final["transform_required"]["reference"]["rover_matrix"]["matrix"]
    apply = lambda x, y: (m[0][0] * x + m[0][1] * y + m[0][2], m[1][0] * x + m[1][1] * y + m[1][2])  # noqa: E731
    once = apply(fx.SITE_GOAL["x_m"], fx.SITE_GOAL["y_m"])
    to = offline["applied_conversions"][0]["to"]
    assert once == pytest.approx((to["x_m"], to["y_m"]), abs=1e-9)
    assert once == pytest.approx((5.5, -7.0), abs=1e-9)
    assert math.dist(apply(*once), once) > 1.0          # a second application lands elsewhere: it must be refused


# ----------------------------------------------------------------------------- double-conversion guard --
def test_a_conversion_cannot_be_recorded_twice_or_by_a_component_that_does_not_own_it(rover_side):
    offline = run(rover_side, conversion_owner="MULTIAGENT_FRAMES2D")["envelope"]["goal_handoff"]
    assert len(offline["applied_conversions"]) == 1 and offline["transform_required"]["status"] == "APPLIED_ONCE"
    with pytest.raises(gc.DoubleConversion, match="DOUBLE_CONVERSION"):
        gc.record_conversion(offline, offline["applied_conversions"][0])
    final = run(rover_side, conversion_owner="ROVER_ADAPTER")["envelope"]["goal_handoff"]
    with pytest.raises(gc.DoubleConversion, match="CONVERSION_NOT_OWNED_HERE"):
        gc.record_conversion(final, offline["applied_conversions"][0])
    tampered = {**final, "applied_conversions": offline["applied_conversions"], "goal_rover": offline["goal_rover"]}
    assert any(p.startswith("DOUBLE_CONVERSION_RISK") for p in gc.conversion_problems(tampered))
    assert gc.conversion_problems({**offline, "applied_conversions": offline["applied_conversions"] * 2})[0].startswith(
        "DOUBLE_CONVERSION")


@pytest.mark.parametrize("owner", OWNERS)
def test_a_goal_already_in_the_rover_frame_is_not_converted_again(rover_side, owner):
    out = run(rover_side, conversion_owner=owner, site_goal={"frame": "odom", "x_m": 5.5, "y_m": -7.0, "sigma_m": 0.12})
    codes = {e["code"] for e in out["errors"]}
    assert "GOAL_ALREADY_IN_ROVER_FRAME" in codes and out["classification"] == "BLOCKED_BEFORE_SUBMISSION"
    never_moves(out)


def test_the_executor_request_declares_it_must_not_convert_again(rover_side):
    out = run(rover_side, conversion_owner="MULTIAGENT_FRAMES2D")
    rec, nav = out["envelope"]["goal_handoff"], S(out)["executor_request"]["request"]
    assert gc.executor_goal_problems(rec, nav) == []
    again = {**nav, "goal": {**nav["goal"], "transform": "SITE_TO_ODOM"}}
    assert gc.executor_goal_problems(rec, again)[0].startswith("EXECUTOR_WOULD_CONVERT_AGAIN")
    moved = {**nav, "goal": {**nav["goal"], "x_m": nav["goal"]["x_m"] + 1.0}}
    assert gc.executor_goal_problems(rec, moved) == ["EXECUTOR_GOAL_DIFFERS_FROM_THE_RECORDED_CONVERSION"]


# ---------------------------------------------------------------------- negatives, in BOTH conversion modes --
def _negative(name, t):
    loc = fx.localization
    return {
        "transform_not_accredited": dict(graph=f.FrameGraph([fx.transform(t, accredited=False, source_sha256="")])),
        "pose_of_another_rover": dict(localization=loc(t, vehicle_id="rover_02")),
        "boot_changed": dict(localization=loc(t, boot_id="rover-boot-2")),
        "uncertainty_too_high": dict(localization=loc(t, sigma_m=0.6)),
        "localization_stale": dict(localization=loc(t, observed_at=t - timedelta(seconds=30))),
        "localization_lost": dict(localization=None),
        "observation_expired": dict(ground_state="BLOCKED_OBSERVATION_EXPIRED"),
        "observation_withdrawn": dict(ground_state="BLOCKED_TARGET_WITHDRAWN"),
        "aerial_dependency_failed": dict(ground_state="BLOCKED_DEPENDENCY_LOST"),
        "authorization_revoked": dict(receipt_provider=rh.fixture_receipt_provider("OFFLINE_TEST",
                                                                                   revocation_status="REVOKED")),
    }[name]


NEGATIVES = {  # name -> (category, a code prefix that must be present)
    "transform_not_accredited": ("FRAMES", "CHAIN_NOT_USABLE"),
    "pose_of_another_rover": ("LOCALIZATION", "ROVER_IDENTITY_MISMATCH"),
    "boot_changed": ("LOCALIZATION", "ROVER_BOOT_CHANGED"),
    "uncertainty_too_high": ("FRAMES", "UNCERTAINTY_TOO_HIGH"),
    "localization_stale": ("LOCALIZATION", "ROVER_LOCALIZATION_STALE"),
    "localization_lost": ("LOCALIZATION", "ROVER_LOCALIZATION_NOT_ACCREDITED"),
    "observation_expired": ("COORDINATOR", "GROUND_TASK_NOT_READY"),
    "observation_withdrawn": ("COORDINATOR", "GROUND_TASK_NOT_READY"),
    "aerial_dependency_failed": ("COORDINATOR", "GROUND_TASK_NOT_READY"),
    "authorization_revoked": ("AUTHORIZATION", "AUTHORIZATION"),
}


@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize("name", sorted(NEGATIVES))
def test_each_negative_blocks_with_a_structured_error_whoever_converts(rover_side, owner, name):
    t = now()
    out = rh.handoff(fx.request(t), fx.synthetic_inputs(t, snapshot_label=rover_side.label, conversion_owner=owner,
                                                        **_negative(name, t)), rover_side)
    cat, code = NEGATIVES[name]
    assert out["classification"] == "BLOCKED_BEFORE_SUBMISSION", out["errors"]
    assert any(e["category"] == cat and e["code"].startswith(code) for e in out["errors"]), out["errors"]
    assert out["envelope"] is None
    if owner == "ROVER_ADAPTER":
        assert S(out)["frames"]["goal_rover"] is None and S(out)["frames"]["goal_handoff"]["applied_conversions"] == []
    assert "UNCLASSIFIED" not in out["error_categories"], out["errors"]
    never_moves(out)


def test_a_scope_of_another_plan_is_refused_in_both_modes(rover_side):
    for owner in OWNERS:
        out = run(rover_side, conversion_owner=owner, req_kw={"signed_limits": {"max_speed_mps": 1.0, "timeout_s": 60.0}})
        assert any(e["category"] == "SCOPE" and e["code"] == "PLAN_ID_MISMATCH" for e in out["errors"])
        never_moves(out)


# --------------------------------------------------------------- the coordinator reads the structured errors --
def _coordinator(t):
    demo = pd.run_scenario("red_target", quiet=True, now=t, safety_policy="safety/4", keep_coordinator=True)
    return demo, demo.pop("_coordinator")


def test_a_lost_position_puts_the_ground_task_in_waiting_and_no_authorization_passes(rover_side):
    t = now()
    demo, coord = _coordinator(t)
    req, trace = ib.handoff_for(demo, rover_side, mode="no_localization", now=t)
    at = t + timedelta(seconds=6)
    coord.handle({"type": "EXECUTOR_PRECONDITIONS", "source": "TEST_FIXTURE", "at": at,
                  "reasons": trace["coordinator_events"][0]["reasons"]})   # exactly what the hand-off produced
    assert coord.states()["G1"]["state"] == "WAITING_FOR_ROVER_LOCALIZATION"
    res = coord.handle({"type": "AUTHORIZATION", "source": "TEST_FIXTURE", "at": at + timedelta(seconds=1),
                        "authorization_record": req["authorization"], "request": req, "preconditions": []})
    assert coord.mission_state != "EXECUTION_PENDING", res


def test_the_executor_policy_block_leaves_the_mission_blocked_not_pending(rover_side):
    t = now()
    demo, coord = _coordinator(t)
    req, trace = ib.handoff_for(demo, rover_side, now=t)
    assert trace["classification"] == "READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED"
    assert {e["category"] for e in trace["errors"]} == {"EXECUTOR_POLICY"}
    at = t + timedelta(seconds=6)
    pre = trace["coordinator_events"][0]["reasons"]
    coord.handle({"type": "EXECUTOR_PRECONDITIONS", "source": "TEST_FIXTURE", "at": at, "reasons": pre})
    coord.handle({"type": "AUTHORIZATION", "source": "TEST_FIXTURE", "at": at + timedelta(seconds=1),
                  "authorization_record": req["authorization"], "request": req, "preconditions": pre})
    assert coord.mission_state == "EXECUTION_BLOCKED"
    coord.handle({"type": "EXECUTOR_FEEDBACK", "source": "TEST_FIXTURE", "at": at + timedelta(seconds=2),
                  "feedback_type": trace["coordinator_events"][1]["feedback_type"]})
    assert coord.mission_state == "EXECUTION_BLOCKED"


# ------------------------------------------------------------------- M4c-r1 through the final contract --
def test_m4c_r1_keeps_its_provenance_and_is_refused_for_every_missing_precondition(rover_side):
    req, inp = fx.historical(now())
    inp.snapshot_label = rover_side.label
    out = rh.handoff(req, inp, rover_side)
    assert out["classification"] == "BLOCKED_BEFORE_SUBMISSION" and out["conversion_owner"] == "ROVER_ADAPTER"
    assert {"PLAN", "AUTHORIZATION", "LOCALIZATION"} <= set(out["error_categories"])
    assert "UNCLASSIFIED" not in out["error_categories"], out["errors"]
    assert req["navigation_plan"] is None and req["authorization"] is None      # nothing was invented
    p = out["provenance"]
    assert p["agents_recorded_as"] == "REAL_LOCAL_LLM" and p["new_llm_calls"] == 0
    assert p["aerial_assignments"] == {"drone_01": ["POI_1"], "drone_02": ["POI_3"]}
    assert p["drone_gate_accepted"] is True and p["rover_gate_accepted"] is True
    assert len(p["dependencies"]) == 2 and p["ground_target"]["matched_poi"] == "POI_3"
    sums = (fx.M4C_R1 / "demo/SHA256SUMS").read_text()
    assert f"{p['result_sha256']}  ./result.json" in sums or p["result_sha256"] in sums   # the sealed file, unchanged
    never_moves(out)
