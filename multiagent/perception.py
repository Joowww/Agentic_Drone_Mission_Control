"""Drone -> rover observation contract (tfg.multiagent.observation/1) and the deterministic gate that turns ONE
observation into a ground target the Rover Agent may plan to, or refuses it with reasons.

Goal of the TFG: a drone sees a red or yellow card and the rover goes there. Nothing here runs a camera, ROS 2,
SLAM or a vehicle: it fixes WHAT an observation must carry and HOW it is checked, so a future perception node
(e.g. an OAK-D on the drone) can plug in. Fixtures are labelled TEST_FIXTURE and never pass as sensor data.

Frames (all metres, right-handed):
- camera optical frame (camera_frame_id): x right, y down, z forward (REP 103 optical convention);
- the site's local frame (site.local_frame.frame_id, ENU-like, z up) is the common map; the camera pose MUST be
  given in it (position + unit quaternion x, y, z, w rotating optical-frame vectors into the map).
Pixel coordinates alone never give a position: a 3D point needs metric depth (stereo / ToF) or an explicit
relative position, plus the camera pose at that instant. A global coordinate is never derived from pixels.

Gate (ground_target_from_observation), every check recorded, the first failures returned:
schema; declared observer drone and camera; class red_card | yellow_card; confidence >= min; not from the future;
age <= min(valid_for_s, max_age_s); metric 3D point; camera pose in the site frame, close in time to the image,
unit quaternion; combined position uncertainty known and <= max; target inside the operation perimeter and the
rover drivable area (existing site_validation); matched to a declared POI within poi_match_m (the rover planner
only plans to declared points); source REAL_SENSOR needs evidence, TEST_FIXTURE only when fixtures are allowed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA = "tfg.multiagent.observation/1"
TARGET_CLASSES = ("red_card", "yellow_card")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Observer(_Strict):
    vehicle_id: str = Field(min_length=1, max_length=40)
    camera_id: str = Field(min_length=1, max_length=60)
    camera_model: str | None = Field(None, max_length=80)


class Detection(_Strict):
    object_class: str = Field(min_length=1, max_length=40)
    confidence: float = Field(ge=0.0, le=1.0)
    # what "confidence" is: a colour detector's HEURISTIC_QUALITY is not a CALIBRATED_PROBABILITY
    score_kind: Literal["CALIBRATED_PROBABILITY", "HEURISTIC_QUALITY", "UNSPECIFIED"] = "UNSPECIFIED"
    target_id: str = Field(min_length=1, max_length=60)  # identity of the physical target (e.g. card_red_1)


class ImagePoint(_Strict):
    u_px: float = Field(ge=0)
    v_px: float = Field(ge=0)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)


class Intrinsics(_Strict):
    fx: float = Field(gt=0)
    fy: float = Field(gt=0)
    cx: float = Field(ge=0)
    cy: float = Field(ge=0)


class Depth(_Strict):
    depth_m: float = Field(gt=0, le=200)
    # GROUND_PLANE_ASSUMPTION: the depth of the intersection of the pixel ray with a declared flat ground plane; an
    # explicit, testable hypothesis (multiagent.geometry), accepted only when the policy allows it
    source: Literal["STEREO", "TOF", "LIDAR", "MONOCULAR_ESTIMATE", "GROUND_PLANE_ASSUMPTION"]


class Pose(_Strict):
    frame_id: str = Field(min_length=1)
    position_m: tuple[float, float, float]
    orientation_xyzw: tuple[float, float, float, float]
    stamp_utc: datetime
    source: Literal["VEHICLE_EKF", "MOCAP", "SLAM", "SITL_GROUND_TRUTH", "TEST_FIXTURE"]
    position_sigma_m: float | None = Field(None, ge=0)


class Source(_Strict):
    kind: Literal["REAL_SENSOR", "SITL_SENSOR", "TEST_FIXTURE"]
    device: str = Field(min_length=1, max_length=80)
    evidence_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")  # raw frame / bag the detection came from


class Observation(_Strict):
    schema_: Literal["tfg.multiagent.observation/1"] = Field(SCHEMA, alias="schema")
    observation_id: str = Field(min_length=1, max_length=80)
    observer: Observer
    stamp_utc: datetime
    detection: Detection
    image: ImagePoint
    intrinsics: Intrinsics | None = None
    depth: Depth | None = None
    relative_position_m: tuple[float, float, float] | None = None  # in the camera optical frame, if measured
    camera_frame_id: str = Field(min_length=1)
    camera_pose: Pose | None = None
    detection_sigma_m: float | None = Field(None, ge=0)  # position uncertainty of the detection itself
    camera_calibration: Literal["CALIBRATED", "DECLARED_VIRTUAL", "UNCALIBRATED"] | None = None
    valid_for_s: float = Field(gt=0, le=3600)
    source: Source

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    @field_validator("stamp_utc")
    @classmethod
    def _aware(cls, v):
        if v.tzinfo is None:
            raise ValueError("stamp_utc must carry a timezone")
        return v


class Policy(_Strict):
    min_confidence: float = Field(0.8, ge=0, le=1)  # for CALIBRATED_PROBABILITY / UNSPECIFIED scores
    # a HEURISTIC_QUALITY score (e.g. the colour detector's fill x saturation) is not a probability: its own threshold
    min_heuristic_quality: float = Field(0.5, ge=0, le=1)
    max_age_s: float = Field(30.0, gt=0)
    max_future_skew_s: float = Field(1.0, ge=0)
    max_pose_skew_s: float = Field(0.1, ge=0)
    max_sigma_m: float = Field(0.5, gt=0)
    poi_match_m: float = Field(1.0, gt=0)
    allow_monocular_depth: bool = False
    allow_ground_plane: bool = False
    require_calibrated_camera: bool = False
    allow_fixtures: bool = False


def _rotate(q, v):
    x, y, z, w = q
    # v' = q v q*, expanded for a unit quaternion
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx))


def camera_point(obs: Observation) -> tuple[tuple[float, float, float] | None, str]:
    """3D point in the camera optical frame, and how it was obtained (or why not)."""
    if obs.relative_position_m is not None:
        return tuple(obs.relative_position_m), "RELATIVE_POSITION_GIVEN"
    if obs.depth is None:
        return None, "NO_METRIC_DEPTH: pixels alone do not give a position"
    if obs.intrinsics is None:
        return None, "NO_INTRINSICS: depth without camera intrinsics cannot be back-projected"
    k, d = obs.intrinsics, obs.depth.depth_m
    return ((obs.image.u_px - k.cx) / k.fx * d, (obs.image.v_px - k.cy) / k.fy * d, d), f"BACK_PROJECTED_{obs.depth.source}"


def to_map(obs: Observation) -> tuple[float, float, float] | None:
    p, _ = camera_point(obs)
    if p is None or obs.camera_pose is None:
        return None
    r = _rotate(obs.camera_pose.orientation_xyzw, p)
    t = obs.camera_pose.position_m
    return (t[0] + r[0], t[1] + r[1], t[2] + r[2])


def ground_target_from_observation(raw, *, site, context, fleet, now: datetime, policy: Policy | None = None,
                                   camera_ids: dict | None = None) -> dict:
    """{"status": ACCEPTED | REFUSED, "checks": [...], "reasons": [...], "target": {...} | None}.
    ``camera_ids``: {drone_id: [camera ids]} declared for the fleet (None: not declared -> refused)."""
    from planning.site_validation import validate_ground_local_target
    from planning.site_geometry import INSIDE, point_location
    policy = policy or Policy()
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        return ok

    try:
        obs = raw if isinstance(raw, Observation) else Observation.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - schema errors are a refusal, never an exception for the caller
        return {"status": "REFUSED", "checks": [{"check": "schema", "status": "FAIL", "detail": str(exc)[:400]}],
                "reasons": ["SCHEMA_INVALID"], "target": None, "observation_id": None}
    drones = {d.vehicle_id for d in context.drones}
    check("observer is a declared drone", obs.observer.vehicle_id in drones, obs.observer.vehicle_id)
    cams = (camera_ids or {}).get(obs.observer.vehicle_id)
    check("camera declared for that drone", bool(cams) and obs.observer.camera_id in cams,
          f"{obs.observer.camera_id} vs {cams}")
    check("target class", obs.detection.object_class in TARGET_CLASSES, obs.detection.object_class)
    if obs.detection.score_kind == "HEURISTIC_QUALITY":
        check("heuristic quality (not a probability)", obs.detection.confidence >= policy.min_heuristic_quality,
              f"{obs.detection.confidence} vs min {policy.min_heuristic_quality}")
    else:
        check("confidence", obs.detection.confidence >= policy.min_confidence,
              f"{obs.detection.confidence} vs min {policy.min_confidence}")
    age = (now - obs.stamp_utc).total_seconds()
    check("not from the future", age >= -policy.max_future_skew_s, f"age {age:.3f} s")
    check("fresh", age <= min(obs.valid_for_s, policy.max_age_s),
          f"age {age:.3f} s vs valid_for {obs.valid_for_s} s and max {policy.max_age_s} s")
    point, how = camera_point(obs)
    monocular = obs.depth is not None and obs.depth.source == "MONOCULAR_ESTIMATE" and obs.relative_position_m is None
    plane = obs.depth is not None and obs.depth.source == "GROUND_PLANE_ASSUMPTION" and obs.relative_position_m is None
    check("metric 3D point", point is not None and (not monocular or policy.allow_monocular_depth)
          and (not plane or policy.allow_ground_plane), how + (" (ground-plane hypothesis not allowed by the policy)"
                                                               if plane and not policy.allow_ground_plane else ""))
    if policy.require_calibrated_camera:
        check("calibrated camera", obs.camera_calibration == "CALIBRATED", str(obs.camera_calibration))
    # sensor data never presumes a calibration: a real camera must be CALIBRATED, a simulated one at least declared
    if obs.source.kind == "REAL_SENSOR":
        check("calibrated camera (real sensor)", obs.camera_calibration == "CALIBRATED", str(obs.camera_calibration))
    elif obs.source.kind == "SITL_SENSOR":
        check("declared or calibrated camera (simulated sensor)",
              obs.camera_calibration in ("CALIBRATED", "DECLARED_VIRTUAL"), str(obs.camera_calibration))
    pose = obs.camera_pose
    if check("camera pose given", pose is not None, "camera pose in the site frame at capture time"):
        check("pose in the site frame", pose.frame_id == site.local_frame.frame_id,
              f"{pose.frame_id} vs {site.local_frame.frame_id}")
        skew = abs((pose.stamp_utc - obs.stamp_utc).total_seconds())
        check("pose close in time to the image", skew <= policy.max_pose_skew_s, f"{skew:.3f} s vs {policy.max_pose_skew_s} s")
        norm = math.sqrt(sum(c * c for c in pose.orientation_xyzw))
        check("unit quaternion", abs(norm - 1) <= 1e-3, f"norm {norm:.6f}")
        fixture_pose = pose.source == "TEST_FIXTURE"
        check("pose source consistent with the observation source",
              fixture_pose == (obs.source.kind == "TEST_FIXTURE"), f"{pose.source} / {obs.source.kind}")
    sigmas = [obs.detection_sigma_m, pose.position_sigma_m if pose else None]
    sigma = math.sqrt(sum(s * s for s in sigmas)) if all(s is not None for s in sigmas) else None
    check("position uncertainty known and small", sigma is not None and sigma <= policy.max_sigma_m,
          f"sigma {sigma if sigma is None else round(sigma, 3)} m vs max {policy.max_sigma_m} m")
    if obs.source.kind == "TEST_FIXTURE":
        check("fixtures allowed", policy.allow_fixtures, "TEST_FIXTURE observations only in fixture mode")
    else:
        check("sensor evidence", obs.source.evidence_sha256 is not None, "raw evidence hash of the frame/bag")
    target_xyz = to_map(obs) if all(c["status"] == "PASS" for c in checks) else None
    target, matched = None, None
    if target_xyz is not None:
        xy = (round(target_xyz[0], 3), round(target_xyz[1], 3))
        perimeter = site.operation_perimeter.polygon
        check("inside the operation perimeter", perimeter is not None and point_location(xy, perimeter) == INSIDE, str(xy))
        rover = next(iter(context.rovers), None)
        ground = validate_ground_local_target(site, rover.start_point, xy, context.planning_margin_m,
                                              fleet.vehicle(rover.vehicle_id)) if rover else {"status": "FAIL", "checks": []}
        check("ground route to the target (straight line, drivable area, exclusions)", ground["status"] == "PASS",
              [f"{c['check']}: {c['status']}" for c in ground.get("checks", [])][:6])
        pois = [(p.point_id, math.dist(xy, (p.x_m, p.y_m))) for p in site.points
                if p.kind == "poi" and p.x_m is not None and p.y_m is not None]
        nearest = min(pois, key=lambda t: t[1]) if pois else None
        if check("matches a declared POI", nearest is not None and nearest[1] <= policy.poi_match_m,
                 f"nearest {nearest[0]} at {nearest[1]:.3f} m vs {policy.poi_match_m} m" if nearest else "no POI"):
            matched = nearest[0]
        target = {"map_frame": site.local_frame.frame_id, "x_m": xy[0], "y_m": xy[1], "z_m": round(target_xyz[2], 3),
                  "sigma_m": round(sigma, 3), "matched_poi": matched, "point_from": how,
                  "target_id": obs.detection.target_id, "object_class": obs.detection.object_class}
    failed = [c for c in checks if c["status"] == "FAIL"]
    return {"status": "REFUSED" if failed else "ACCEPTED", "observation_id": obs.observation_id,
            "data_kind": "TEST_FIXTURE" if obs.source.kind == "TEST_FIXTURE" else obs.source.kind,
            "checks": checks, "reasons": [f"{c['check'].upper()}: {c['detail']}" for c in failed],
            "target": target if not failed else None, "candidate_point": target if failed else None}


def fixture_observation(*, site, drone="drone_01", poi="POI_4", now: datetime, offset_m=(0.0, 0.0), age_s=2.0,
                        **override) -> dict:
    """A TEST FIXTURE: a card exactly below a camera looking straight down from 10 m above a declared POI. Not sensor
    data; labelled TEST_FIXTURE in the observation and in the pose."""
    p = site.point(poi)
    stamp = now - timedelta(seconds=age_s)
    # optical z (forward) pointing down = map -z; optical x = map +x; optical y (down in the image) = map -y
    obs = {"schema": SCHEMA, "observation_id": f"fixture-{drone}-{poi}", "stamp_utc": stamp.isoformat(),
           "observer": {"vehicle_id": drone, "camera_id": "cam_down_fixture"},
           "detection": {"object_class": "red_card", "confidence": 0.93, "target_id": "card_red_1"},
           "image": {"u_px": 320.0, "v_px": 240.0, "width_px": 640, "height_px": 480},
           "intrinsics": {"fx": 400.0, "fy": 400.0, "cx": 320.0, "cy": 240.0},
           "depth": {"depth_m": 10.0, "source": "STEREO"}, "camera_frame_id": "cam_down_fixture_optical",
           "camera_pose": {"frame_id": site.local_frame.frame_id,
                           "position_m": [p.x_m + offset_m[0], p.y_m + offset_m[1], 10.0],
                           "orientation_xyzw": [1.0, 0.0, 0.0, 0.0], "stamp_utc": stamp.isoformat(),
                           "source": "TEST_FIXTURE", "position_sigma_m": 0.1},
           "detection_sigma_m": 0.15, "valid_for_s": 30.0,
           "source": {"kind": "TEST_FIXTURE", "device": "multiagent.perception.fixture_observation"}}
    for key, value in override.items():
        obs[key] = value
    return obs


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
