"""OpenCV port of multiagent.card_detector (same algorithm, same thresholds read from detector_config.json). Runs
ONLY in the isolated comparison environment (detector_cmp_requirements.txt); it imports nothing from the project, so
it can run with ``python -I``. Not a replacement for the project detector; a measurement aid.

    <venv>/bin/python -I multiagent/benchmark/detector_cmp_opencv.py --images <dir> --out <dir>/opencv.json
"""
import argparse
import json
from pathlib import Path
import resource
import statistics
import sys
import time

import cv2
import numpy as np


def _band(h, bands):
    m = np.zeros(h.shape, bool)
    for lo, hi in bands:
        m |= (h >= lo) & (h <= hi)
    return m


def detect(rgb, cfg, depth_m, fx):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)  # H 0..179, S/V 0..255: the convention card_detector follows
    hch, sch, vch = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    v_min = max(cfg["v_floor"], int(cfg["min_v_fraction"] * np.sort(vch.ravel())[int(0.95 * (vch.size - 1))]))
    bright = vch >= v_min
    red = bright & (sch >= cfg["min_s"]) & _band(hch, cfg["red_hue"])
    yellow = bright & (sch >= cfg["min_s"]) & _band(hch, cfg["yellow_hue"]) & ~red
    amb = bright & (sch >= cfg["ambiguous_min_s"]) & _band(hch, cfg["ambiguous_hue"]) & ~red & ~yellow
    kernel = np.ones((3, 3), np.uint8)
    h, w = hch.shape
    detections, ambiguous = [], []
    for label, mask in (("red", red), ("yellow", yellow), ("ambiguous", amb)):
        m = mask.astype(np.uint8)
        if cfg["morphology"] and m.any():
            m = cv2.morphologyEx(cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel), cv2.MORPH_CLOSE, kernel)
        n, _, stats, cents = cv2.connectedComponentsWithStats(m, connectivity=8)
        for k in range(1, n):
            x0, y0, bw, bh, area = (int(v) for v in stats[k])
            fill, aspect = area / (bw * bh), bw / bh
            center = [round(float(cents[k][0]) + 0.5, 2), round(float(cents[k][1]) + 0.5, 2)]
            size = [bw * depth_m / fx, bh * depth_m / fx]
            touches = x0 == 0 or y0 == 0 or x0 + bw == w or y0 + bh == h
            if area < cfg["min_area_px"] or not cfg["aspect_range"][0] <= aspect <= cfg["aspect_range"][1] \
                    or not all(cfg["card_min_m"] <= s <= cfg["card_max_m"] for s in size) or fill < cfg["borderline_fill"]:
                continue
            if label == "ambiguous":
                ambiguous.append({"class": label, "center_px": center, "reason": "HUE_BETWEEN_RED_AND_YELLOW"})
            elif touches:
                ambiguous.append({"class": label, "center_px": center, "reason": "TOUCHES_IMAGE_BORDER"})
            elif fill < cfg["min_fill"]:
                ambiguous.append({"class": label, "center_px": center, "reason": "BORDERLINE_FILL"})
            elif label in cfg["classes"]:
                detections.append({"class": f"{label}_card", "center_px": center, "area": area})
    detections.sort(key=lambda d: -d.pop("area"))
    status = "AMBIGUOUS" if ambiguous else ("DETECTED" if detections else "NONE")
    return status, detections, ambiguous


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("--images", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--repeats", type=int, default=3)
    args = a.parse_args(argv)
    truth = json.loads((args.images / "truth.json").read_text())
    cfg = json.loads((args.images / "detector_config.json").read_text())
    rows = []
    for case in truth["cases"]:
        bgr = cv2.imread(str(args.images / f"{case['case_id']}.png"), cv2.IMREAD_COLOR)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        times = []
        for _ in range(args.repeats):
            t0 = time.perf_counter()
            status, dets, amb = detect(rgb, cfg, truth["depth_m"], truth["camera"]["fx"])
            times.append(time.perf_counter() - t0)
        rows.append({"case_id": case["case_id"], "status": status, "seconds_median": statistics.median(times),
                     "detections": dets, "ambiguous": amb})
    out = {"detector": f"opencv port (cv2 {cv2.__version__}, numpy {np.__version__})", "python": sys.version.split()[0],
           "repeats": args.repeats, "max_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, "rows": rows}
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"rows": len(rows)}))


if __name__ == "__main__":
    main()
