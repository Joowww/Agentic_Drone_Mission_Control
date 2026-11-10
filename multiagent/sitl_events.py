"""Input adapter: typed vehicle/camera events (future Gazebo / ArduPilot / ROS 2 ingestion) -> coordinator events.
No connection is opened here; ROS 2, MAVLink and Gazebo are not imported. Five separate parts:

  parse()      raw dict -> RawEvent (shape and types only)
  validate()   identity, frame, pose, time, sequence, boot, duplicates, vehicle state, sensor accreditation
  normalize()  accepted event -> coordinator event(s) (HEARTBEAT, OBSERVATION, AERIAL_POINT_REACHED,
               AERIAL_TASK_ABORTED, VEHICLE_IDENTITY)
  provenance   the ACCREDITATION comes from the ingestion component that delivers the event (IngestionSource),
               never from the message: a message saying source="SITL" is recorded as a claim, nothing more
  emit()       events for the coordinator + structured rejections; telemetry loss is reported, never filled in

Today the only accredited ingestion is TEST_FIXTURE (the coordinator accepts only TEST_FIXTURE events). A real
SITL ingestion becomes accredited only by adding its component, with its own tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import math

KINDS = ("VEHICLE_POSE", "VEHICLE_STATE", "DETECTION", "POINT_REACHED", "TARGET_WITHDRAWN")
VEHICLE_STATES = ("IDLE", "FLYING", "DRIVING", "HOLDING", "LANDED", "ABORTED")
REQUIRED = {"VEHICLE_POSE": ("x_m", "y_m", "yaw_rad", "frame"), "VEHICLE_STATE": ("state",),
            "DETECTION": ("observation",), "POINT_REACHED": ("point",), "TARGET_WITHDRAWN": ("target_id", "reason")}


@dataclass(frozen=True)
class IngestionSource:
    """A component that hands events to the adapter. Only an accredited one can produce coordinator events; its
    coordinator_source is the event source the coordinator sees, and observation_kind what observations may claim."""
    name: str
    accredited: bool
    coordinator_source: str
    observation_kind: str


TEST_FIXTURE_INGESTION = IngestionSource("TEST_FIXTURE_INGESTION", True, "TEST_FIXTURE", "TEST_FIXTURE")


@dataclass(frozen=True)
class RawEvent:
    msg_id: str
    kind: str
    vehicle_id: str
    boot_id: str
    seq: int
    stamp: datetime
    frame: str | None
    body: dict
    claimed_source: str | None


@dataclass
class AdapterState:
    """What the adapter remembers between events (per vehicle: boot and last sequence; seen message ids)."""
    seen: set = field(default_factory=set)
    boot: dict = field(default_factory=dict)
    last_seq: dict = field(default_factory=dict)
    last_stamp: dict = field(default_factory=dict)
    frame: dict = field(default_factory=dict)          # vehicle -> frame of its poses in the current boot
    rover_pose: dict = field(default_factory=dict)     # rover -> last accepted pose (for the hand-off's localization)
    telemetry: dict = field(default_factory=dict)      # vehicle -> last telemetry status reported


@dataclass(frozen=True)
class AdapterConfig:
    drones: dict            # vehicle_id -> aerial task id it reports for
    rovers: tuple           # declared rover ids
    frames: dict            # kind -> allowed frame(s)
    cameras: dict           # vehicle_id -> accredited camera ids
    max_age_s: float
    max_future_skew_s: float
    telemetry_timeout_s: float
    site_bounds: tuple      # (xmin, ymin, xmax, ymax) in the site frame, for pose plausibility


def parse(raw) -> tuple[RawEvent | None, list[str]]:
    if not isinstance(raw, dict):
        return None, ["PARSE: not an object"]
    errs = []
    for k in ("msg_id", "kind", "vehicle_id", "boot_id", "seq", "stamp_utc", "body"):
        if k not in raw:
            errs.append(f"PARSE: missing {k}")
    if errs:
        return None, errs
    if raw["kind"] not in KINDS:
        return None, [f"PARSE: unknown kind {raw['kind']!r}"]
    if type(raw["seq"]) is not int or raw["seq"] < 0:
        return None, ["PARSE: seq must be a non-negative integer"]
    try:
        stamp = datetime.fromisoformat(raw["stamp_utc"])
        if stamp.tzinfo is None:
            raise ValueError
    except (TypeError, ValueError):
        return None, ["PARSE: stamp_utc must be an ISO time with a timezone"]
    if not isinstance(raw["body"], dict):
        return None, ["PARSE: body must be an object"]
    missing = [k for k in REQUIRED[raw["kind"]] if k not in raw["body"]]
    if missing:
        return None, [f"PARSE: {raw['kind']} needs {missing}"]
    return RawEvent(str(raw["msg_id"]), raw["kind"], str(raw["vehicle_id"]), str(raw["boot_id"]), raw["seq"], stamp,
                    raw["body"].get("frame"), raw["body"], raw.get("source")), []


def validate(ev: RawEvent, cfg: AdapterConfig, state: AdapterState, *, now: datetime,
             ingestion: IngestionSource) -> list[str]:
    """Every reason not to forward the event; also updates the per-vehicle sequence/boot state when accepted."""
    out = []
    if not ingestion.accredited:
        out.append(f"INGESTION_NOT_ACCREDITED: {ingestion.name} (claimed source {ev.claimed_source!r} is not evidence)")
    if ev.vehicle_id not in cfg.drones and ev.vehicle_id not in cfg.rovers:
        out.append(f"UNKNOWN_VEHICLE: {ev.vehicle_id}")
    if ev.msg_id in state.seen:
        out.append("DUPLICATE_MESSAGE")
    age = (now - ev.stamp).total_seconds()
    if age < -cfg.max_future_skew_s:
        out.append(f"FROM_THE_FUTURE: {age:.3f} s")
    elif age > cfg.max_age_s:
        out.append(f"STALE: {age:.3f} s > {cfg.max_age_s} s")
    key = ev.vehicle_id
    boot_changed = key in state.boot and state.boot[key] != ev.boot_id
    if not boot_changed and key in state.last_seq and ev.seq <= state.last_seq[key]:
        out.append(f"OUT_OF_ORDER: seq {ev.seq} <= {state.last_seq[key]}")
    if ev.kind == "VEHICLE_POSE" and not boot_changed and key in state.frame and ev.frame != state.frame[key]:
        out.append(f"FRAME_CHANGED: {state.frame[key]!r} -> {ev.frame!r} within boot {ev.boot_id}")
    allowed = cfg.frames.get(ev.kind)
    if allowed is not None and ev.frame not in allowed:
        out.append(f"FRAME_NOT_ALLOWED: {ev.frame!r} for {ev.kind} (allowed {sorted(allowed)})")
    b = ev.body
    if ev.kind == "VEHICLE_POSE":
        if not all(isinstance(b.get(k), (int, float)) and math.isfinite(b[k]) for k in ("x_m", "y_m", "yaw_rad")):
            out.append("POSE_NOT_FINITE")
        else:
            x0, y0, x1, y1 = cfg.site_bounds
            if not (x0 <= b["x_m"] <= x1 and y0 <= b["y_m"] <= y1):
                out.append("POSE_OUTSIDE_SITE_BOUNDS")
            if "sigma_m" in b and not (isinstance(b["sigma_m"], (int, float)) and b["sigma_m"] >= 0):
                out.append("POSE_UNCERTAINTY_INVALID")
    if ev.kind == "VEHICLE_STATE" and b.get("state") not in VEHICLE_STATES:
        out.append(f"VEHICLE_STATE_UNKNOWN: {b.get('state')!r}")
    if ev.kind == "DETECTION":
        cam = ((b.get("observation") or {}).get("observer") or {}).get("camera_id")
        if cam not in cfg.cameras.get(ev.vehicle_id, ()):
            out.append(f"SENSOR_NOT_ACCREDITED: {cam!r} on {ev.vehicle_id}")
        kind = ((b.get("observation") or {}).get("source") or {}).get("kind")
        if kind != ingestion.observation_kind:
            out.append(f"OBSERVATION_PROVENANCE_INCONSISTENT: {kind!r} through {ingestion.name}")
        if ((b.get("observation") or {}).get("observer") or {}).get("vehicle_id") != ev.vehicle_id:
            out.append("OBSERVER_MISMATCH")
    if not out:
        state.seen.add(ev.msg_id)
        state.boot[key], state.last_seq[key], state.last_stamp[key] = ev.boot_id, ev.seq, ev.stamp
        if ev.kind == "VEHICLE_POSE":
            state.frame[key] = ev.frame
            if key in cfg.rovers:
                state.rover_pose[key] = {"vehicle_id": key, "boot_id": ev.boot_id, "frame": ev.frame, "x_m": b["x_m"],
                                         "y_m": b["y_m"], "yaw_rad": b["yaw_rad"], "sigma_m": b.get("sigma_m"),
                                         "observed_at": ev.stamp, "ingestion": ingestion.name, "msg_id": ev.msg_id}
    return out


def normalize(ev: RawEvent, cfg: AdapterConfig, *, ingestion: IngestionSource, boot_changed: bool) -> list[dict]:
    src, at = ingestion.coordinator_source, ev.stamp
    base = {"source": src, "at": at, "event_id": f"{ev.vehicle_id}:{ev.boot_id}:{ev.msg_id}",
            "provenance": {"ingestion": ingestion.name, "claimed_source": ev.claimed_source, "msg_id": ev.msg_id,
                           "boot_id": ev.boot_id, "seq": ev.seq}}
    events = []
    if boot_changed:  # a new incarnation of the vehicle: identity is re-established, never assumed continuous
        events.append({**base, "type": "VEHICLE_IDENTITY", "vehicle_id": f"{ev.vehicle_id}@boot:{ev.boot_id}",
                       "event_id": base["event_id"] + ":identity"})
    task = cfg.drones.get(ev.vehicle_id)
    if ev.kind in ("VEHICLE_POSE", "VEHICLE_STATE") and task:
        if ev.kind == "VEHICLE_STATE" and ev.body["state"] == "ABORTED":
            events.append({**base, "type": "AERIAL_TASK_ABORTED", "task_id": task})
        else:
            events.append({**base, "type": "HEARTBEAT", "task_id": task})
    elif ev.kind == "POINT_REACHED" and task:
        events.append({**base, "type": "AERIAL_POINT_REACHED", "task_id": task, "point": ev.body["point"]})
    elif ev.kind == "DETECTION":
        events.append({**base, "type": "OBSERVATION", "observation": ev.body["observation"]})
    elif ev.kind == "TARGET_WITHDRAWN":
        events.append({**base, "type": "TARGET_WITHDRAWN", "target_id": ev.body["target_id"], "reason": ev.body["reason"]})
    return events


def emit(raws: list, cfg: AdapterConfig, state: AdapterState, *, now: datetime,
         ingestion: IngestionSource = TEST_FIXTURE_INGESTION) -> dict:
    """Coordinator events + structured rejections + telemetry status for each drone (LOST when silent too long)."""
    events, rejected = [], []
    for raw in raws:
        ev, errs = parse(raw)
        if ev is None:
            rejected.append({"msg_id": (raw or {}).get("msg_id") if isinstance(raw, dict) else None, "reasons": errs})
            continue
        boot_changed = ev.vehicle_id in state.boot and state.boot[ev.vehicle_id] != ev.boot_id
        errs = validate(ev, cfg, state, now=now, ingestion=ingestion)
        if errs:
            rejected.append({"msg_id": ev.msg_id, "vehicle_id": ev.vehicle_id, "reasons": errs})
            continue
        events.extend(normalize(ev, cfg, ingestion=ingestion, boot_changed=boot_changed))
    telemetry = {}
    for vid in list(cfg.drones) + list(cfg.rovers):
        last = state.last_stamp.get(vid)
        telemetry[vid] = "NEVER_RECEIVED" if last is None else (
            "LOST" if (now - last) > timedelta(seconds=cfg.telemetry_timeout_s) else "OK")
        if vid in cfg.rovers and telemetry[vid] == "LOST" and state.telemetry.get(vid) == "OK":
            # the rover's localization was lost: it can no longer be the target of an executable request
            events.append({"type": "EXECUTOR_PRECONDITIONS", "source": ingestion.coordinator_source, "at": now,
                           "reasons": [f"NO_POSITION: rover {vid} telemetry {telemetry[vid]}"],
                           "event_id": f"{vid}:telemetry:{telemetry[vid]}:{now.isoformat()}"})
    state.telemetry.update(telemetry)
    return {"events": sorted(events, key=lambda e: e["at"]), "rejected": rejected, "telemetry": telemetry}


def rover_localization(state: AdapterState, cfg: AdapterConfig, vehicle_id: str, *, now: datetime,
                       ingestion: IngestionSource, accredited_frames: set) -> dict | None:
    """The rover's latest pose in the frames2d/hand-off shape, or None. validated only when the ingestion is accredited,
    the frame is one with an accredited transform, and the pose is fresh; a missing value is never filled in."""
    pose = state.rover_pose.get(vehicle_id)
    if pose is None or (now - pose["observed_at"]) > timedelta(seconds=cfg.telemetry_timeout_s):
        return None
    if pose.get("sigma_m") is None:
        return None
    return {**pose, "validated": bool(ingestion.accredited and pose["frame"] in accredited_frames),
            "source": f"{ingestion.name}:{pose['msg_id']}",
            "source_sha256": __import__("hashlib").sha256(repr(sorted(pose.items(), key=str)).encode()).hexdigest()}


# ------------------------------------------------- declared topic map (ROS 2 / ArduPilot DDS; identity by topic) --
# Namespaces CONFIRMED by the validated multi-vehicle baseline (read-only; feature/ardupilot-ros2 7e8855f6a,
# simulation/ros2_gazebo/results/validation_3_vehicles.md and scripts/check_sim.sh). A namespace is not a topic:
# the baseline lists /ap/vN/status and services, and NO pose/odometry topic for the drones.
KNOWN_NAMESPACES = {"/ap/v1": {"vehicle_id": "drone_01", "sysid": 1, "autopilot": "ArduCopter"},
                    "/ap/v2": {"vehicle_id": "drone_02", "sysid": 2, "autopilot": "ArduCopter"},
                    "/ap/v3": {"vehicle_id": "rover_01", "sysid": 3, "autopilot": "ArduRover"}}
BASELINE = "feature/ardupilot-ros2 7e8855f6a"
# topic statuses: only the last two can be ingested; the others are recorded knowledge, not accreditation
TOPIC_STATUSES = ("BASELINE_CONFIRMED", "REFERENCED_BY_ROVER_CODE", "ACCREDITED_BY_INGESTION", "DECLARED_BY_TEST")
INGESTIBLE = ("ACCREDITED_BY_INGESTION", "DECLARED_BY_TEST")


@dataclass(frozen=True)
class TopicSpec:
    vehicle_id: str
    msg_type: str | None      # None: the message type is not confirmed (nothing is parsed from it)
    status: str
    evidence: str
    direction: str = "TELEMETRY"   # COMMAND topics (e.g. cmd_vel) are never ingested


def _namespace(topic: str) -> str | None:
    parts = topic.split("/")
    return "/".join(parts[:3]) if len(parts) > 2 and parts[1] == "ap" else None


@dataclass(frozen=True)
class TopicMap:
    """Topic -> TopicSpec, DECLARED by the ingestion configuration. The vehicle identity comes from here, never from
    the message. A plain (vehicle_id, msg_type) tuple is a DECLARED_BY_TEST entry. A topic under a known /ap/vN
    namespace must name that namespace's vehicle (checked when the map is built)."""
    topics: dict

    def __post_init__(self):
        for topic, spec in self.topics.items():
            spec = self.spec(topic)
            if spec.status not in TOPIC_STATUSES:
                raise ValueError(f"TOPIC_STATUS_UNKNOWN: {topic}: {spec.status}")
            ns = _namespace(topic)
            if ns in KNOWN_NAMESPACES and KNOWN_NAMESPACES[ns]["vehicle_id"] != spec.vehicle_id:
                raise ValueError(f"NAMESPACE_VEHICLE_MISMATCH: {topic} is {KNOWN_NAMESPACES[ns]['vehicle_id']}'s "
                                 f"namespace, declared for {spec.vehicle_id}")

    def spec(self, topic: str) -> TopicSpec | None:
        s = self.topics.get(topic)
        if isinstance(s, tuple):
            return TopicSpec(s[0], s[1], "DECLARED_BY_TEST", "test configuration")
        return s


