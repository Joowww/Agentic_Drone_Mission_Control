"""Camera input adapter: Image + CameraInfo + Pose + timestamp -> card detector -> observation -> coordinator event.

Shaped like the ROS 2 messages a future Gazebo camera would give (sensor_msgs/Image as decoded pixels,
sensor_msgs/CameraInfo, a pose of the observing drone), but nothing here imports ROS 2 and nothing assumes the current
Gazebo world has a camera. Every input is INJECTED; in tests and demos they are SYNTHETIC fixtures, labelled so.

Reused, not duplicated: multiagent.card_detector.detect, multiagent.geometry.build_observation (pixel -> site frame
with propagated uncertainty) and multiagent.perception.ground_target_from_observation (the observation gate). The
target stays in the SITE frame: the final conversion to the rover's navigation frame is the rover's adapter's
(ROVER_ADAPTER); it is not done here.

Refused before any detection, with a structured reason: camera without calibration (K missing, distortion present,
or a declared-virtual camera outside OFFLINE_TEST), pose not accredited by its ingestion, image too old, pose and
image out of sync, another drone than the configured owner of the camera, incompatible frame, mission cancelled,
repeated image. After detection: an ambiguous detection, and an uncertainty above the limit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import math

SCHEMA = "tfg.multiagent.camera-observation-input/1"


@dataclass
class CameraConfig:
    """DECLARED by the ingestion configuration, never taken from the messages."""
    camera_id: str
    owner_vehicle_id: str
    image_frame_id: str                 # the frame_id the CameraInfo/Image headers must carry
    extrinsics: dict                    # geometry.Extrinsics shape (mount transform), with its source
    max_image_age_s: float = 2.0
    max_pose_skew_s: float = 0.1
    max_total_sigma_m: float = 0.5
    accredited_pose_sources: tuple = ("TEST_FIXTURE",)


@dataclass
class AdapterState:
    seen_images: set = field(default_factory=set)


def _refuse(code, detail, **extra):
    return {"schema": SCHEMA, "status": "REFUSED", "reasons": [f"{code}: {detail}"], "event": None, **extra}


def camera_model(info: dict, cfg: CameraConfig, *, mode: str) -> tuple[dict | None, str | None]:
    """CameraInfo (sensor_msgs-like: width, height, k[9], d[], distortion_model, header.frame_id) + its declared
    calibration status -> geometry.CameraModel dict, or a refusal reason."""
    k = info.get("k") or []
    if len(k) != 9 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in k) or k[0] <= 0 or k[4] <= 0:
        return None, "CAMERA_NOT_CALIBRATED: no usable intrinsic matrix K"
    if any(abs(x) > 0 for x in (info.get("d") or [])):
        return None, "CAMERA_DISTORTION_NOT_SUPPORTED: undistort first (the geometry assumes a pinhole model)"
    status = info.get("calibration_status")
    if status not in ("CALIBRATED", "DECLARED_VIRTUAL"):
        return None, f"CAMERA_NOT_CALIBRATED: calibration status {status!r}"
    if status == "DECLARED_VIRTUAL" and mode != "OFFLINE_TEST":
        return None, "CAMERA_NOT_CALIBRATED: a declared virtual camera is accepted only in OFFLINE_TEST"
    if (info.get("header") or {}).get("frame_id") != cfg.image_frame_id:
        return None, f"FRAME_INCOMPATIBLE: CameraInfo frame {(info.get('header') or {}).get('frame_id')!r}"
    return {"camera_id": cfg.camera_id, "width_px": int(info["width"]), "height_px": int(info["height"]),
            "fx": float(k[0]), "fy": float(k[4]), "cx": float(k[2]), "cy": float(k[5]), "units": "px",
            "distortion": "NONE", "calibration_status": status, "model": info.get("distortion_model") or "pinhole"}, None


def observe(*, image, image_stamp: datetime, image_frame_id: str, camera_info: dict, pose: dict, now: datetime,
            cfg: CameraConfig, state: AdapterState, site, context, fleet, policy, camera_ids: dict,
            mission_cancelled: bool, mode: str = "OFFLINE_TEST", observation_id: str, ingestion_source: str,
            image_source: dict) -> dict:
    """One image -> {"status": OBSERVED | NO_TARGET | REFUSED, "reasons", "event" (coordinator OBSERVATION event or
    None), "gate", "provenance"}. ``pose``: geometry.DronePose shape plus "accredited" set by ITS ingestion."""
    from multiagent import card_detector, geometry, perception
    img_sha = hashlib.sha256(bytes(image.pixels)).hexdigest()
    prov = {"image_sha256": img_sha, "image_source": image_source, "camera_id": cfg.camera_id,
            "owner_vehicle_id": cfg.owner_vehicle_id, "pose_source": pose.get("source") if pose else None,
            "ingestion": ingestion_source, "mode": mode}
    if mission_cancelled:
        return _refuse("MISSION_CANCELLED", "no observation is produced for a cancelled mission", provenance=prov)
    if img_sha in state.seen_images:
        return _refuse("OBSERVATION_REPEATED", "this image was already processed", provenance=prov)
    if image_frame_id != cfg.image_frame_id:
        return _refuse("FRAME_INCOMPATIBLE", f"image frame {image_frame_id!r}, camera {cfg.image_frame_id!r}",
                       provenance=prov)
    cam, why = camera_model(camera_info, cfg, mode=mode)
    if cam is None:
        code, detail = why.split(": ", 1)
        return _refuse(code, detail, provenance=prov)
    if pose is None or not pose.get("accredited") or pose.get("source") not in cfg.accredited_pose_sources:
        return _refuse("POSE_NOT_ACCREDITED", f"pose source {(pose or {}).get('source')!r}", provenance=prov)
    if pose.get("vehicle_id") != cfg.owner_vehicle_id:
        return _refuse("OTHER_DRONE", f"pose of {pose.get('vehicle_id')!r}, camera owned by {cfg.owner_vehicle_id!r}",
                       provenance=prov)
    if pose.get("frame_id") != site.local_frame.frame_id:
        return _refuse("FRAME_INCOMPATIBLE", f"pose in {pose.get('frame_id')!r}, site frame "
                       f"{site.local_frame.frame_id!r}", provenance=prov)
    age = (now - image_stamp).total_seconds()
    if age > cfg.max_image_age_s or age < -policy.max_future_skew_s:
        return _refuse("IMAGE_STALE", f"image age {age:.2f} s (limit {cfg.max_image_age_s} s)", provenance=prov)
    skew = abs((pose["stamp_utc"] - image_stamp).total_seconds())
    if skew > cfg.max_pose_skew_s:
        return _refuse("POSE_IMAGE_DESYNCHRONISED", f"{skew:.3f} s between pose and image (limit "
                       f"{cfg.max_pose_skew_s} s)", provenance=prov)
    state.seen_images.add(img_sha)
    det = card_detector.detect(image, depth_m=pose["position_m"][2], fx=cam["fx"])
    prov["detector"] = {"status": det["status"], "count": len(det["detections"])}
    if det["status"] == "AMBIGUOUS" or det["ambiguous"]:
        return _refuse("DETECTION_AMBIGUOUS", f"{[a.get('reason') for a in det['ambiguous']]}", provenance=prov)
    if det["status"] != "DETECTED":
        return {"schema": SCHEMA, "status": "NO_TARGET", "reasons": [f"DETECTOR_{det['status']}"], "event": None,
                "provenance": prov}
    d = det["detections"][0]
    geo_pose = {k: pose[k] for k in ("vehicle_id", "frame_id", "child_frame", "position_m", "orientation_xyzw",
                                     "stamp_utc", "source", "position_sigma_m", "attitude_sigma_rad")}
    built = geometry.build_observation(d, camera=cam, extrinsics=cfg.extrinsics, pose=geo_pose,
                                       site_frame=site.local_frame.frame_id, observation_id=observation_id,
                                       target_id=f"{d['object_class']}_1", stamp_utc=image_stamp,
                                       source={"kind": "TEST_FIXTURE" if mode == "OFFLINE_TEST" else ingestion_source,
                                               "device": f"{cfg.camera_id}+card_detector",
                                               "evidence_sha256": img_sha}, ground_plane=True)
    if built["status"] != "BUILT":
        return _refuse("GEOMETRY_REFUSED", "; ".join(built["reasons"]), provenance=prov)
    obs = built["observation"]
    total = math.hypot(obs["detection_sigma_m"], pose.get("position_sigma_m") or 0.0)
    if total > cfg.max_total_sigma_m:
        return _refuse("UNCERTAINTY_TOO_HIGH", f"{total:.3f} m > {cfg.max_total_sigma_m} m", provenance=prov)
    gate = perception.ground_target_from_observation(obs, site=site, context=context, fleet=fleet, now=now,
                                                     policy=policy, camera_ids=camera_ids)
    if gate["status"] != "ACCEPTED":
        return {"schema": SCHEMA, "status": "REFUSED", "reasons": gate["reasons"], "event": None, "gate": gate,
                "provenance": prov}
    event = {"type": "OBSERVATION", "source": "TEST_FIXTURE" if mode == "OFFLINE_TEST" else ingestion_source,
             "at": now, "observation": obs, "event_id": f"camera:{observation_id}"}
    return {"schema": SCHEMA, "status": "OBSERVED", "reasons": [], "event": event, "gate": gate,
            "geometry": built["geometry"], "provenance": prov,
            "target_site_frame": {k: gate["target"][k] for k in ("x_m", "y_m", "sigma_m", "matched_poi")},
            "rover_frame_conversion": "NOT_DONE_HERE (ROVER_ADAPTER owns it)"}
