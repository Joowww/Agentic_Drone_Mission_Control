"""From a pixel detection to an observation in the site frame (tfg.multiagent.observation/1), with every frame,
unit, transform and hypothesis explicit. multiagent.perception stays the source of truth: this module only BUILDS the
observation; the perception gate validates it (freshness, uncertainty, bounds, POI match, sources).

Frames and conventions (metres, right-handed, unit quaternions x, y, z, w; R(q) maps child-frame vectors into parent):
- site frame: the site's local frame (ENU-like, z up), e.g. ``synthetic_orchard_local``;
- drone body: ``<vehicle_id>/base_link`` (REP 103: x forward, y left, z up), pose given IN the site frame;
- camera optical: ``<camera_id>_optical`` (x right, y down, z forward), extrinsics given IN the drone body frame.
Chain: T_site<-optical = T_site<-body (drone pose) * T_body<-optical (extrinsics).

Depth: a metric depth along the optical axis (STEREO/TOF/LIDAR) when the sensor gives one, or the explicit, testable
GROUND_PLANE_ASSUMPTION: the ray through the pixel intersected with the plane z = ground_z of the site frame.
Uncertainty (first order, declared inputs): sigma_det = sqrt((sigma_px * d / f)^2 + (d * sigma_attitude)^2 +
sigma_depth^2); the perception gate adds the pose sigma in quadrature. A documented approximation, not a full
covariance propagation.
"""
from __future__ import annotations

from datetime import datetime
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from multiagent import perception


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CameraModel(_Strict):
    camera_id: str = Field(min_length=1)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    fx: float = Field(gt=0)
    fy: float = Field(gt=0)
    cx: float = Field(ge=0)
    cy: float = Field(ge=0)
    units: Literal["px"] = "px"
    distortion: Literal["NONE"] = "NONE"  # a distorted model must be undistorted first; not supported here
    calibration_status: Literal["CALIBRATED", "DECLARED_VIRTUAL", "UNCALIBRATED"]
    model: str | None = None


class Extrinsics(_Strict):
    camera_id: str = Field(min_length=1)
    parent_frame: str = Field(min_length=1)  # <vehicle_id>/base_link
    child_frame: str = Field(min_length=1)   # <camera_id>_optical
    translation_m: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]
    units: Literal["m"] = "m"
    source: Literal["CALIBRATED", "CAD_MEASURED", "DECLARED_VIRTUAL"]


class DronePose(_Strict):
    vehicle_id: str = Field(min_length=1)
    frame_id: str = Field(min_length=1)       # the site frame
    child_frame: str = Field(min_length=1)    # <vehicle_id>/base_link
    position_m: tuple[float, float, float]
    orientation_xyzw: tuple[float, float, float, float]
    stamp_utc: datetime
    source: Literal["VEHICLE_EKF", "MOCAP", "SLAM", "SITL_GROUND_TRUTH", "TEST_FIXTURE"]
    position_sigma_m: float | None = Field(None, ge=0)
    attitude_sigma_rad: float | None = Field(None, ge=0)
    units: Literal["m"] = "m"


class GeometryError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _unit(q, what):
    n = math.sqrt(sum(c * c for c in q))
    if n < 1e-9:
        raise GeometryError("NON_INVERTIBLE_TRANSFORM", f"{what}: zero quaternion")
    if abs(n - 1) > 1e-3:
        raise GeometryError("NON_UNIT_QUATERNION", f"{what}: norm {n:.6f}")
    return q


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def rotate(q, v):
    return perception._rotate(q, v)


def compose(pose: DronePose, ext: Extrinsics) -> tuple[tuple, tuple]:
    """(position, orientation) of the camera optical frame in the site frame."""
    if ext.parent_frame != pose.child_frame:
        raise GeometryError("FRAME_CHAIN_BROKEN", f"extrinsics parent {ext.parent_frame!r} != pose child {pose.child_frame!r}")
    qp, qe = _unit(pose.orientation_xyzw, "drone pose"), _unit(ext.rotation_xyzw, "extrinsics")
    t = rotate(qp, ext.translation_m)
    return tuple(pose.position_m[i] + t[i] for i in range(3)), qmul(qp, qe)


def ground_plane_depth(cam: CameraModel, u: float, v: float, position, orientation, ground_z: float = 0.0) -> float:
    """Depth along the optical axis of the intersection of the pixel ray with z = ground_z (site frame)."""
    ray_cam = ((u - cam.cx) / cam.fx, (v - cam.cy) / cam.fy, 1.0)
    ray = rotate(orientation, ray_cam)
    if abs(ray[2]) < 1e-6:
        raise GeometryError("RAY_PARALLEL_TO_GROUND", "the pixel ray never meets the ground plane")
    s = (ground_z - position[2]) / ray[2]
    if s <= 0:
        raise GeometryError("GROUND_BEHIND_CAMERA", "the ground plane is behind the camera along this ray")
    return s  # ray_cam has z = 1, so s is the depth along the optical axis


