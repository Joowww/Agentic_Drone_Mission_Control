"""UAV-UGV coordination cases (offline, TEST_FIXTURE events, real coordinator and perception gate)."""
from datetime import timedelta

from tests.test_multiagent_coordinator import NOW, SITE, coord, ev, g, obs, signed, through_validated


def validated(c, oid="o1", dt=1.0, **kw):
    c.handle(ev("HEARTBEAT", dt - 0.5, task_id="AIR_drone_02"))
    return c.handle(ev("OBSERVATION", dt, observation=obs(oid, dt=dt, **kw)))


def ready(c):
    validated(c)
    c.handle(ev("AERIAL_POINT_REACHED", 2, task_id="AIR_drone_02", point="POI_3"))
    for phase in ("GROUND_PLANNED", "GROUND_VALIDATED", "AUTHORIZATION_REQUESTED"):
        c.handle(ev("MISSION_PHASE", 3, phase=phase))
    return c


def test_01_drone_1_detects_at_its_own_point():
    c = through_validated(coord())
    c.handle(ev("HEARTBEAT", 0.5, task_id="AIR_drone_01"))
    o = obs("d1", dt=1)
    o["observer"] = {"vehicle_id": "drone_01", "camera_id": "cam_down_fixture"}
    poi1 = SITE.point("POI_1")
    o["camera_pose"]["position_m"] = [poi1.x_m, poi1.y_m, 10.0]
    c.handle(ev("OBSERVATION", 1, observation=o))
    st = c.states()["G1"]
    assert st["target"] == "POI_1" and st["waits_for_task"] == "AIR_drone_01"


def test_02_a_second_drone_detecting_another_card_never_takes_the_bound_task():
    c = through_validated(coord())
    validated(c, "a")
    o = obs("b", dt=1.5)
    o["detection"] = {**o["detection"], "target_id": "card_yellow_9", "object_class": "yellow_card"}
    c.handle(ev("OBSERVATION", 1.5, observation=o))
    assert c.states()["G1"]["observation_id"] == "a"


def test_03_two_observations_of_the_same_target_keep_one_binding():
    c = through_validated(coord())
    validated(c, "a")
    out = c.handle(ev("OBSERVATION", 1.5, observation=obs("a2", dt=1.5)))
    assert out["outcome"] == "APPLIED" and c.states()["G1"]["target"] == "POI_3"


def test_04_contradictory_observations_block_instead_of_replacing():
    c = through_validated(coord())
    validated(c, "a")
    o = obs("moved", dt=1.5)  # the SAME target id, now seen over another declared point
    o["camera_pose"]["position_m"] = [SITE.point("POI_1").x_m, SITE.point("POI_1").y_m, 10.0]
    c.handle(ev("OBSERVATION", 1.5, observation=o))
    assert g(c) == "BLOCKED_CONTRADICTORY_OBSERVATION" and c.states()["G1"]["target"] == "POI_3"
    assert c.handle(ev("AUTHORIZATION", 5, **signed(5)))["outcome"] == "REFUSED"


def test_05_a_detection_after_cancellation_never_reactivates():
    c = through_validated(coord())
    c.handle(ev("CANCEL", 0.5, reason="operator"))
    assert validated(c)["outcome"] == "REFUSED" and c.mission_state == "CANCELLED"


def test_06_07_a_silent_drone_or_an_incomplete_aerial_task_holds_the_rover():
    c = through_validated(coord(stale_after_s=10))
    validated(c)
    assert g(c) == "TARGET_VALIDATED"          # the drone has not reached POI_3: not ready
    c.handle(ev("CLOCK", 30))
    assert g(c) == "BLOCKED_DRONE_REPORTS_STALE"


def test_08_the_separation_status_is_kept():
    assert coord().summary()["separation"] in ("DECONFLICTED_BY_START_DELAY", "CLEAR", "NOT_APPLICABLE", None)


def test_09_rover_without_position_waits_for_localization():
    c = ready(through_validated(coord()))
    c.handle(ev("EXECUTOR_PRECONDITIONS", 4, reasons=["NO_POSITION_SOURCE: none declared"]))
    assert g(c) == "WAITING_FOR_ROVER_LOCALIZATION"