KNOWN_TOPICS = TopicMap({
    "/ap/v1/status": TopicSpec("drone_01", None, "BASELINE_CONFIRMED", f"{BASELINE} scripts/check_sim.sh (topic list)"),
    "/ap/v2/status": TopicSpec("drone_02", None, "BASELINE_CONFIRMED", f"{BASELINE} scripts/check_sim.sh (topic list)"),
    "/ap/v3/cmd_vel": TopicSpec("rover_01", None, "BASELINE_CONFIRMED",
                                f"{BASELINE} results/validation_3_vehicles.md (subscription)", direction="COMMAND"),
    "/ap/v3/status": TopicSpec("rover_01", None, "REFERENCED_BY_ROVER_CODE",
                               "2e206f1fa tools/rover_control.py, tools/rover_environment_identity.py"),
    "/rover1/odometry": TopicSpec("rover_01", "nav_msgs/msg/Odometry", "REFERENCED_BY_ROVER_CODE",
                                  "2e206f1fa tools/rover_control.py (ros_gz_bridge from /model/rover1/odometry)"),
})
DEFAULT_TOPICS = KNOWN_TOPICS   # what is KNOWN; nothing in it is accredited for ingestion


def from_topic(topic: str, msg: dict, *, topic_map: TopicMap = KNOWN_TOPICS, boot_id: str, seq: int,
               msg_id: str) -> dict:
    spec = topic_map.spec(topic)
    if spec is None:
        raise ValueError(f"UNDECLARED_TOPIC: {topic}")
    if spec.direction == "COMMAND":
        raise ValueError(f"COMMAND_TOPIC_NOT_INGESTED: {topic}")
    if spec.status not in INGESTIBLE:
        raise ValueError(f"TOPIC_NOT_ACCREDITED: {topic} is {spec.status} ({spec.evidence})")
    if spec.msg_type is None:
        raise ValueError(f"MESSAGE_TYPE_NOT_CONFIRMED: {topic}")
    raw = from_ros2(spec.msg_type, msg, vehicle_id=spec.vehicle_id, boot_id=boot_id, seq=seq, msg_id=msg_id)
    raw["topic"] = {"name": topic, "status": spec.status}
    return raw


