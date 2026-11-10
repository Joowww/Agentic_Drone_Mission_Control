"""Red / yellow card detector by COLOUR THRESHOLDS (no learning, no neural network), standard library only.

Pipeline (the same steps an OpenCV implementation would use; OpenCV is not installed here):
 1. HSV conversion with OpenCV's convention (H 0..179, S 0..255, V 0..255);
 2. illumination: the value threshold adapts to the image (min_v_fraction x 95th percentile of V, never below an
    absolute floor), so a uniformly dimmer or brighter scene keeps its cards; hue/saturation do not depend on gain;
 3. per-class masks: red (two hue bands), yellow, and AMBIGUOUS orange between them;
 4. morphology: opening (removes isolated noise) then closing (fills small holes), 3x3;
 5. 8-connected components; metrics per component: area, bbox, centre (mean pixel), fill ratio (area / bbox area),
    aspect ratio, mean HSV, whether it touches the image border;
 6. geometric filters: minimum area; aspect and fill ratio of a (possibly rotated, partly occluded) card; with a
    declared depth and fx, the physical size must be in [card_min_m, card_max_m] and the area floor is derived from
    the observable side (see observability(); v2), which also reports the configured sizes NOT observable there;
 7. classification: VALID, AMBIGUOUS (orange hue, border-touching, or a borderline fill ratio), REJECTED (+reason).
Result status: DETECTED (>= 1 valid and no ambiguous), AMBIGUOUS (any ambiguous candidate), NONE.

score: HEURISTIC_QUALITY = fill_ratio x min(1, mean_saturation / 153). It measures how card-like and saturated the
region is; it is NOT a calibrated probability and must not be read as one.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
import hashlib

from multiagent.vision_image import Image

SCHEMA = "tfg.multiagent.card-detection/1"


@dataclass
class Config:
    red_hue: tuple = ((0, 8), (170, 179))
    yellow_hue: tuple = ((20, 34),)
    ambiguous_hue: tuple = ((10, 18),)
    min_s: int = 120
    ambiguous_min_s: int = 150
    v_floor: int = 55
    min_v_fraction: float = 0.35
    min_area_px: int = 60
    aspect_range: tuple = (0.3, 3.4)
    min_fill: float = 0.5
    borderline_fill: float = 0.4
    card_min_m: float = 0.15
    card_max_m: float = 1.2
    # observability (v2): with a declared depth and fx, the pixel area floor is DERIVED from the size-measurement
    # error budget instead of the fixed min_area_px: a side measured with +-edge_error_px per edge has a relative
    # error of 2 x edge_error_px / side_px; requiring it <= max_relative_size_error gives the minimum observable side.
    # Declared assumptions for a synthetic virtual camera; a real camera needs calibration (blur, rolling shutter).
    edge_error_px: float = 1.0
    max_relative_size_error: float = 1 / 3
    morphology: bool = True
    classes: tuple = ("red", "yellow")


def hsv(r: int, g: int, b: int) -> tuple[int, int, int]:
    mx, mn = max(r, g, b), min(r, g, b)
    v, d = mx, mx - mn
    s = 0 if mx == 0 else (255 * d) // mx
    if d == 0:
        return 0, s, v
    if mx == r:
        hdeg = (60 * (g - b) / d) % 360
    elif mx == g:
        hdeg = 60 * (b - r) / d + 120
    else:
        hdeg = 60 * (r - g) / d + 240
    return int(hdeg / 2) % 180, s, v


def _in(h, bands):
    return any(lo <= h <= hi for lo, hi in bands)


def _rows(mask: bytearray, w: int, h: int) -> list[int]:
    table = bytes.maketrans(b"\x00\x01", b"01")
    return [int(bytes(reversed(mask[y * w:(y + 1) * w])).translate(table), 2) if any(mask[y * w:(y + 1) * w]) else 0
            for y in range(h)]  # bit x of row y = pixel (x, y)


def _unrows(rows: list[int], w: int) -> bytearray:
    out = bytearray()
    for r in rows:
        out += bytes((r >> x) & 1 for x in range(w))
    return out


def _morph_rows(rows: list[int], w: int, op: str) -> list[int]:
    """3x3 erosion/dilation on rows-as-integers (bit x = pixel x). As OpenCV's defaults, pixels outside the image
    never erode a border pixel and never dilate into the image."""
    full = (1 << w) - 1
    h = len(rows)
    if op == "erode":
        horiz = [(r & ((r << 1) | 1) & ((r >> 1) | (1 << (w - 1)))) & full for r in rows]
        return [horiz[y] & (horiz[y - 1] if y > 0 else full) & (horiz[y + 1] if y < h - 1 else full) for y in range(h)]
    horiz = [(r | (r << 1) | (r >> 1)) & full for r in rows]
    return [horiz[y] | (horiz[y - 1] if y > 0 else 0) | (horiz[y + 1] if y < h - 1 else 0) for y in range(h)]


def _morph(mask: bytearray, w: int, h: int, op: str) -> bytearray:
    return _unrows(_morph_rows(_rows(mask, w, h), w, op), w)


def _morph_reference(mask: bytearray, w: int, h: int, op: str) -> bytearray:
    """Pixel-by-pixel 3x3 reference of _morph (tests only), same border convention."""
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            vals = [mask[yy * w + xx] for yy in range(max(0, y - 1), min(h, y + 2)) for xx in range(max(0, x - 1), min(w, x + 2))]
            out[y * w + x] = (1 if all(vals) else 0) if op == "erode" else (1 if any(vals) else 0)
    return out


def _components(mask: bytearray, w: int, h: int):
    seen = bytearray(w * h)
    for start in range(w * h):
        if not mask[start] or seen[start]:
            continue
        queue, pixels = deque([start]), []
        seen[start] = 1
        while queue:
            i = queue.popleft()
            pixels.append(i)
            x, y = i % w, i // w
            for yy in range(max(0, y - 1), min(h, y + 2)):
                for xx in range(max(0, x - 1), min(w, x + 2)):
                    j = yy * w + xx
                    if mask[j] and not seen[j]:
                        seen[j] = 1
                        queue.append(j)
        yield pixels


def observability(cfg: Config, *, depth_m: float | None, fx: float | None, tilt_deg: float = 0.0) -> dict:
    """What can be measured at this depth with this camera. A nadir camera over flat ground (image plane parallel
    to the ground) has a UNIFORM scale gsd = depth / fx: there is no perspective change across the image. A tilt or a
    slope shrinks the apparent side by up to cos(tilt) and lengthens the range by 1/cos(tilt) (worst case cos^2);
    that factor is reported, not hidden. Without depth and fx the fixed min_area_px applies (v1 behaviour)."""
    min_side_px = 2 * cfg.edge_error_px / cfg.max_relative_size_error
    if not depth_m or not fx:
        return {"basis": "NO_GEOMETRY: fixed min_area_px", "area_floor_px": cfg.min_area_px}
    import math
    gsd = depth_m / fx
    worst = math.cos(math.radians(tilt_deg)) ** 2
    observable_min_m = min_side_px * gsd / worst
    return {"basis": "DECLARED_VIRTUAL_CAMERA (calibration pending)", "gsd_m_per_px": round(gsd, 5),
            "tilt_deg": tilt_deg, "worst_case_scale": round(worst, 4), "min_observable_side_px": round(min_side_px, 2),
            "observable_min_m": round(observable_min_m, 4),
            "expected_side_px": [round(cfg.card_min_m * worst / gsd, 2), round(cfg.card_max_m / gsd, 2)],
            "area_floor_px": math.ceil(min_side_px ** 2),
            "unobservable_configured_range_m": [cfg.card_min_m, round(observable_min_m, 4)]
            if observable_min_m > cfg.card_min_m else None}


def detect(img: Image, config: Config | None = None, *, depth_m: float | None = None, fx: float | None = None,
           tilt_deg: float = 0.0) -> dict:
    cfg = config or Config()
    w, h = img.width, img.height
    obs = observability(cfg, depth_m=depth_m, fx=fx, tilt_deg=tilt_deg)
    area_floor = obs["area_floor_px"]
    hsvs = [hsv(*img.get(x, y)) for y in range(h) for x in range(w)]
    vs = sorted(v for _, _, v in hsvs)
    v_min = max(cfg.v_floor, int(cfg.min_v_fraction * vs[int(0.95 * (len(vs) - 1))]))
    masks = {"red": bytearray(w * h), "yellow": bytearray(w * h), "ambiguous": bytearray(w * h)}
    for i, (hh, s, v) in enumerate(hsvs):
        if v < v_min:
            continue
        if s >= cfg.min_s and _in(hh, cfg.red_hue):
            masks["red"][i] = 1
        elif s >= cfg.min_s and _in(hh, cfg.yellow_hue):
            masks["yellow"][i] = 1
        elif s >= cfg.ambiguous_min_s and _in(hh, cfg.ambiguous_hue):
            masks["ambiguous"][i] = 1
    detections, ambiguous, rejected = [], [], []
    for label, mask in masks.items():
        if cfg.morphology and any(mask):
            rows = _rows(mask, w, h)
            rows = _morph_rows(_morph_rows(rows, w, "erode"), w, "dilate")  # opening
            rows = _morph_rows(_morph_rows(rows, w, "dilate"), w, "erode")  # closing
            mask = _unrows(rows, w)
        for pixels in _components(mask, w, h):
            xs, ys = [i % w for i in pixels], [i // w for i in pixels]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            bw, bh = x1 - x0 + 1, y1 - y0 + 1
            area = len(pixels)
            mean = [sum(hsvs[i][k] for i in pixels) / area for k in range(3)]
            fill, aspect = area / (bw * bh), bw / bh
            item = {"class": label, "bbox_px": [x0, y0, bw, bh],
                    "center_px": [round(sum(xs) / area + 0.5, 2), round(sum(ys) / area + 0.5, 2)],
                    "area_px": area, "fill_ratio": round(fill, 3), "aspect": round(aspect, 3),
                    "mean_hsv": [round(m, 1) for m in mean],
                    "touches_border": x0 == 0 or y0 == 0 or x1 == w - 1 or y1 == h - 1,
                    "score": round(fill * min(1.0, mean[1] / 153), 3), "score_kind": "HEURISTIC_QUALITY"}
            if depth_m is not None and fx:
                item["size_m"] = [round(bw * depth_m / fx, 3), round(bh * depth_m / fx, 3)]
            reason = None
            if area < area_floor:
                reason = f"AREA_TOO_SMALL: {area} px < {area_floor} ({obs['basis']})"
            elif not cfg.aspect_range[0] <= aspect <= cfg.aspect_range[1]:
                reason = f"ASPECT_OUT_OF_RANGE: {aspect:.2f}"
            elif "size_m" in item and not all(cfg.card_min_m <= s <= cfg.card_max_m for s in item["size_m"]):
                reason = f"PHYSICAL_SIZE_OUT_OF_RANGE: {item['size_m']} m"
            elif fill < cfg.borderline_fill:
                reason = f"FILL_TOO_LOW: {fill:.2f}"
            if reason:
                rejected.append({**item, "reason": reason})
            elif label == "ambiguous":
                ambiguous.append({**item, "reason": "HUE_BETWEEN_RED_AND_YELLOW"})
            elif item["touches_border"]:
                ambiguous.append({**item, "reason": "TOUCHES_IMAGE_BORDER (may be cut off)"})
            elif fill < cfg.min_fill:
                ambiguous.append({**item, "reason": f"BORDERLINE_FILL: {fill:.2f}"})
            elif label in cfg.classes:
                detections.append({**item, "object_class": f"{label}_card"})
            else:
                rejected.append({**item, "reason": f"CLASS_NOT_ALLOWED: {label}"})
    detections.sort(key=lambda d: -d["area_px"])
    status = "AMBIGUOUS" if ambiguous else ("DETECTED" if detections else "NONE")
    return {"schema": SCHEMA, "status": status, "detections": detections, "ambiguous": ambiguous, "rejected": rejected,
            "image": {"width_px": w, "height_px": h, "sha256": hashlib.sha256(bytes(img.pixels)).hexdigest()},
            "value_threshold": v_min, "config": asdict(cfg), "observability": obs,
            "detector": {"kind": "HSV_THRESHOLD_MORPHOLOGY_CONNECTED_COMPONENTS", "learned": False, "version": "2",
                         "score": "HEURISTIC_QUALITY (fill ratio x saturation), not a calibrated probability"}}
