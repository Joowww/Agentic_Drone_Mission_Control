"""Card detector (colour thresholds, no learning) and the pixel -> site-frame geometry, on SYNTHETIC_TEST scenes only.
Independent checks: hand-computed HSV values, a pixel-by-pixel morphology reference, closed-form ground points."""
from datetime import timedelta
import math
import random

import pytest

from multiagent import card_detector as cd, geometry as g, integrated_mission as im, perception as pc
from multiagent import synthetic_scenes as ss
from multiagent.contracts import load_context
from multiagent.vision_image import Image, from_png, to_png

CTX = load_context(im.CONTEXT)
SITE, FLEET = im._site_fleet(CTX)
FRAME = SITE.local_frame.frame_id
NOW = pc.utc_now()
CAM = ss.default_camera() | {"camera_id": "cam_down_fixture"}
P3 = SITE.point("POI_3")
POLICY = pc.Policy(allow_fixtures=True, allow_ground_plane=True)


def scene(**kw):
    img, manifest = ss.render({"seed": 1, "height_m": 10.0, "camera": CAM, **kw})
    return img, manifest, cd.detect(img, depth_m=10.0, fx=CAM["fx"])


CARD = {"size_m": [0.5, 0.35]}


# ------------------------------------------------------------------------------------- detector --
def test_hsv_matches_hand_computed_values():
    assert cd.hsv(255, 0, 0) == (0, 255, 255) and cd.hsv(0, 255, 0) == (60, 255, 255)
    assert cd.hsv(255, 255, 0) == (30, 255, 255) and cd.hsv(128, 128, 128) == (0, 0, 128)


def test_morphology_equals_a_pixel_reference():
    rng = random.Random(7)
    for w, h in ((23, 17), (1, 4), (64, 9)):
        m = bytearray(1 if rng.random() < 0.45 else 0 for _ in range(w * h))
        for op in ("erode", "dilate"):
            assert cd._morph(m, w, h, op) == cd._morph_reference(m, w, h, op)


@pytest.mark.parametrize("color, background", [("red", "grass"), ("yellow", "soil"), ("red", "gravel"), ("yellow", "grass")])
def test_one_card_is_found_with_its_centre_and_box(color, background):
    _, man, r = scene(background=background, cards=[{"color": color, "center_px": [200, 90], "angle_deg": 20, **CARD}])
    assert r["status"] == "DETECTED" and len(r["detections"]) == 1
    d = r["detections"][0]
    assert d["object_class"] == f"{color}_card" and math.dist(d["center_px"], man["truth"][0]["center_px"]) < 1.5
    x, y, bw, bh = d["bbox_px"]
    assert x <= 200 <= x + bw and y <= 90 <= y + bh and d["score_kind"] == "HEURISTIC_QUALITY"
    assert man["data_kind"] == "SYNTHETIC_TEST" and r["detector"]["learned"] is False


def test_two_cards_give_two_detections():
    _, _, r = scene(cards=[{"color": "red", "center_px": [80, 70], **CARD},
                           {"color": "yellow", "center_px": [230, 170], "angle_deg": 40, **CARD}])
    assert r["status"] == "DETECTED" and sorted(d["object_class"] for d in r["detections"]) == ["red_card", "yellow_card"]


@pytest.mark.parametrize("cards, status, reason", [
    ([], "NONE", None),
    ([{"color": "orange", "center_px": [160, 120], **CARD}], "AMBIGUOUS", "HUE_BETWEEN_RED_AND_YELLOW"),
    ([{"color": "red", "center_px": [3, 120], **CARD}], "AMBIGUOUS", "TOUCHES_IMAGE_BORDER"),
    # below the observable floor (v2: derived, side >= 6 px; a 3x3 card renders as about 4x4 px)
    ([{"color": "red", "center_px": [160, 120], "size_px": [3, 3]}], "NONE", "AREA_TOO_SMALL"),
    ([{"color": "red", "center_px": [160, 120], "size_px": [120, 4]}], "NONE", "ASPECT_OUT_OF_RANGE"),
    ([{"color": "red", "center_px": [160, 120], "size_m": [2.5, 2.0]}], "NONE", "PHYSICAL_SIZE_OUT_OF_RANGE"),
    ([{"color": "magenta", "center_px": [160, 120], **CARD}], "NONE", None),
    ([{"color": "blue", "center_px": [160, 120], **CARD}], "NONE", None),
])
def test_absent_ambiguous_and_rejected_regions(cards, status, reason):
    _, _, r = scene(cards=cards)
    assert r["status"] == status and r["detections"] == []
    if reason:
        assert any(x["reason"].startswith(reason) for x in r["ambiguous"] + r["rejected"])


