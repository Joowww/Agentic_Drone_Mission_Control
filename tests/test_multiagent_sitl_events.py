"""SITL event input adapter (offline, synthetic fixtures; no ROS 2, no MAVLink, no Gazebo)."""
from datetime import timedelta

import pytest

from multiagent import sitl_events as se
from tests.test_multiagent_coordinator import NOW, coord, g, obs, through_validated

SITE = "synthetic_orchard_local"
CFG = se.AdapterConfig(drones={"drone_01": "AIR_drone_01", "drone_02": "AIR_drone_02"}, rovers=("rover_01",),
                       frames={"VEHICLE_POSE": {SITE}}, cameras={"drone_01": ("cam_down_fixture",),
                                                                 "drone_02": ("cam_down_fixture",)},
                       max_age_s=2.0, max_future_skew_s=0.5, telemetry_timeout_s=5.0, site_bounds=(-50, -50, 50, 50))


def pose(msg, vid="drone_02", seq=1, dt=0.0, boot="b1", **body):
    return {"msg_id": msg, "kind": "VEHICLE_POSE", "vehicle_id": vid, "boot_id": boot, "seq": seq,
            "stamp_utc": (NOW + timedelta(seconds=dt)).isoformat(), "source": "SITL",
            "body": {"x_m": 8.0, "y_m": 4.0, "yaw_rad": 0.0, "frame": SITE, "sigma_m": 0.1, **body}}


def detection(msg, seq=2, dt=0.0, **obs_kw):
    o = obs(msg, dt=dt, **obs_kw)
    return {"msg_id": msg, "kind": "DETECTION", "vehicle_id": "drone_02", "boot_id": "b1", "seq": seq,
            "stamp_utc": (NOW + timedelta(seconds=dt)).isoformat(), "body": {"observation": o}}


def run(raws, *, now_dt=0.5, state=None, ingestion=se.TEST_FIXTURE_INGESTION):
    state = state or se.AdapterState()
    return se.emit(raws, CFG, state, now=NOW + timedelta(seconds=now_dt), ingestion=ingestion), state


def reasons(out):
    return [r for x in out["rejected"] for r in x["reasons"]]


def test_a_correct_pose_becomes_a_heartbeat_with_provenance():
    out, _ = run([pose("m1")])
    assert [e["type"] for e in out["events"]] == ["HEARTBEAT"] and out["events"][0]["task_id"] == "AIR_drone_02"
    assert out["events"][0]["source"] == "TEST_FIXTURE" and out["events"][0]["provenance"]["claimed_source"] == "SITL"
    assert out["telemetry"]["drone_02"] == "OK" and out["telemetry"]["drone_01"] == "NEVER_RECEIVED"


def test_a_claimed_sitl_source_is_not_accreditation():
    fake = se.IngestionSource("UNACCREDITED_SOCKET", False, "SITL", "SITL_SENSOR")
    out, _ = run([pose("m1")], ingestion=fake)
    assert not out["events"] and any(r.startswith("INGESTION_NOT_ACCREDITED") for r in reasons(out))


@pytest.mark.parametrize("raw, reason", [
    (pose("m1", vid="drone_09"), "UNKNOWN_VEHICLE"),
    (pose("m1", frame="map"), "FRAME_NOT_ALLOWED"),
    (pose("m1", dt=-10.0), "STALE"),
    (pose("m1", dt=5.0), "FROM_THE_FUTURE"),
    (pose("m1", x_m=float("nan")), "POSE_NOT_FINITE"),
    (pose("m1", x_m=500.0), "POSE_OUTSIDE_SITE_BOUNDS"),
    ({"msg_id": "s", "kind": "VEHICLE_STATE", "vehicle_id": "drone_02", "boot_id": "b1", "seq": 1,
      "stamp_utc": NOW.isoformat(), "body": {"state": "WOBBLING"}}, "VEHICLE_STATE_UNKNOWN"),
    (detection("d1", observer={"vehicle_id": "drone_02", "camera_id": "cam_unaccredited"}), "SENSOR_NOT_ACCREDITED"),
    ({"msg_id": "x", "kind": "TELEPORT"}, "PARSE"),
])
def test_invalid_events_are_rejected_with_a_reason(raw, reason):
    out, _ = run([raw])
    assert not out["events"] and any(r.startswith(reason) for r in reasons(out)), reasons(out)


def test_duplicates_and_out_of_order_sequences():
    out, state = run([pose("m1", seq=5), pose("m1", seq=5)])
    assert len(out["events"]) == 1 and "DUPLICATE_MESSAGE" in reasons(out)
    out, _ = run([pose("m2", seq=4)], state=state)
    assert any(r.startswith("OUT_OF_ORDER") for r in reasons(out))


def test_a_boot_change_re_establishes_identity_instead_of_continuing():
    out, state = run([pose("m1", seq=50)])
    out, _ = run([pose("m2", seq=1, boot="b2")], state=state)  # a lower seq is fine: it is a new incarnation
    types = [e["type"] for e in out["events"]]
    assert types == ["VEHICLE_IDENTITY", "HEARTBEAT"] or sorted(types) == ["HEARTBEAT", "VEHICLE_IDENTITY"]
    assert any(e.get("vehicle_id") == "drone_02@boot:b2" for e in out["events"])


