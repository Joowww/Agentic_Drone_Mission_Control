"""SYNTHETIC_TEST images for the card detector: a nadir view rendered from a declared virtual camera. Not a photo,
not a Gazebo frame, not a flight: every scene carries data_kind SYNTHETIC_TEST and its full parameters.

Geometry of a scene: a virtual camera ``height_m`` above flat ground looking straight down (optical axis = -z of the
site frame); the ground sample distance is height_m / fx metres per pixel; a card of physical size (w, h) m appears as
(w / gsd, h / gsd) pixels, rotated by angle_deg, at a pixel position the scene states.
"""
from __future__ import annotations

import hashlib
import json
import math
import random

from multiagent.vision_image import Image

COLORS = {"red": (205, 32, 38), "yellow": (232, 205, 42), "orange": (238, 122, 30), "magenta": (200, 40, 170),
          "white": (235, 235, 230), "blue": (40, 70, 200)}
BACKGROUNDS = {"grass": (62, 122, 46), "soil": (112, 86, 66), "gravel": (128, 126, 120)}


def default_camera(width=320, height=240, fx=300.0) -> dict:
    """A VIRTUAL camera with declared parameters (calibration_status DECLARED_VIRTUAL); not a real calibration."""
    return {"camera_id": "cam_down_virtual", "model": "pinhole, no distortion", "calibration_status": "DECLARED_VIRTUAL",
            "width_px": width, "height_px": height, "fx": fx, "fy": fx, "cx": width / 2, "cy": height / 2, "units": "px"}


def render(spec: dict) -> tuple[Image, dict]:
    """(image, manifest). ``spec``: width, height, background, illumination, noise, seed, camera, height_m,
    cards [{color, center_px [u, v], size_m [w, h] | size_px [w, h], angle_deg}], occluders [{rect [x0, y0, x1, y1],
    color}]."""
    cam = spec.get("camera") or default_camera(spec.get("width", 320), spec.get("height", 240))
    w, h = cam["width_px"], cam["height_px"]
    rng = random.Random(spec.get("seed", 0))
    gsd = spec.get("height_m", 10.0) / cam["fx"]
    base = BACKGROUNDS[spec.get("background", "grass")]
    light, noise = spec.get("illumination", 1.0), spec.get("noise", 6)
    shapes = []
    for c in spec.get("cards", []):
        sw, sh = c["size_px"] if "size_px" in c else (c["size_m"][0] / gsd, c["size_m"][1] / gsd)
        a = math.radians(c.get("angle_deg", 0.0))
        shapes.append((c["center_px"][0], c["center_px"][1], sw / 2, sh / 2, math.cos(a), math.sin(a), COLORS[c["color"]]))
    occluders = [(o["rect"], COLORS.get(o.get("color", "white"), o.get("rgb", (200, 200, 200))))
                 for o in spec.get("occluders", [])]
    img = Image.blank(w, h)
    for y in range(h):
        for x in range(w):
            rgb = base
            for (u, v, hw, hh, ca, sa, col) in shapes:
                dx, dy = x + 0.5 - u, y + 0.5 - v
                if abs(dx * ca + dy * sa) <= hw and abs(-dx * sa + dy * ca) <= hh:
                    rgb = col
            for (x0, y0, x1, y1), col in occluders:
                if x0 <= x < x1 and y0 <= y < y1:
                    rgb = col
            n = rng.randint(-noise, noise) if noise else 0
            img.set(x, y, tuple((ch + n) * light for ch in rgb))
    manifest = {"schema": "tfg.multiagent.synthetic-scene/1", "data_kind": "SYNTHETIC_TEST", "spec": spec, "camera": cam,
                "ground_sample_distance_m_per_px": gsd,
                "truth": [{"color": c["color"], "center_px": list(c["center_px"])} for c in spec.get("cards", [])],
                "image_sha256": hashlib.sha256(bytes(img.pixels)).hexdigest()}
    return img, manifest


def spec_sha256(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
