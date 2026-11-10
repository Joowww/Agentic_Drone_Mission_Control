"""Fair comparison of the pure-Python card detector with an OpenCV port of the SAME algorithm (same thresholds, same
filters, same images, same metric). SYNTHETIC_TEST scenes only; nothing here is a real photograph.

    python -m multiagent.benchmark.detector_cmp export --out <dir>            # frozen case set -> PNG + truth
    python -m multiagent.benchmark.detector_cmp run-python --images <dir> --out <dir>/python.json
    <isolated venv>/bin/python -I multiagent/benchmark/detector_cmp_opencv.py --images <dir> --out <dir>/opencv.json
    python -m multiagent.benchmark.detector_cmp score --images <dir> --runs <dir>/python.json <dir>/opencv.json

The OpenCV side runs in an ISOLATED environment declared in detector_cmp_requirements.txt (never the shared .venv).
The case set is fixed in CASES before any measurement; it is not tuned to either detector.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import resource
import statistics
import sys
import time

CASE_SET = "detector_cmp/1"
CARD = {"size_m": [0.5, 0.35]}
CASTS = {"warm": (1.15, 1.0, 0.75), "cool": (0.8, 1.0, 1.2), "green": (0.85, 1.2, 0.85)}
EXPECTED = {"red": "red_card", "yellow": "yellow_card", "orange": "AMBIGUOUS"}  # anything else: nothing expected
MATCH_PX = 6.0


def _c(color, u=160, v=120, **kw):
    return {"color": color, "center_px": [u, v], **CARD, **kw}


def cases() -> list[dict]:
    out = []

    def add(cid, group, **spec):
        out.append({"case_id": cid, "group": group, "spec": {"seed": len(out) + 1, "height_m": 10.0, **spec}})
    for bg in ("grass", "soil", "gravel"):
        for col in ("red", "yellow"):
            add(f"base_{col}_{bg}", "base", background=bg, cards=[_c(col)])
    for light in (0.55, 0.8, 1.25):
        for col in ("red", "yellow"):
            add(f"light_{col}_{light}", "illumination", illumination=light, cards=[_c(col)])
    for cast in CASTS:
        for col in ("red", "yellow"):
            add(f"cast_{col}_{cast}", "colour_cast", cast=cast, cards=[_c(col)])
    for ang in (30, 60):
        for col in ("red", "yellow"):
            add(f"angle_{col}_{ang}", "rotation", cards=[_c(col, angle_deg=ang)])
    add("small_red", "size", cards=[{"color": "red", "center_px": [160, 120], "size_m": [0.2, 0.2]}])
    add("large_yellow", "size", cards=[{"color": "yellow", "center_px": [160, 120], "size_m": [1.0, 0.7]}])
    for bg in ("grass", "soil"):
        add(f"orange_{bg}", "ambiguous", background=bg, cards=[_c("orange")])
    for col in ("magenta", "blue", "white"):
        add(f"distractor_{col}", "distractor", cards=[_c(col)])
    for bg in ("grass", "soil", "gravel"):
        add(f"empty_{bg}", "empty", background=bg, cards=[])
    add("two_cards", "multiple", cards=[_c("red", 90, 80), _c("yellow", 230, 160)])
    add("occluded_red", "occlusion", cards=[_c("red")], occluders=[{"rect": [160, 100, 190, 140], "color": "white"}])
    add("border_yellow", "border", cards=[_c("yellow", 6, 120)])
    for col in ("red", "yellow"):
        add(f"noise_{col}", "noise", noise=20, cards=[_c(col)])
    return out


def case_set_sha256() -> str:
    return hashlib.sha256(json.dumps(cases(), sort_keys=True).encode()).hexdigest()


def export(out: Path) -> dict:
    from multiagent import synthetic_scenes as ss
    from multiagent.vision_image import to_png
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    cam = ss.default_camera() | {"camera_id": "cam_down_fixture"}
    truth = []
    for case in cases():
        spec = {k: v for k, v in case["spec"].items() if k != "cast"}
        img, manifest = ss.render({**spec, "camera": cam})
        gains = CASTS.get(case["spec"].get("cast"))
        if gains:
            for i in range(0, len(img.pixels), 3):
                for k in range(3):
                    img.pixels[i + k] = max(0, min(255, int(img.pixels[i + k] * gains[k])))
        data = to_png(img)
        (out / f"{case['case_id']}.png").write_bytes(data)
        truth.append({"case_id": case["case_id"], "group": case["group"], "png_sha256": hashlib.sha256(data).hexdigest(),
                      "cards": manifest["truth"]})
    meta = {"schema": "tfg.multiagent.detector-cmp-images/1", "case_set": CASE_SET, "case_set_sha256": case_set_sha256(),
            "data_kind": "SYNTHETIC_TEST", "camera": cam, "depth_m": 10.0, "match_px": MATCH_PX, "cases": truth}
    (out / "truth.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    from multiagent import card_detector as cd
    (out / "detector_config.json").write_text(json.dumps(asdict(cd.Config()), indent=1, sort_keys=True) + "\n")
    return meta


def run_python(images: Path, out: Path, repeats: int = 3) -> dict:
    from multiagent import card_detector as cd
    from multiagent.vision_image import from_png
    images = Path(images)
    truth = json.loads((images / "truth.json").read_text())
    rows = []
    for case in truth["cases"]:
        img = from_png((images / f"{case['case_id']}.png").read_bytes())
        times = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            r = cd.detect(img, depth_m=truth["depth_m"], fx=truth["camera"]["fx"])
            times.append(time.perf_counter() - t0)
        rows.append({"case_id": case["case_id"], "status": r["status"], "seconds_median": statistics.median(times),
                     "detections": [{"class": d["object_class"], "center_px": d["center_px"]} for d in r["detections"]],
                     "ambiguous": [{"class": a["class"], "center_px": a["center_px"], "reason": a["reason"]}
                                   for a in r["ambiguous"]]})
    result = {"detector": f"pure_python card_detector v{r['detector']['version']}", "python": sys.version.split()[0], "repeats": repeats,
              "max_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, "rows": rows}
    Path(out).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    return result


def _near(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 <= MATCH_PX


def score(images: Path, run: dict) -> dict:
    """Same metric for both: a detection is a TP if its class is the expected one and its centroid is within MATCH_PX
    of a truth card; any other detection is a FP (a wrong colour counts as FP + FN); an orange card is correct only
    when reported as ambiguous; an ambiguous report on a red/yellow card is a FN labelled AMBIGUOUS_ON_TARGET."""
    truth = {c["case_id"]: c for c in json.loads((Path(images) / "truth.json").read_text())["cases"]}
    tot = {"tp": 0, "fp": 0, "fn": 0, "ambiguous_ok": 0, "ambiguous_missed": 0, "ambiguous_on_target": 0,
           "false_ambiguous": 0}
    per_case, per_group = [], {}
    for row in run["rows"]:
        t = truth[row["case_id"]]
        targets = [c for c in t["cards"] if c["color"] in ("red", "yellow")]
        oranges = [c for c in t["cards"] if c["color"] == "orange"]
        tp = fp = 0
        used = set()
        for d in row["detections"]:
            hit = next((i for i, c in enumerate(targets) if i not in used and EXPECTED[c["color"]] == d["class"]
                        and _near(d["center_px"], c["center_px"])), None)
            if hit is None:
                fp += 1
            else:
                tp += 1
                used.add(hit)
        fn_cards = [c for i, c in enumerate(targets) if i not in used]
        amb_on_target = sum(1 for c in fn_cards if any(_near(a["center_px"], c["center_px"]) for a in row["ambiguous"]))
        amb_ok = sum(1 for c in oranges if any(_near(a["center_px"], c["center_px"]) for a in row["ambiguous"]))
        false_amb = sum(1 for a in row["ambiguous"] if not any(_near(a["center_px"], c["center_px"])
                                                              for c in targets + oranges))
        c = {"tp": tp, "fp": fp, "fn": len(fn_cards), "ambiguous_ok": amb_ok, "ambiguous_missed": len(oranges) - amb_ok,
             "ambiguous_on_target": amb_on_target, "false_ambiguous": false_amb}
        correct = c["fp"] == 0 and c["fn"] == 0 and c["ambiguous_missed"] == 0 and c["false_ambiguous"] == 0
        per_case.append({"case_id": row["case_id"], "group": t["group"], "correct": correct, **c})
        g = per_group.setdefault(t["group"], {"cases": 0, "correct": 0})
        g["cases"] += 1
        g["correct"] += correct
        for k in tot:
            tot[k] += c[k]
    secs = [r["seconds_median"] for r in run["rows"]]
    return {"detector": run["detector"], "cases": len(per_case), "cases_correct": sum(c["correct"] for c in per_case),
            "totals": tot, "precision": tot["tp"] / (tot["tp"] + tot["fp"]) if tot["tp"] + tot["fp"] else None,
            "recall": tot["tp"] / (tot["tp"] + tot["fn"]) if tot["tp"] + tot["fn"] else None,
            "seconds_per_image": {"median": statistics.median(secs), "max": max(secs)},
            "max_rss_mib": run.get("max_rss_mib"), "per_group": per_group, "per_case": per_case}


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = a.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("run-python")
    p.add_argument("--images", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("--images", type=Path, required=True)
    s.add_argument("--runs", type=Path, nargs="+", required=True)
    s.add_argument("--out", type=Path)
    args = a.parse_args(argv)
    if args.cmd == "export":
        m = export(args.out)
        print(json.dumps({"cases": len(m["cases"]), "case_set_sha256": m["case_set_sha256"]}))
    elif args.cmd == "run-python":
        r = run_python(args.images, args.out)
        print(json.dumps({"rows": len(r["rows"])}))
    else:
        scores = [score(args.images, json.loads(p.read_text())) for p in args.runs]
        if args.out:
            args.out.write_text(json.dumps(scores, indent=1, sort_keys=True) + "\n")
        for sc in scores:
            print(json.dumps({k: sc[k] for k in ("detector", "cases", "cases_correct", "precision", "recall",
                                                 "totals", "seconds_per_image", "max_rss_mib")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