@pytest.mark.parametrize("illumination", [0.55, 0.8, 1.25])
def test_uniform_illumination_changes_keep_the_card(illumination):
    _, _, r = scene(illumination=illumination, cards=[{"color": "red", "center_px": [160, 120], **CARD}])
    assert r["status"] == "DETECTED"


def test_noise_and_partial_occlusion():
    _, _, noisy = scene(noise=25, cards=[{"color": "yellow", "center_px": [160, 120], **CARD}])
    assert noisy["status"] == "DETECTED" and noisy["rejected"] == []  # opening removed the salt noise
    _, _, occ = scene(cards=[{"color": "red", "center_px": [160, 120], **CARD}],
                      occluders=[{"rect": [160, 100, 190, 140], "color": "white"}])
    d = occ["detections"][0]
    assert occ["status"] == "DETECTED" and d["center_px"][0] < 160  # the visible part biases the centre (documented)


def test_restricted_classes_reject_the_other_colour():
    img, _ = ss.render({"seed": 1, "camera": CAM, "cards": [{"color": "yellow", "center_px": [160, 120], **CARD}]})
    r = cd.detect(img, cd.Config(classes=("red",)), depth_m=10.0, fx=CAM["fx"])
    assert r["status"] == "NONE" and r["rejected"][0]["reason"] == "CLASS_NOT_ALLOWED: yellow"


def test_png_round_trip_and_filters():
    img, _ = ss.render({"seed": 3, "camera": CAM, "cards": [{"color": "red", "center_px": [50, 60], **CARD}]})
    assert from_png(to_png(img)).pixels == img.pixels
    with pytest.raises(ValueError):
        from_png(b"not a png")


# ------------------------------------------------------------------------------------- geometry --
def build(uv=(160.0, 120.0), position=(P3.x_m, P3.y_m, 10.0), yaw=0.0, *, camera=CAM, ext=None, pose=None, **kw):
    e, p = g.virtual_rig("drone_02", camera, position_m=position, stamp_utc=NOW, site_frame=FRAME, yaw_rad=yaw)
    return g.build_observation({"center_px": list(uv), "object_class": "red_card", "score": 0.9,
                                "score_kind": "HEURISTIC_QUALITY"}, camera=camera,
                               extrinsics=e if ext is None else ext, pose=p if pose is None else pose, site_frame=FRAME,
                               observation_id="o", target_id="card_red_1", stamp_utc=NOW,
                               source={"kind": "TEST_FIXTURE", "device": "test"}, **{"ground_plane": True, **kw})


def ground(b):
    return [round(c, 6) for c in pc.to_map(pc.Observation.model_validate(b["observation"]))]


@pytest.mark.parametrize("uv, position, yaw, expected", [
    ((160, 120), (8.0, 4.0, 10.0), 0.0, (8.0, 4.0)),                       # principal point straight below
    ((190, 120), (7.0, 4.0, 10.0), 0.0, (8.0, 4.0)),                       # +30 px = +1 m east at 10 m, fx 300
    ((160, 90), (8.0, 3.0, 10.0), 0.0, (8.0, 4.0)),                        # -30 px (up in the image) = +1 m north
    ((190, 120), (8.0, 3.0, 10.0), math.pi / 2, (8.0, 4.0)),               # yawed 90 deg: image right = north
    ((175, 120), (7.0, 4.0, 20.0), 0.0, (8.0, 4.0)),                       # twice as high: half the pixels per metre
])
def test_ground_points_match_closed_form_solutions(uv, position, yaw, expected):
    b = build(uv, position, yaw)
    assert b["status"] == "BUILT" and ground(b)[:2] == list(expected) and abs(ground(b)[2]) < 1e-6


def test_the_extrinsic_lever_arm_moves_the_point():
    e, _ = g.virtual_rig("drone_02", CAM, position_m=(7.5, 4.0, 10.0), stamp_utc=NOW, site_frame=FRAME)
    e = {**e, "translation_m": (0.5, 0.0, 0.0)}  # camera 0.5 m forward of the body origin (heading east)
    assert ground(build(position=(7.5, 4.0, 10.0), ext=e))[:2] == [8.0, 4.0]


def test_metric_depth_and_uncertainty():
    b = build(ground_plane=False, depth={"depth_m": 10.0, "source": "STEREO"}, sigma_px=3.0)
    assert ground(b)[:2] == [8.0, 4.0] and b["observation"]["detection_sigma_m"] == pytest.approx(3.0 * 10 / 300)
    high = build(position=(8.0, 4.0, 40.0), sigma_px=3.0)
    assert high["observation"]["detection_sigma_m"] > b["observation"]["detection_sigma_m"]  # grows with depth


