"""Camera input adapter: synthetic Image + CameraInfo + Pose (TEST_FIXTURE) -> detector -> observation -> coordinator.
No ROS 2, no Gazebo, no real camera."""
from datetime import timedelta

import pytest

from multiagent import camera_observation as co, geometry, integrated_mission as im, perception, synthetic_scenes
from tests.test_multiagent_coordinator import NOW, coord, g, through_validated

CTX = im.load_context(im.CONTEXT)
SITE, FLEET = im._site_fleet(CTX)
FRAME = SITE.local_frame.frame_id
CAM = synthetic_scenes.default_camera() | {"camera_id": "cam_down_fixture"}
POLICY = perception.Policy(allow_fixtures=True, allow_ground_plane=True)
POI3 = SITE.point("POI_3")


def scene(color="red", seed=11):
    return synthetic_scenes.render({"seed": seed, "camera": CAM, "height_m": 10.0, "background": "grass", "noise": 8,
                                    "cards": [{"color": color, "center_px": [190, 120], "angle_deg": 18,
                                               "size_m": [0.5, 0.35]}]})


def info(**kw):
    base = {"header": {"frame_id": "cam_down_fixture_optical"}, "width": CAM["width_px"], "height": CAM["height_px"],
            "k": [CAM["fx"], 0, CAM["cx"], 0, CAM["fy"], CAM["cy"], 0, 0, 1], "d": [], "distortion_model": "plumb_bob",
            "calibration_status": "DECLARED_VIRTUAL"}
    return {**base, **kw}


def rig(vehicle="drone_02", dt=0.0, **pose_kw):
    ext, pose = geometry.virtual_rig(vehicle, CAM, position_m=(POI3.x_m - 1.0, POI3.y_m, 10.0),
                                     stamp_utc=NOW + timedelta(seconds=dt), site_frame=FRAME)
    return ext, {**pose, "accredited": True, **pose_kw}


def cfg(**kw):
    ext, _ = rig()
    return co.CameraConfig(camera_id="cam_down_fixture", owner_vehicle_id="drone_02",
                           image_frame_id="cam_down_fixture_optical", extrinsics=ext, **kw)


def run(*, img=None, image_dt=0.0, now_dt=0.5, pose=None, camera_info=None, config=None, state=None, cancelled=False,
        mode="OFFLINE_TEST", frame="cam_down_fixture_optical", oid="cam-obs-1"):
    image, manifest = img or scene()
    return co.observe(image=image, image_stamp=NOW + timedelta(seconds=image_dt), image_frame_id=frame,
                      camera_info=camera_info or info(), pose=pose or rig()[1], now=NOW + timedelta(seconds=now_dt),
                      cfg=config or cfg(), state=state or co.AdapterState(), site=SITE, context=CTX, fleet=FLEET,
                      policy=POLICY, camera_ids=im.CAMERAS, mission_cancelled=cancelled, mode=mode,
                      observation_id=oid, ingestion_source="TEST_FIXTURE_INGESTION",
                      image_source={"kind": "SYNTHETIC_TEST", "manifest_sha256": manifest["image_sha256"]})


def code(out):
    return out["reasons"][0].split(":")[0]


def test_a_valid_synthetic_frame_becomes_a_site_frame_target_and_validates_the_ground_task():
    out = run()
    assert out["status"] == "OBSERVED" and out["target_site_frame"]["matched_poi"] == "POI_3"
    assert out["rover_frame_conversion"].startswith("NOT_DONE_HERE")
    assert out["provenance"]["image_source"]["kind"] == "SYNTHETIC_TEST" and out["event"]["source"] == "TEST_FIXTURE"
    c = through_validated(coord(policy=POLICY))   # the same declared policy (ground plane allowed) as the adapter
    c.handle({"type": "HEARTBEAT", "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=0.2), "task_id": "AIR_drone_02"})
    assert c.handle(out["event"])["outcome"] == "APPLIED" and g(c) == "TARGET_VALIDATED"
    strict = through_validated(coord())          # default policy: a ground-plane position is refused, not accepted
    assert strict.handle(out["event"])["outcome"] == "APPLIED_REFUSED_OBSERVATION"


@pytest.mark.parametrize("kw, reason", [
    (dict(camera_info=info(k=[])), "CAMERA_NOT_CALIBRATED"),
    (dict(camera_info=info(calibration_status=None)), "CAMERA_NOT_CALIBRATED"),
    (dict(mode="OPERATIONAL"), "CAMERA_NOT_CALIBRATED"),                       # declared virtual camera
    (dict(camera_info=info(d=[0.1, 0, 0, 0, 0])), "CAMERA_DISTORTION_NOT_SUPPORTED"),
    (dict(pose=rig(accredited=False)[1]), "POSE_NOT_ACCREDITED"),
    (dict(pose=rig(source="SITL_GROUND_TRUTH")[1]), "POSE_NOT_ACCREDITED"),     # not an accredited source here
    (dict(image_dt=-5.0, now_dt=0.0), "IMAGE_STALE"),
    (dict(pose=rig(dt=0.5)[1]), "POSE_IMAGE_DESYNCHRONISED"),
    (dict(pose=rig(vehicle="drone_01")[1]), "OTHER_DRONE"),
    (dict(frame="cam_front_optical"), "FRAME_INCOMPATIBLE"),
    (dict(pose={**rig()[1], "frame_id": "map"}), "FRAME_INCOMPATIBLE"),
    (dict(img=scene(color="orange")), "DETECTION_AMBIGUOUS"),
    (dict(pose=rig(position_sigma_m=0.6)[1]), "UNCERTAINTY_TOO_HIGH"),
    (dict(cancelled=True), "MISSION_CANCELLED"),
])
def test_each_bad_input_is_refused_with_its_reason_and_no_event(kw, reason):
    out = run(**kw)
    assert out["status"] == "REFUSED" and code(out) == reason and out["event"] is None, out["reasons"]


def test_the_same_image_twice_is_a_repetition():
    state = co.AdapterState()
    assert run(state=state)["status"] == "OBSERVED"
    out = run(state=state, oid="cam-obs-2")
    assert out["status"] == "REFUSED" and code(out) == "OBSERVATION_REPEATED"


def test_an_image_without_a_card_is_no_target_not_an_error():
    img = synthetic_scenes.render({"seed": 3, "camera": CAM, "height_m": 10.0, "background": "grass", "noise": 8,
                                   "cards": []})
    out = run(img=img)
    assert out["status"] == "NO_TARGET" and out["event"] is None