def test_a_relabelled_sensor_observation_is_refused():
    raw = detection("d1")
    raw["body"]["observation"]["source"] = {"kind": "REAL_SENSOR", "device": "relabelled", "evidence_sha256": "a" * 64}
    out, _ = run([raw])
    assert any(r.startswith("OBSERVATION_PROVENANCE_INCONSISTENT") for r in reasons(out))


def test_telemetry_loss_is_reported_and_blocks_the_ground_task_in_the_coordinator():
    out, state = run([pose("m1")])
    later, _ = run([], state=state, now_dt=30.0)
    assert later["telemetry"]["drone_02"] == "LOST"
    c = through_validated(coord(stale_after_s=10))
    for e in out["events"]:
        c.handle(e)
    c.handle({"type": "OBSERVATION", "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=1), "observation": obs("o1", dt=1)})
    c.handle({"type": "CLOCK", "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=30)})
    assert g(c) == "BLOCKED_DRONE_REPORTS_STALE"


def test_adapter_events_drive_the_real_coordinator_end_to_end():
    raws = [pose("m1", seq=1, dt=1.0), detection("d1", seq=2, dt=1.0),
            {"msg_id": "r1", "kind": "POINT_REACHED", "vehicle_id": "drone_02", "boot_id": "b1", "seq": 3,
             "stamp_utc": (NOW + timedelta(seconds=2)).isoformat(), "body": {"point": "POI_3"}}]
    out, _ = run(raws, now_dt=2.5)
    assert [e["type"] for e in out["events"]] == ["HEARTBEAT", "OBSERVATION", "AERIAL_POINT_REACHED"]
    c = through_validated(coord())
    outcomes = [c.handle(e)["outcome"] for e in out["events"]]
    assert outcomes == ["APPLIED", "APPLIED", "APPLIED"] and g(c) == "READY_FOR_AUTHORIZATION"
    assert c.summary()["commands_sent"] == 0


def test_ros2_shaped_odometry_fixture_converts_without_ros2():
    import json
    import math
    import sys
    from datetime import datetime
    from pathlib import Path
    msg = json.loads((Path(se.__file__).parent / "fixtures/ros2_like/odometry_drone_02.json").read_text())
    raw = se.from_ros2("nav_msgs/msg/Odometry", msg, vehicle_id="drone_02", boot_id="b1", seq=1, msg_id="odo-1")
    assert raw["kind"] == "VEHICLE_POSE" and math.isclose(raw["body"]["yaw_rad"], math.pi / 2)
    assert math.isclose(raw["body"]["sigma_m"], 0.1) and raw["body"]["frame"] == SITE and raw["source"] == "SITL"
    now = datetime.fromisoformat(raw["stamp_utc"]) + timedelta(seconds=0.5)
    out = se.emit([raw], CFG, se.AdapterState(), now=now)
    assert [e["type"] for e in out["events"]] == ["HEARTBEAT"] and out["events"][0]["source"] == "TEST_FIXTURE"
    assert out["events"][0]["provenance"]["claimed_source"] == "SITL"   # a claim, not accreditation
    assert "rclpy" not in sys.modules
    with pytest.raises(ValueError, match="UNSUPPORTED_ROS2_TYPE"):
        se.from_ros2("sensor_msgs/msg/Image", msg, vehicle_id="drone_02", boot_id="b1", seq=2, msg_id="x")


# ---------------------------------------------------------------------- rover localization and topics (§6) --
RCFG = se.AdapterConfig(drones={"drone_02": "AIR_drone_02"}, rovers=("rover_01",),
                        frames={"VEHICLE_POSE": {SITE, "odom"}}, cameras={"drone_02": ("cam_down_fixture",)},
                        max_age_s=2.0, max_future_skew_s=0.5, telemetry_timeout_s=5.0, site_bounds=(-50, -50, 50, 50))


def rover_pose(msg, seq, dt, boot="rb1", frame="odom", **body):
    return {"msg_id": msg, "kind": "VEHICLE_POSE", "vehicle_id": "rover_01", "boot_id": boot, "seq": seq,
            "stamp_utc": (NOW + timedelta(seconds=dt)).isoformat(),
            "body": {"x_m": 5.5, "y_m": -5.0, "yaw_rad": 1.5708, "frame": frame, "sigma_m": 0.05, **body}}


def test_late_events_and_a_frame_change_are_rejected():
    state = se.AdapterState()
    se.emit([rover_pose("r1", 1, 0.0)], RCFG, state, now=NOW + timedelta(seconds=0.2))
    late = se.emit([rover_pose("r0", 0, -0.5)], RCFG, state, now=NOW + timedelta(seconds=0.3))
    assert any(r.startswith("OUT_OF_ORDER") for x in late["rejected"] for r in x["reasons"])
    changed = se.emit([rover_pose("r2", 2, 0.4, frame=SITE)], RCFG, state, now=NOW + timedelta(seconds=0.5))
    assert any(r.startswith("FRAME_CHANGED") for x in changed["rejected"] for r in x["reasons"])
    rebooted = se.emit([rover_pose("r3", 1, 0.6, boot="rb2", frame=SITE)], RCFG, state, now=NOW + timedelta(seconds=0.7))
    assert not rebooted["rejected"]  # a new boot may legitimately use another frame; identity is re-established


def test_rover_localization_feeds_the_handoff_only_when_accredited_fresh_and_known():
    state = se.AdapterState()
    se.emit([rover_pose("r1", 1, 0.0)], RCFG, state, now=NOW + timedelta(seconds=0.1))
    loc = se.rover_localization(state, RCFG, "rover_01", now=NOW + timedelta(seconds=0.5),
                                ingestion=se.TEST_FIXTURE_INGESTION, accredited_frames={"odom"})
    assert loc["validated"] and loc["vehicle_id"] == "rover_01" and loc["boot_id"] == "rb1" and loc["frame"] == "odom"
    no_transform = se.rover_localization(state, RCFG, "rover_01", now=NOW + timedelta(seconds=0.5),
                                         ingestion=se.TEST_FIXTURE_INGESTION, accredited_frames=set())
    assert no_transform["validated"] is False      # the frame has no accredited transform
    assert se.rover_localization(state, RCFG, "rover_01", now=NOW + timedelta(seconds=30),
                                 ingestion=se.TEST_FIXTURE_INGESTION, accredited_frames={"odom"}) is None


def test_losing_the_rover_blocks_new_executable_requests_in_the_coordinator():
    from tests.test_multiagent_coordinator import signed
    state = se.AdapterState()
    se.emit([rover_pose("r1", 1, 0.0)], RCFG, state, now=NOW + timedelta(seconds=0.1))
    lost = se.emit([], RCFG, state, now=NOW + timedelta(seconds=30))
    assert lost["telemetry"]["rover_01"] == "LOST"
    pre = [e for e in lost["events"] if e["type"] == "EXECUTOR_PRECONDITIONS"]
    assert pre and pre[0]["reasons"][0].startswith("NO_POSITION")
    again = se.emit([], RCFG, state, now=NOW + timedelta(seconds=31))
    assert not [e for e in again["events"] if e["type"] == "EXECUTOR_PRECONDITIONS"]   # reported once, not spammed
    c = through_validated(coord())
    c.handle({"type": "HEARTBEAT", "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=0.5), "task_id": "AIR_drone_02"})
    c.handle({"type": "OBSERVATION", "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=1), "observation": obs("o", dt=1)})
    c.handle({"type": "AERIAL_POINT_REACHED", "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=2),
              "task_id": "AIR_drone_02", "point": "POI_3"})
    c.handle({**pre[0], "at": NOW + timedelta(seconds=3)})
    assert g(c) == "WAITING_FOR_ROVER_LOCALIZATION"
    for phase in ("GROUND_PLANNED", "GROUND_VALIDATED", "AUTHORIZATION_REQUESTED"):
        c.handle({"type": "MISSION_PHASE", "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=4), "phase": phase})
    out = c.handle({"type": "AUTHORIZATION", "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=5), **signed(5)})
    assert out["outcome"] == "REFUSED"


def test_an_event_of_another_drone_or_an_undeclared_topic_is_refused():
    out, _ = run([pose("x", vid="drone_07")])
    assert any(r.startswith("UNKNOWN_VEHICLE") for r in reasons(out))
    with pytest.raises(ValueError, match="UNDECLARED_TOPIC"):
        se.from_topic("/ap/v9/odometry", {}, boot_id="b", seq=1, msg_id="m")


def test_identity_comes_from_the_declared_topic_not_the_message():
    import json
    from pathlib import Path
    msg = json.loads((Path(se.__file__).parent / "fixtures/ros2_like/odometry_drone_02.json").read_text())
    test_map = se.TopicMap({"/rover1/odometry": ("rover_01", "nav_msgs/msg/Odometry")})   # declared by the test
    raw = se.from_topic("/rover1/odometry", msg, topic_map=test_map, boot_id="rb1", seq=1, msg_id="t1")
    assert raw["vehicle_id"] == "rover_01"   # the message said drone_02/base_link: the topic decides


def test_a_withdrawn_target_blocks_its_task():
    c = through_validated(coord())
    c.handle({"type": "HEARTBEAT", "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=0.5), "task_id": "AIR_drone_02"})
    c.handle({"type": "OBSERVATION", "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=1), "observation": obs("o", dt=1)})
    tid = c.ground["G1"]["target_id"]
    out, _ = run([{"msg_id": "w", "kind": "TARGET_WITHDRAWN", "vehicle_id": "drone_02", "boot_id": "b1", "seq": 9,
                   "stamp_utc": (NOW + timedelta(seconds=1.5)).isoformat(),
                   "body": {"target_id": tid, "reason": "card removed"}}], now_dt=2.0)
    for e in out["events"]:
        c.handle(e)
    assert g(c) == "BLOCKED_TARGET_WITHDRAWN"
    assert c.handle({"type": "TARGET_WITHDRAWN", "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=3),
                     "target_id": "nope", "reason": "x"})["outcome"] == "REFUSED"