@pytest.mark.parametrize("change, code", [
    (dict(pose=None, ground_plane=True), "POSE_UNKNOWN"),
    (dict(ground_plane=False), "DEPTH_MISSING"),
    (dict(camera=CAM | {"units": "mm"}), "UNITS_OR_SCHEMA_INVALID"),
    (dict(camera=CAM | {"distortion": "RADTAN"}), "UNITS_OR_SCHEMA_INVALID"),
    (dict(camera=CAM | {"camera_id": "cam_other"},  # extrinsics still describe cam_down_fixture
          ext=g.virtual_rig("drone_02", CAM, position_m=(8, 4, 10), stamp_utc=NOW, site_frame=FRAME)[0]),
     "CAMERA_IDENTITY_MISMATCH"),
    (dict(uv=(400.0, 120.0)), "PIXEL_OUTSIDE_IMAGE"),
])
def test_missing_or_inconsistent_inputs_refuse(change, code):
    if "pose" in change and change["pose"] is None:
        r = g.build_observation({"center_px": [160, 120], "object_class": "red_card", "score": 0.9}, camera=CAM,
                                extrinsics=g.virtual_rig("drone_02", CAM, position_m=(8, 4, 10), stamp_utc=NOW,
                                                         site_frame=FRAME)[0], pose=None, site_frame=FRAME,
                                observation_id="o", target_id="t", stamp_utc=NOW, source={"kind": "TEST_FIXTURE", "device": "t"},
                                ground_plane=True)
    else:
        r = build(**change)
    assert r["status"] == "REFUSED" and r["observation"] is None and r["reasons"][0].startswith(code)


def test_frames_identity_and_invertibility():
    e, p = g.virtual_rig("drone_02", CAM, position_m=(8, 4, 10), stamp_utc=NOW, site_frame=FRAME)
    assert build(pose={**p, "frame_id": "map"})["reasons"][0].startswith("FRAME_MISMATCH")
    assert build(ext={**e, "parent_frame": "drone_01/base_link"}, pose={**p, "child_frame": "drone_01/base_link"})[
        "reasons"][0].startswith("VEHICLE_IDENTITY_MISMATCH")
    assert build(ext={**e, "parent_frame": "drone_02/camera_mount"})["reasons"][0].startswith("FRAME_CHAIN_BROKEN")
    assert build(ext={**e, "rotation_xyzw": (0, 0, 0, 0)})["reasons"][0].startswith("NON_INVERTIBLE_TRANSFORM")
    assert build(ext={**e, "rotation_xyzw": (1, 1, 0, 0)})["reasons"][0].startswith("NON_UNIT_QUATERNION")
    up = {**p, "orientation_xyzw": (1.0, 0.0, 0.0, 0.0)}  # body flipped: the camera looks at the sky
    assert build(pose=up)["reasons"][0].startswith("GROUND_BEHIND_CAMERA")


def test_the_perception_gate_still_decides():
    ok = pc.ground_target_from_observation(build()["observation"], site=SITE, context=CTX, fleet=FLEET, now=NOW,
                                           policy=POLICY, camera_ids={"drone_02": ["cam_down_fixture"]})
    assert ok["status"] == "ACCEPTED" and ok["target"]["matched_poi"] == "POI_3"
    plane_off = pc.ground_target_from_observation(build()["observation"], site=SITE, context=CTX, fleet=FLEET, now=NOW,
                                                  policy=pc.Policy(allow_fixtures=True),
                                                  camera_ids={"drone_02": ["cam_down_fixture"]})
    assert any("ground-plane hypothesis not allowed" in r for r in plane_off["reasons"])
    stale = pc.ground_target_from_observation(build()["observation"], site=SITE, context=CTX, fleet=FLEET,
                                              now=NOW + timedelta(seconds=90), policy=POLICY,
                                              camera_ids={"drone_02": ["cam_down_fixture"]})
    assert any(r.startswith("FRESH") for r in stale["reasons"])
    far = build(position=(300.0, 4.0, 10.0))
    out = pc.ground_target_from_observation(far["observation"], site=SITE, context=CTX, fleet=FLEET, now=NOW, policy=POLICY,
                                            camera_ids={"drone_02": ["cam_down_fixture"]})
    assert any(r.startswith("INSIDE THE OPERATION PERIMETER") for r in out["reasons"])
    big = build(position=(8.0, 4.0, 150.0), sigma_px=4.0)  # 150 m up: sigma 2 m
    out = pc.ground_target_from_observation(big["observation"], site=SITE, context=CTX, fleet=FLEET, now=NOW, policy=POLICY,
                                            camera_ids={"drone_02": ["cam_down_fixture"]})
    assert any(r.startswith("POSITION UNCERTAINTY") for r in out["reasons"])
    strict = pc.Policy(allow_fixtures=True, allow_ground_plane=True, require_calibrated_camera=True)
    out = pc.ground_target_from_observation(build()["observation"], site=SITE, context=CTX, fleet=FLEET, now=NOW,
                                            policy=strict, camera_ids={"drone_02": ["cam_down_fixture"]})
    assert any(r.startswith("CALIBRATED CAMERA") for r in out["reasons"])  # a virtual camera is not a calibration


