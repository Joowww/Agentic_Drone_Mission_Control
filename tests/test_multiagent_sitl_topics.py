"""Known ArduPilot namespaces vs. topics that are NOT accredited, and the injected subscription port (no ROS 2, no
Gazebo). Messages are plain dicts shaped like nav_msgs/msg/Odometry (TEST_FIXTURE)."""
from datetime import timedelta
import math

import pytest

from multiagent import frames2d as f, sitl_events as se
from tests.test_multiagent_coordinator import NOW
from tests.test_multiagent_sitl_events import RCFG

TEST_MAP = se.TopicMap({"/rover1/odometry": ("rover_01", "nav_msgs/msg/Odometry")})   # declared by this test only


def odom(dt, *, frame="odom", x=5.5, y=-5.0, var=0.0025):
    t = NOW + timedelta(seconds=dt)
    sec = int(t.timestamp())
    return {"header": {"stamp": {"sec": sec, "nanosec": int(round((t.timestamp() - sec) * 1e9))}, "frame_id": frame},
            "child_frame_id": "base_link",
            "pose": {"pose": {"position": {"x": x, "y": y, "z": 0.0},
                              "orientation": {"x": 0.0, "y": 0.0, "z": math.sin(math.pi / 4), "w": math.cos(math.pi / 4)}},
                     "covariance": [var, 0, 0, 0, 0, 0, 0, var] + [0] * 28}}


class Port(se.SubscriptionPort):
    def __init__(self, *batches):
        self.batches = list(batches)

    def poll(self):
        return self.batches.pop(0) if self.batches else []


def ingest(port, state, dt):
    return se.ingest(port, TEST_MAP, RCFG, state, now=NOW + timedelta(seconds=dt), ingestion=se.TEST_FIXTURE_INGESTION)


def codes(out):
    return [r for x in out["rejected"] for r in x["reasons"]]


def test_namespaces_are_known_topics_are_recorded_and_nothing_is_ingestible_by_default():
    assert {ns: v["vehicle_id"] for ns, v in se.KNOWN_NAMESPACES.items()} == {
        "/ap/v1": "drone_01", "/ap/v2": "drone_02", "/ap/v3": "rover_01"}
    statuses = {t: se.KNOWN_TOPICS.spec(t).status for t in se.KNOWN_TOPICS.topics}
    assert statuses["/ap/v1/status"] == statuses["/ap/v2/status"] == "BASELINE_CONFIRMED"
    assert statuses["/rover1/odometry"] == statuses["/ap/v3/status"] == "REFERENCED_BY_ROVER_CODE"
    assert not any(s in se.INGESTIBLE for s in statuses.values())
    drone_pose = [t for t in se.KNOWN_TOPICS.topics if se.KNOWN_TOPICS.spec(t).vehicle_id.startswith("drone")
                  and se.KNOWN_TOPICS.spec(t).msg_type is not None]
    assert drone_pose == []                     # no drone pose topic is assumed
    for topic in se.KNOWN_TOPICS.topics:
        with pytest.raises(ValueError, match="TOPIC_NOT_ACCREDITED|COMMAND_TOPIC_NOT_INGESTED"):
            se.from_topic(topic, odom(0), boot_id="b", seq=1, msg_id="m")


def test_a_topic_in_another_vehicles_namespace_or_a_command_topic_is_refused():
    with pytest.raises(ValueError, match="NAMESPACE_VEHICLE_MISMATCH"):
        se.TopicMap({"/ap/v1/pose": ("rover_01", "nav_msgs/msg/Odometry")})
    cmd = se.TopicMap({"/ap/v3/cmd_vel": se.TopicSpec("rover_01", "geometry_msgs/msg/Twist", "DECLARED_BY_TEST", "t",
                                                      direction="COMMAND")})
    with pytest.raises(ValueError, match="COMMAND_TOPIC_NOT_INGESTED"):
        se.from_topic("/ap/v3/cmd_vel", {}, topic_map=cmd, boot_id="b", seq=1, msg_id="m")


