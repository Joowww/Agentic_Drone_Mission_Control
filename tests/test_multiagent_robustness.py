"""Robustness of the demo chain (offline, TEST_FIXTURE events): targets that stop being valid, telemetry lost before
the authorization, targets outside the area or too uncertain, several detections for one task, restart."""
from datetime import timedelta

from tests.test_multiagent_coordinator import NOW, coord, ev, g, obs, signed, through_validated


def ready(c, dt=0.0):
    c.handle(ev("HEARTBEAT", dt, task_id="AIR_drone_02"))
    c.handle(ev("OBSERVATION", dt + 1, observation=obs(dt=dt + 1)))
    c.handle(ev("AERIAL_POINT_REACHED", dt + 2, task_id="AIR_drone_02", point="POI_3"))
    assert g(c) == "READY_FOR_AUTHORIZATION"
    for phase in ("GROUND_PLANNED", "GROUND_VALIDATED", "AUTHORIZATION_REQUESTED"):
        assert c.handle(ev("MISSION_PHASE", dt + 3, phase=phase))["outcome"] == "APPLIED"
    return c


def auth(c, dt):
    return c.handle(ev("AUTHORIZATION", dt, **signed(dt), preconditions=["DRY_RUN_ADAPTER: no physical adapter"]))


def test_an_authorization_for_another_rover_or_out_of_its_window_is_refused():
    c = ready(through_validated(coord()))
    assert c.handle(ev("AUTHORIZATION", 5, **signed(5, vehicle="rover_02")))["outcome"] == "REFUSED"
    late = signed(5)
    assert c.handle(ev("AUTHORIZATION", 400, **late))["outcome"] == "REFUSED"  # signed at 4 s, valid 300 s
    assert c.mission_state == "AUTHORIZATION_REQUESTED"


def test_a_timely_authorization_still_works():
    c = ready(through_validated(coord()))
    assert auth(c, 5)["outcome"] == "APPLIED" and c.mission_state == "EXECUTION_BLOCKED"


def test_telemetry_lost_after_the_request_refuses_the_authorization():
    c = ready(through_validated(coord(stale_after_s=10)))
    out = auth(c, 20)  # the drone has not reported for 18 s
    assert out["outcome"] == "REFUSED" and "GROUND_TASK_NOT_READY_AT_AUTHORIZATION" in out["reason"]
    assert g(c) == "BLOCKED_DRONE_REPORTS_STALE" and c.mission_state == "AUTHORIZATION_REQUESTED"
    assert c.summary()["commands_sent"] == 0


def test_a_ready_target_that_is_no_longer_valid_is_blocked_and_cannot_be_authorized():
    c = ready(through_validated(coord(ready_hold_s=60, stale_after_s=10_000)))
    # observation valid for 30 s from t=1; READY may still be authorized until 30 + 60 s
    c.handle(ev("HEARTBEAT", 80, task_id="AIR_drone_02"))
    assert g(c) == "READY_FOR_AUTHORIZATION"
    c.handle(ev("HEARTBEAT", 100, task_id="AIR_drone_02"))
    assert g(c) == "BLOCKED_OBSERVATION_EXPIRED"
    assert auth(c, 101)["outcome"] == "REFUSED" and c.mission_state == "AUTHORIZATION_REQUESTED"


def test_a_target_outside_the_area_is_refused_and_the_rover_keeps_waiting():
    c = through_validated(coord())
    c.handle(ev("HEARTBEAT", task_id="AIR_drone_02"))
    out = c.handle(ev("OBSERVATION", 1, observation=obs("far", dt=1, offset_m=(400.0, 0.0))))
    assert out["outcome"] == "APPLIED_REFUSED_OBSERVATION" and g(c) == "CONDITIONAL_AWAITING_OBSERVATION"
    assert "PERIMETER" in out["reason"].upper() or "POI" in out["reason"].upper()


def test_a_target_between_pois_is_refused():
    c = through_validated(coord())
    c.handle(ev("HEARTBEAT", task_id="AIR_drone_02"))
    out = c.handle(ev("OBSERVATION", 1, observation=obs("between", dt=1, offset_m=(-3.0, 0.0))))
    assert out["outcome"] == "APPLIED_REFUSED_OBSERVATION" and g(c) == "CONDITIONAL_AWAITING_OBSERVATION"


def test_too_much_position_uncertainty_is_refused():
    c = through_validated(coord())
    c.handle(ev("HEARTBEAT", task_id="AIR_drone_02"))
    out = c.handle(ev("OBSERVATION", 1, observation=obs("fuzzy", dt=1, detection_sigma_m=3.0)))
    assert out["outcome"] == "APPLIED_REFUSED_OBSERVATION" and "UNCERTAINTY" in out["reason"].upper()
    assert g(c) == "AWAITING_GEOREFERENCED_TARGET" and c.states()["G1"]["target"] is None  # seen, not usable


def test_a_second_card_never_replaces_the_bound_target_of_the_only_task():
    c = through_validated(coord())
    c.handle(ev("HEARTBEAT", task_id="AIR_drone_02"))
    c.handle(ev("OBSERVATION", 1, observation=obs("first", dt=1)))
    bound = c.states()["G1"]
    second = obs("second", dt=2)
    second["detection"] = {**second["detection"], "object_class": "yellow_card", "target_id": "card_yellow_1"}
    c.handle(ev("OBSERVATION", 2, observation=second))
    assert c.states()["G1"]["observation_id"] == bound["observation_id"] == "first"
    assert c.states()["G1"]["target"] == bound["target"]


def test_a_restarted_coordinator_keeps_the_expiry_of_a_ready_target():
    c = ready(through_validated(coord(ready_hold_s=60, stale_after_s=10_000)))
    snap = c.snapshot()
    r = coord(ready_hold_s=60, stale_after_s=10_000)
    r.restore(snap)
    assert g(r) == "READY_FOR_AUTHORIZATION" and r.mission_state == "AUTHORIZATION_REQUESTED"
    r.handle(ev("HEARTBEAT", 100, task_id="AIR_drone_02"))
    assert g(r) == "BLOCKED_OBSERVATION_EXPIRED" and auth(r, 101)["outcome"] == "REFUSED"


def test_a_synthetic_observation_relabelled_as_a_sensor_is_refused():
    """Found offline: a REAL_SENSOR/SITL_SENSOR claim with any 64-hex evidence passed the gate inside a fixture event."""
    for kind, pose in (("REAL_SENSOR", "VEHICLE_EKF"), ("SITL_SENSOR", "SITL_GROUND_TRUTH")):
        c = through_validated(coord())
        c.handle(ev("HEARTBEAT", task_id="AIR_drone_02"))
        o = obs(f"relabelled-{kind}", dt=1)
        o["source"] = {"kind": kind, "device": "relabelled synthetic image", "evidence_sha256": "a" * 64}
        o["camera_pose"]["source"] = pose
        out = c.handle(ev("OBSERVATION", 1, observation=o))
        assert out["outcome"] == "REFUSED" and "OBSERVATION_PROVENANCE_INCONSISTENT" in out["reason"]
        assert g(c) == "CONDITIONAL_AWAITING_OBSERVATION" and c.mission_state == "AWAITING_DETECTION"
    c = through_validated(coord())
    c.handle(ev("HEARTBEAT", task_id="AIR_drone_02"))
    assert c.handle(ev("OBSERVATION", 1, observation=obs("fixture", dt=1)))["outcome"] == "APPLIED"