def test_from_a_rendered_image_to_a_validated_target():
    img, _ = ss.render({"seed": 2, "camera": CAM, "height_m": 10.0,
                        "cards": [{"color": "red", "center_px": [190, 120], "angle_deg": 15, **CARD}]})
    det = cd.detect(img, depth_m=10.0, fx=CAM["fx"])
    b = g.build_observation(det["detections"][0], camera=CAM, extrinsics=g.virtual_rig(
        "drone_02", CAM, position_m=(7.0, 4.0, 10.0), stamp_utc=NOW, site_frame=FRAME)[0],
        pose=g.virtual_rig("drone_02", CAM, position_m=(7.0, 4.0, 10.0), stamp_utc=NOW, site_frame=FRAME)[1],
        site_frame=FRAME, observation_id="img", target_id="card_red_1", stamp_utc=NOW,
        source={"kind": "TEST_FIXTURE", "device": "synthetic_scenes+card_detector"}, ground_plane=True)
    out = pc.ground_target_from_observation(b["observation"], site=SITE, context=CTX, fleet=FLEET, now=NOW, policy=POLICY,
                                            camera_ids={"drone_02": ["cam_down_fixture"]})
    assert out["status"] == "ACCEPTED" and out["target"]["matched_poi"] == "POI_3"
    assert b["observation"]["detection"]["score_kind"] == "HEURISTIC_QUALITY"
    assert isinstance(img, Image)


# ------------------------------------------------------------------- coordinate quality (sensitivity) --
@pytest.mark.parametrize("height", [5.0, 10.0, 20.0])
def test_errors_scale_as_the_first_order_model_says(height):
    """Perturb each input of the real chain and compare the ground displacement with the model behind sigma_det."""
    def point(uv=(160.0, 120.0), position=(8.0, 4.0, height), yaw=0.0, roll=0.0):
        e, p = g.virtual_rig("drone_02", CAM, position_m=position, stamp_utc=NOW, site_frame=FRAME, yaw_rad=yaw)
        if roll:
            p["orientation_xyzw"] = (math.sin(roll / 2), 0.0, 0.0, math.cos(roll / 2))  # small roll about body x
        return ground(build(uv, position, yaw, ext=e, pose=p))[:2]
    base = point()
    # pixel: 1 px -> height / fx metres
    assert math.dist(point(uv=(161.0, 120.0)), base) == pytest.approx(height / CAM["fx"], rel=1e-3)
    # pose position: a 0.1 m error moves the point 0.1 m
    assert math.dist(point(position=(8.1, 4.0, height)), base) == pytest.approx(0.1, rel=1e-6)
    # attitude: 0.01 rad of roll at depth d -> about d * 0.01 m (first order)
    assert math.dist(point(roll=0.01), base) == pytest.approx(height * 0.01, rel=0.01)
    # the declared sigma_det grows linearly with depth for pixel and attitude terms
    e, p = g.virtual_rig("drone_02", CAM, position_m=(8, 4, height), stamp_utc=NOW, site_frame=FRAME, attitude_sigma_rad=0.01)
    b = build(position=(8, 4, height), ext=e, pose=p, sigma_px=1.0)
    assert b["observation"]["detection_sigma_m"] == pytest.approx(math.hypot(height / CAM["fx"], height * 0.01), rel=1e-3)


# ---------------------------------------------------------------- illumination tolerance (documented boundary) --
def _tint(img, gains):
    out = Image(img.width, img.height, bytearray(img.pixels))
    for i in range(0, len(out.pixels), 3):
        for k in range(3):
            out.pixels[i + k] = max(0, min(255, int(out.pixels[i + k] * gains[k])))
    return out