def test_the_port_reports_refused_topics_duplicates_late_stale_and_frame_changes():
    state = se.AdapterState()
    first = ingest(Port([("/rover1/odometry", odom(0.0), "rb1", 1, "o1"),
                         ("/ap/v9/odometry", odom(0.0), "x", 1, "u1")]), state, 0.2)
    assert [e["type"] for e in first["events"]] == [] and state.rover_pose["rover_01"]["frame"] == "odom"
    assert first["rejected"][0]["topic"] == "/ap/v9/odometry" and codes(first)[0].startswith("UNDECLARED_TOPIC")
    later = ingest(Port([("/rover1/odometry", odom(0.0), "rb1", 1, "o1"),            # the same message again
                         ("/rover1/odometry", odom(-0.1), "rb1", 0, "o0"),           # older sequence
                         ("/rover1/odometry", odom(-10.0), "rb1", 5, "o5"),          # too old
                         ("/rover1/odometry", odom(0.3, frame="map"), "rb1", 6, "o6")]), state, 0.4)
    got = codes(later)
    for prefix in ("DUPLICATE_MESSAGE", "OUT_OF_ORDER", "STALE", "FRAME_NOT_ALLOWED"):
        assert any(r.startswith(prefix) for r in got), (prefix, got)


def test_a_new_boot_reestablishes_identity_and_an_old_boot_pose_is_refused_by_the_frames_check():
    state = se.AdapterState()
    ingest(Port([("/rover1/odometry", odom(0.0), "rb1", 1, "o1")]), state, 0.1)
    ingest(Port([("/rover1/odometry", odom(0.2), "rb2", 1, "o2")]), state, 0.3)
    loc = se.rover_localization(state, RCFG, "rover_01", now=NOW + timedelta(seconds=0.4),
                                ingestion=se.TEST_FIXTURE_INGESTION, accredited_frames={"odom"})
    assert loc["boot_id"] == "rb2" and loc["vehicle_id"] == "rover_01"
    graph = f.FrameGraph([f.Transform(parent="synthetic_orchard_local", child="odom", x_m=1.0, y_m=-1.5,
                                      yaw_rad=math.pi / 2, sigma_m=0.02, sigma_rad=0.001,
                                      not_before=NOW - timedelta(hours=1), expires=NOW + timedelta(hours=1),
                                      source="TEST_FIXTURE", source_sha256="e" * 64, accredited=True)])
    out = f.goal_for_rover({"frame": "synthetic_orchard_local", "x_m": 8.0, "y_m": 4.0, "sigma_m": 0.12}, graph,
                           rover_frame="odom", localization=loc, limits={"max_total_sigma_m": 0.5,
                           "localization_max_age_s": 2.0, "max_distance_m": 5.0}, now=NOW + timedelta(seconds=0.4),
                           authorized_area=[(-10, -10), (30, -10), (30, 30), (-10, 30)],
                           rover_identity={"vehicle_id": "rover_01", "boot_id": "rb1"}, apply=False)
    assert any(r.startswith("ROVER_BOOT_CHANGED") for r in out["reasons"])


def test_losing_the_rover_through_the_port_yields_no_position_once_and_no_localization():
    state = se.AdapterState()
    ingest(Port([("/rover1/odometry", odom(0.0), "rb1", 1, "o1")]), state, 0.1)
    lost = ingest(Port([]), state, 30.0)
    assert [e["reasons"] for e in lost["events"]] == [["NO_POSITION: rover rover_01 telemetry LOST"]]
    assert ingest(Port([]), state, 40.0)["events"] == []          # once, not on every poll
    assert se.rover_localization(state, RCFG, "rover_01", now=NOW + timedelta(seconds=30),
                                 ingestion=se.TEST_FIXTURE_INGESTION, accredited_frames={"odom"}) is None
