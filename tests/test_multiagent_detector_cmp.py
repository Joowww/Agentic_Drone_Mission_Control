"""Detector comparison harness (offline): the case set is frozen, the metric is the same for both detectors, and the
OpenCV port is never imported by the project (cv2 is not in the shared environment)."""
import hashlib
import json
from pathlib import Path

from multiagent.benchmark import detector_cmp as dc

FROZEN = "fef481ed3831a93ce719a935acb6219c3b97c5e6348bd3598a2e04de63991ac6"  # measured with this set; never re-tuned


def test_the_case_set_is_frozen():
    assert dc.case_set_sha256() == FROZEN and len(dc.cases()) == 37
    groups = {c["group"] for c in dc.cases()}
    assert {"illumination", "colour_cast", "ambiguous", "distractor", "empty", "border", "size"} <= groups


def test_the_metric(tmp_path):
    (tmp_path / "truth.json").write_text(json.dumps({"cases": [
        {"case_id": "a", "group": "g", "cards": [{"color": "red", "center_px": [10, 10]}]},
        {"case_id": "b", "group": "g", "cards": [{"color": "orange", "center_px": [10, 10]}]},
        {"case_id": "c", "group": "g", "cards": [{"color": "yellow", "center_px": [50, 50]}]}]}))
    run = {"detector": "x", "rows": [
        {"case_id": "a", "seconds_median": 1, "ambiguous": [], "detections": [{"class": "yellow_card", "center_px": [10, 10]}]},
        {"case_id": "b", "seconds_median": 1, "detections": [], "ambiguous": [{"class": "ambiguous", "center_px": [11, 10]}]},
        {"case_id": "c", "seconds_median": 1, "detections": [], "ambiguous": [{"class": "yellow", "center_px": [50, 50]}]}]}
    s = dc.score(tmp_path, run)
    assert s["totals"]["fp"] == 1 and s["totals"]["fn"] == 2  # wrong colour = FP + FN
    assert s["totals"]["ambiguous_ok"] == 1 and s["totals"]["ambiguous_on_target"] == 1
    assert [c["correct"] for c in s["per_case"]] == [False, True, False]


def test_the_opencv_port_is_isolated():
    src = (Path(dc.__file__).parent / "detector_cmp_opencv.py").read_text()
    assert "from multiagent" not in src and "import multiagent" not in src
    req = (Path(dc.__file__).parent / "detector_cmp_requirements.txt").read_text()
    assert "opencv-python-headless==" in req and "numpy==" in req


def test_one_exported_image_is_reproducible(tmp_path):
    from multiagent import synthetic_scenes as ss
    from multiagent.vision_image import to_png
    case = next(c for c in dc.cases() if c["case_id"] == "base_red_grass")
    img, _ = ss.render({**case["spec"], "camera": ss.default_camera() | {"camera_id": "cam_down_fixture"}})
    sealed = sorted(Path(dc.__file__).parent.glob("results/detector_cmp_v1_*/truth.json"))
    if sealed:
        truth = {c["case_id"]: c for c in json.loads(sealed[-1].read_text())["cases"]}
        assert hashlib.sha256(to_png(img)).hexdigest() == truth["base_red_grass"]["png_sha256"]