@pytest.mark.parametrize("color", ["red", "yellow"])
@pytest.mark.parametrize("gains", [(1.15, 1.0, 0.75), (0.8, 1.0, 1.2)], ids=["warm", "cool"])
def test_warm_and_cool_casts_are_tolerated(color, gains):
    img, _ = ss.render({"seed": 1, "camera": CAM, "cards": [{"color": color, "center_px": [160, 120], **CARD}]})
    r = cd.detect(_tint(img, gains), depth_m=10.0, fx=CAM["fx"])
    assert r["status"] == "DETECTED" and r["detections"][0]["object_class"] == f"{color}_card"


def test_known_limit_a_strong_green_cast_loses_yellow_and_never_turns_it_red():
    """Documented boundary (not hidden by retuning on synthetic data): a green cast pushes yellow's hue out of its
    band, so the detector reports nothing rather than a wrong class. A grey/white reference target in real scenes
    is the planned fix; gray-world normalisation was measured and rejected (worse: 16/24 vs 21/24)."""
    img, _ = ss.render({"seed": 1, "camera": CAM, "cards": [{"color": "yellow", "center_px": [160, 120], **CARD}]})
    r = cd.detect(_tint(img, (0.85, 1.15, 0.85)), depth_m=10.0, fx=CAM["fx"])
    assert r["status"] == "NONE" and r["detections"] == []


# ------------------------------------------------------------------- observability (detector v2, derived floor) --
def test_the_area_floor_is_derived_from_the_size_error_budget():
    o = cd.observability(cd.Config(), depth_m=10.0, fx=300.0)
    assert o["min_observable_side_px"] == 6.0 and o["area_floor_px"] == 36   # 2 x 1 px / (1/3)
    assert o["gsd_m_per_px"] == round(10 / 300, 5) and o["observable_min_m"] == 0.2
    # the configured card_min_m (0.15 m = 4.5 px at 10 m) is NOT observable there: reported, not hidden
    assert o["unobservable_configured_range_m"] == [0.15, 0.2]
    assert cd.observability(cd.Config(), depth_m=5.0, fx=300.0)["unobservable_configured_range_m"] is None
    assert cd.observability(cd.Config(), depth_m=None, fx=None)["area_floor_px"] == 60  # no geometry: v1 floor


def test_a_tilt_is_a_reported_worst_case_not_ignored():
    o = cd.observability(cd.Config(), depth_m=10.0, fx=300.0, tilt_deg=30.0)
    assert o["worst_case_scale"] == 0.75 and o["observable_min_m"] > 0.2


def test_a_card_at_the_observable_limit_is_detected_and_one_below_is_not():
    img, _ = ss.render({"seed": 1, "height_m": 10.0, "camera": CAM,
                        "cards": [{"color": "red", "center_px": [160, 120], "size_m": [0.2, 0.2]}]})
    r = cd.detect(img, depth_m=10.0, fx=CAM["fx"])
    assert r["status"] == "DETECTED" and r["detector"]["version"] == "2"
    assert r["observability"]["basis"].startswith("DECLARED_VIRTUAL_CAMERA")
    img, _ = ss.render({"seed": 1, "height_m": 10.0, "camera": CAM,
                        "cards": [{"color": "red", "center_px": [160, 120], "size_m": [0.15, 0.15]}]})
    r = cd.detect(img, depth_m=10.0, fx=CAM["fx"])
    assert r["status"] == "NONE" and any(x["reason"].startswith("AREA_TOO_SMALL") for x in r["rejected"])


@pytest.mark.parametrize("kind, pose_source, calibration, ok", [
    ("REAL_SENSOR", "VEHICLE_EKF", None, False), ("REAL_SENSOR", "VEHICLE_EKF", "UNCALIBRATED", False),
    ("REAL_SENSOR", "VEHICLE_EKF", "DECLARED_VIRTUAL", False), ("REAL_SENSOR", "VEHICLE_EKF", "CALIBRATED", True),
    ("SITL_SENSOR", "SITL_GROUND_TRUTH", None, False), ("SITL_SENSOR", "SITL_GROUND_TRUTH", "DECLARED_VIRTUAL", True),
])
def test_sensor_observations_never_presume_a_calibrated_camera(kind, pose_source, calibration, ok):
    o = pc.fixture_observation(site=SITE, drone="drone_02", poi="POI_3", now=NOW, age_s=0.0)
    o["source"] = {"kind": kind, "device": "test", "evidence_sha256": "a" * 64}
    o["camera_pose"]["source"] = pose_source
    if calibration:
        o["camera_calibration"] = calibration
    gate = pc.ground_target_from_observation(o, site=SITE, context=CTX, fleet=FLEET, now=NOW, policy=POLICY,
                                             camera_ids=im.CAMERAS)
    assert (gate["status"] == "ACCEPTED") is ok, gate["reasons"]