# --------------------------------------------- injected subscription port (no ROS 2 import; a test double or, later,
# the rover's accredited ingestion implements it) --
class SubscriptionPort:
    """poll() -> list of (topic, message dict, boot_id, seq, msg_id). Implemented outside this module."""

    def poll(self) -> list[tuple]:  # pragma: no cover - interface
        raise NotImplementedError


def ingest(port: SubscriptionPort, topic_map: TopicMap, cfg: AdapterConfig, state: AdapterState, *, now: datetime,
           ingestion: IngestionSource) -> dict:
    """Port -> topic map -> parse/validate/normalize -> coordinator events. A topic refused by the map is reported
    (never silently dropped) and produces no event."""
    raws, refused = [], []
    for topic, msg, boot_id, seq, msg_id in port.poll():
        try:
            raws.append(from_topic(topic, msg, topic_map=topic_map, boot_id=boot_id, seq=seq, msg_id=msg_id))
        except (ValueError, KeyError, TypeError) as exc:
            refused.append({"msg_id": msg_id, "topic": topic, "reasons": [str(exc)]})
    out = emit(raws, cfg, state, now=now, ingestion=ingestion)
    out["rejected"] = refused + out["rejected"]
    return out


# --------------------------------------------- ROS 2-shaped messages (plain dicts; ROS 2 is NOT imported) --
def _stamp(header: dict) -> str:
    from datetime import timezone
    st = header["stamp"]
    return datetime.fromtimestamp(st["sec"] + st["nanosec"] * 1e-9, tz=timezone.utc).isoformat()