def test_10_a_temporarily_unavailable_rover_waits_reversibly_and_cannot_be_authorized():
    c = ready(through_validated(coord()))
    c.handle(ev("ROVER_AVAILABILITY", 4, vehicle_id="rover_01", available=False, reason="battery swap"))
    assert g(c) == "WAITING_FOR_ROVER_AVAILABILITY"
    assert c.handle(ev("AUTHORIZATION", 4.5, **signed(4.5)))["outcome"] == "REFUSED"
    c.handle(ev("ROVER_AVAILABILITY", 5, vehicle_id="rover_01", available=True))
    assert g(c) == "READY_FOR_AUTHORIZATION"
    assert c.handle(ev("ROVER_AVAILABILITY", 6, vehicle_id="rover_09", available=True))["outcome"] == "REFUSED"


def test_11_an_expired_target_blocks():
    c = ready(through_validated(coord(ready_hold_s=10, stale_after_s=10_000)))
    c.handle(ev("CLOCK", 60))
    assert g(c) == "BLOCKED_OBSERVATION_EXPIRED"


def test_12_a_mission_change_forces_a_replan():
    c = ready(through_validated(coord()))
    c.handle(ev("MISSION_CHANGED", 4, detail="operator changed the zones"))
    assert c.mission_state == "REPLAN_REQUIRED" and g(c) == "REPLAN_REQUESTED"


def test_13_an_executor_refusal_blocks_execution():
    c = ready(through_validated(coord()))
    c.handle(ev("AUTHORIZATION", 4, **signed(4)))
    assert c.mission_state == "EXECUTION_PENDING"
    c.handle(ev("EXECUTOR_FEEDBACK", 5, feedback_type="GROUND_TASK_REFUSED_BY_EXECUTOR", error="policy disabled"))
    assert c.mission_state == "EXECUTION_BLOCKED"


def test_14_authorization_lost_by_revocation_or_expiry():
    c = ready(through_validated(coord(stale_after_s=10_000, ready_hold_s=10_000)))
    c.handle(ev("AUTHORIZATION", 4, **signed(4)))
    c.handle(ev("AUTHORIZATION_REVOKED", 5, reason="operator withdrew it"))
    assert c.mission_state == "EXECUTION_BLOCKED" and "AUTHORIZATION_REVOKED" in c.mission_reason
    c2 = ready(through_validated(coord(stale_after_s=10_000, ready_hold_s=10_000)))
    c2.handle(ev("AUTHORIZATION", 4, **signed(4)))          # valid for 300 s from 3 s
    c2.handle(ev("CLOCK", 400))
    assert c2.mission_state == "EXECUTION_BLOCKED" and c2.mission_reason == "AUTHORIZATION_EXPIRED"
    restored = coord(stale_after_s=10_000, ready_hold_s=10_000)
    c3 = ready(through_validated(coord(stale_after_s=10_000, ready_hold_s=10_000)))
    c3.handle(ev("AUTHORIZATION", 4, **signed(4)))
    restored.restore(c3.snapshot())
    restored.handle(ev("CLOCK", 400))
    assert restored.mission_state == "EXECUTION_BLOCKED"     # the expiry survives a restart


def test_15_an_unknown_executor_report_is_unknown_and_never_completed():
    c = ready(through_validated(coord()))
    c.handle(ev("AUTHORIZATION", 4, **signed(4)))
    c.handle(ev("EXECUTOR_FEEDBACK", 5, feedback_type="UNRECOGNISED:COMPLETED_MAYBE"))
    assert c.mission_state == "UNKNOWN"
    assert "COMPLETED" not in str(set(__import__("multiagent.mission_coordinator", fromlist=["x"]).MISSION_TRANSITIONS))
    assert c.summary()["commands_sent"] == 0 and c.summary()["executing"] == []


def test_recovery_after_telemetry_loss_needs_a_fresh_observation_not_just_heartbeats():
    c = through_validated(coord(stale_after_s=10))
    validated(c, "a")
    c.handle(ev("CLOCK", 30))
    assert g(c) == "BLOCKED_DRONE_REPORTS_STALE"
    c.handle(ev("HEARTBEAT", 31, task_id="AIR_drone_02"))
    assert g(c) == "BLOCKED_DRONE_REPORTS_STALE"        # telemetry back is not enough to trust the old target
    c.handle(ev("OBSERVATION", 32, observation=obs("a-again", dt=32)))
    assert g(c) == "TARGET_VALIDATED" and c.states()["G1"]["observation_id"] == "a-again"
    c.handle(ev("AERIAL_POINT_REACHED", 33, task_id="AIR_drone_02", point="POI_3"))
    assert g(c) == "READY_FOR_AUTHORIZATION"