def build_observation(detection: dict, *, camera: dict, extrinsics: dict | None, pose: dict | None, site_frame: str,
                      observation_id: str, target_id: str, stamp_utc: datetime, source: dict, valid_for_s: float = 30.0,
                      depth: dict | None = None, ground_plane: bool = False, ground_z: float = 0.0,
                      sigma_px: float = 2.0, sigma_depth_m: float = 0.0) -> dict:
    """``detection``: one item of card_detector.detect()['detections']. Returns {"status": BUILT | REFUSED,
    "observation": raw dict | None, "geometry": what was used, "reasons": [...]}. REFUSED never yields a position."""
    try:
        cam = CameraModel.model_validate(camera)
        ext = Extrinsics.model_validate(extrinsics) if extrinsics is not None else None
        drone = DronePose.model_validate(pose) if pose is not None else None
    except ValidationError as exc:
        return _refused("UNITS_OR_SCHEMA_INVALID", "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                                                              for e in exc.errors()[:3]))
    if drone is None:
        return _refused("POSE_UNKNOWN", "no drone pose at the capture time")
    if ext is None:
        return _refused("EXTRINSICS_UNKNOWN", "no camera mount transform")
    if ext.camera_id != cam.camera_id:
        return _refused("CAMERA_IDENTITY_MISMATCH", f"extrinsics for {ext.camera_id!r}, camera {cam.camera_id!r}")
    if drone.frame_id != site_frame:
        return _refused("FRAME_MISMATCH", f"drone pose in {drone.frame_id!r}, site frame {site_frame!r}")
    if not ext.parent_frame.startswith(f"{drone.vehicle_id}/"):
        return _refused("VEHICLE_IDENTITY_MISMATCH", f"camera mounted on {ext.parent_frame!r}, pose of {drone.vehicle_id!r}")
    u, v = detection["center_px"]
    if not (0 <= u < cam.width_px and 0 <= v < cam.height_px):
        return _refused("PIXEL_OUTSIDE_IMAGE", f"{(u, v)} outside {cam.width_px}x{cam.height_px}")
    try:
        position, orientation = compose(drone, ext)
        if depth is None and ground_plane:
            d = ground_plane_depth(cam, u, v, position, orientation, ground_z)
            depth = {"depth_m": d, "source": "GROUND_PLANE_ASSUMPTION"}
    except GeometryError as exc:
        return _refused(exc.code, exc.detail)
    if depth is None:
        return _refused("DEPTH_MISSING", "no metric depth and no ground-plane hypothesis declared")
    d = depth["depth_m"]
    sigma_det = math.sqrt((sigma_px * d / cam.fx) ** 2 + (d * (drone.attitude_sigma_rad or 0.0)) ** 2 + sigma_depth_m ** 2)
    obs = {"schema": perception.SCHEMA, "observation_id": observation_id, "stamp_utc": stamp_utc.isoformat(),
           "observer": {"vehicle_id": drone.vehicle_id, "camera_id": cam.camera_id, "camera_model": cam.model},
           "detection": {"object_class": detection["object_class"], "confidence": detection["score"],
                         "score_kind": detection.get("score_kind", "UNSPECIFIED"), "target_id": target_id},
           "image": {"u_px": u, "v_px": v, "width_px": cam.width_px, "height_px": cam.height_px},
           "intrinsics": {"fx": cam.fx, "fy": cam.fy, "cx": cam.cx, "cy": cam.cy},
           "depth": {"depth_m": round(d, 6), "source": depth["source"]}, "camera_frame_id": ext.child_frame,
           "camera_pose": {"frame_id": site_frame, "position_m": [round(c, 6) for c in position],
                           "orientation_xyzw": [round(c, 9) for c in orientation], "stamp_utc": drone.stamp_utc.isoformat(),
                           "source": drone.source, "position_sigma_m": drone.position_sigma_m},
           "detection_sigma_m": round(sigma_det, 4), "camera_calibration": cam.calibration_status,
           "valid_for_s": valid_for_s, "source": source}
    return {"status": "BUILT", "observation": obs, "reasons": [],
            "geometry": {"chain": [site_frame, drone.child_frame, ext.child_frame], "depth_source": depth["source"],
                         "ground_plane_z": ground_z if depth["source"] == "GROUND_PLANE_ASSUMPTION" else None,
                         "calibration": cam.calibration_status, "extrinsics_source": ext.source,
                         "pose_source": drone.source, "sigma_detection_m": round(sigma_det, 4)}}


def _refused(code, detail):
    return {"status": "REFUSED", "observation": None, "geometry": None, "reasons": [f"{code}: {detail}"]}


# ----------------------------------------------------------------------- declared virtual rig (tests/demo) --
DOWN = (1.0, 0.0, 0.0, 0.0)  # optical z (forward) along -z of the parent, optical y (down in the image) along -y


def virtual_rig(vehicle_id: str, camera: dict, *, position_m, stamp_utc: datetime, site_frame: str,
                yaw_rad: float = 0.0, sigma_m: float = 0.1, attitude_sigma_rad: float = 0.0) -> tuple[dict, dict]:
    """(extrinsics, pose) of a DECLARED VIRTUAL nadir camera at the body origin and a TEST_FIXTURE pose. Not real
    calibration values: every source field says so."""
    ext = {"camera_id": camera["camera_id"], "parent_frame": f"{vehicle_id}/base_link",
           "child_frame": f"{camera['camera_id']}_optical", "translation_m": (0.0, 0.0, 0.0), "rotation_xyzw": DOWN,
           "source": "DECLARED_VIRTUAL"}
    pose = {"vehicle_id": vehicle_id, "frame_id": site_frame, "child_frame": f"{vehicle_id}/base_link",
            "position_m": tuple(position_m), "orientation_xyzw": (0.0, 0.0, math.sin(yaw_rad / 2), math.cos(yaw_rad / 2)),
            "stamp_utc": stamp_utc, "source": "TEST_FIXTURE", "position_sigma_m": sigma_m,
            "attitude_sigma_rad": attitude_sigma_rad}
    return ext, pose