def _yaw(q: dict) -> float:
    return math.atan2(2.0 * (q["w"] * q["z"] + q["x"] * q["y"]), 1.0 - 2.0 * (q["y"] ** 2 + q["z"] ** 2))


def from_ros2(msg_type: str, msg: dict, *, vehicle_id: str, boot_id: str, seq: int, msg_id: str) -> dict:
    """A ROS 2 message given as a plain dict (as rosbag2/JSON would carry it) -> the adapter's raw event. Only the
    shapes listed are understood; anything else is refused. The provenance is still the ingestion component's."""
    if msg_type == "nav_msgs/msg/Odometry":
        p, q = msg["pose"]["pose"]["position"], msg["pose"]["pose"]["orientation"]
        cov = msg["pose"].get("covariance") or [0.0] * 36
        sigma = math.sqrt(max(cov[0], cov[7])) if len(cov) == 36 and cov[0] >= 0 and cov[7] >= 0 else None
        body = {"x_m": p["x"], "y_m": p["y"], "yaw_rad": _yaw(q), "frame": msg["header"]["frame_id"],
                "child_frame": msg.get("child_frame_id")}
        if sigma is not None:
            body["sigma_m"] = sigma
        kind = "VEHICLE_POSE"
    elif msg_type == "tfg_msgs/msg/VehicleState":  # a declared interface for the future ingestion, not a ROS standard
        body, kind = {"state": msg["state"]}, "VEHICLE_STATE"
    elif msg_type == "tfg_msgs/msg/CardObservation":
        body, kind = {"observation": msg["observation"]}, "DETECTION"
    else:
        raise ValueError(f"UNSUPPORTED_ROS2_TYPE: {msg_type}")
    return {"msg_id": msg_id, "kind": kind, "vehicle_id": vehicle_id, "boot_id": boot_id, "seq": seq,
            "stamp_utc": _stamp(msg["header"]), "body": body, "source": msg.get("_claimed_source")}
