"""Planar geometry and the single local-frame <-> WGS84 conversion used by sites and scenario instances.

Local site frame (``ENU_ROTATED``): metres, right-handed, +z up. The +y axis points along the bearing
``y_axis_bearing_deg`` (clockwise from true north) and +x is 90 degrees clockwise from +y. With a bearing
of 0 the frame is plain ENU (x east, y north). The frame's orientation is a site property; a vehicle's
heading is a different quantity and is never derived from it.

Conversion to latitude/longitude reuses the project's existing local linear model (111 320 m per degree,
longitude scaled by cos(origin latitude): ``planning.relative_routes`` and the SITL mapper use the same
constant), restricted to the same 1000 m radius and |latitude| <= 75. It is a flat-earth approximation for
small sites, not a geodetic transformation; its own round-trip error is tested, its fidelity to the ground
is not.

Geometry is 2D: simple polygons (open rings, no holes) and straight segments. These checks concern the
PLANNED line only; they say nothing about the flown trajectory, unknown obstacles or collisions.
"""
from __future__ import annotations

import math

from planning.relative_routes import MAX_ABS_LATITUDE, MAX_RADIUS_M
from tools.simulation_mission_mapper import METERS_PER_DEGREE_LATITUDE, _calculate_local_offset_metres

FRAME_METHOD = "enu_rotated_local_linear_111320_cos_origin_v1"
EPS = 1e-9
MIN_AREA_M2 = 1e-4
INSIDE, OUTSIDE, BOUNDARY = "INSIDE", "OUTSIDE", "BOUNDARY"


def finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(p, a, b) -> bool:
    return (abs(_cross(a, b, p)) <= EPS * max(1.0, math.dist(a, b))
            and min(a[0], b[0]) - EPS <= p[0] <= max(a[0], b[0]) + EPS
            and min(a[1], b[1]) - EPS <= p[1] <= max(a[1], b[1]) + EPS)


def segments_intersect(a, b, c, d) -> bool:
    """True when the closed segments ab and cd share at least one point (touching and overlap included)."""
    d1, d2, d3, d4 = _cross(c, d, a), _cross(c, d, b), _cross(a, b, c), _cross(a, b, d)
    if ((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)) and ((d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS)):
        return True
    return _on_segment(a, c, d) or _on_segment(b, c, d) or _on_segment(c, a, b) or _on_segment(d, a, b)


def _point_segment_distance(p, a, b) -> float:
    length2 = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2
    if length2 == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / length2))
    return math.dist(p, (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))


def segment_distance(a, b, c, d) -> float:
    if segments_intersect(a, b, c, d):
        return 0.0
    return min(_point_segment_distance(a, c, d), _point_segment_distance(b, c, d),
               _point_segment_distance(c, a, b), _point_segment_distance(d, a, b))


def edges(polygon):
    return list(zip(polygon, polygon[1:] + polygon[:1]))


def polygon_area(polygon) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in edges(polygon)) / 2


def polygon_problems(polygon) -> list[str]:
    """Reasons a polygon is unsupported or degenerate; empty when it is a simple open ring."""
    if not isinstance(polygon, list) or len(polygon) < 3:
        return ["needs at least 3 vertices"]
    if not all(isinstance(p, (list, tuple)) and len(p) == 2 and finite(*p) for p in polygon):
        return ["every vertex must be a finite [x_m, y_m] pair"]
    problems = []
    if math.dist(polygon[0], polygon[-1]) <= EPS:
        problems.append("give an open ring: the first vertex must not be repeated at the end")
    if any(math.dist(a, b) <= EPS for a, b in edges(polygon)):
        problems.append("repeated consecutive vertex")
    if abs(polygon_area(polygon)) < MIN_AREA_M2:
        problems.append("degenerate polygon (zero area)")
    ring = edges(polygon)
    n = len(ring)
    for i in range(n):
        for j in range(i + 1, n):
            adjacent = j == i + 1 or (i == 0 and j == n - 1)
            a, b = ring[i]
            c, d = ring[j]
            if adjacent:
                # Adjacent edges may share only their common vertex: no folding back along the same line.
                far_i, far_j = (a, d) if j == i + 1 else (b, c)
                if _on_segment(far_j, a, b) or _on_segment(far_i, c, d):
                    problems.append(f"edges {i} and {j} overlap")
            elif segments_intersect(a, b, c, d):
                problems.append(f"self-intersection between edges {i} and {j}")
    return problems


def point_location(p, polygon) -> str:
    if any(_on_segment(p, a, b) for a, b in edges(polygon)):
        return BOUNDARY
    inside = False
    for a, b in edges(polygon):
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x > p[0]:
                inside = not inside
    return INSIDE if inside else OUTSIDE


def _pieces(a, b, polygon):
    """Locations of the sub-segments of ab split at every crossing with the polygon's edges."""
    ts = {0.0, 1.0}
    for c, d in edges(polygon):
        r = (b[0] - a[0], b[1] - a[1])
        s = (d[0] - c[0], d[1] - c[1])
        denominator = r[0] * s[1] - r[1] * s[0]
        if abs(denominator) > EPS:
            t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / denominator
            u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / denominator
            if -EPS <= t <= 1 + EPS and -EPS <= u <= 1 + EPS:
                ts.add(min(1.0, max(0.0, t)))
        else:
            length2 = r[0] ** 2 + r[1] ** 2
            for q in (c, d):  # collinear overlap: split at the projected edge ends
                if length2 and _on_segment(q, a, b):
                    ts.add(((q[0] - a[0]) * r[0] + (q[1] - a[1]) * r[1]) / length2)
    ordered = sorted(ts)
    for t0, t1 in zip(ordered, ordered[1:]):
        if t1 - t0 > EPS:
            tm = (t0 + t1) / 2
            yield point_location((a[0] + tm * (b[0] - a[0]), a[1] + tm * (b[1] - a[1])), polygon)


def segment_within(a, b, polygon) -> str:
    """INSIDE when the whole planned segment is strictly inside; BOUNDARY when it touches the edge; else OUTSIDE."""
    locations = [point_location(a, polygon), point_location(b, polygon), *_pieces(a, b, polygon)]
    if OUTSIDE in locations:
        return OUTSIDE
    return BOUNDARY if BOUNDARY in locations else INSIDE


def segment_clearance(a, b, polygon) -> float:
    """0 when the segment enters or touches the polygon; otherwise the minimum distance to it."""
    if point_location(a, polygon) != OUTSIDE or point_location(b, polygon) != OUTSIDE:
        return 0.0
    return min(segment_distance(a, b, c, d) for c, d in edges(polygon))


def local_to_north_east(x_m: float, y_m: float, y_axis_bearing_deg: float) -> tuple[float, float]:
    beta = math.radians(y_axis_bearing_deg)
    east = x_m * math.cos(beta) + y_m * math.sin(beta)
    north = -x_m * math.sin(beta) + y_m * math.cos(beta)
    return north, east


def north_east_to_local(north_m: float, east_m: float, y_axis_bearing_deg: float) -> tuple[float, float]:
    beta = math.radians(y_axis_bearing_deg)
    return east_m * math.cos(beta) - north_m * math.sin(beta), east_m * math.sin(beta) + north_m * math.cos(beta)


def local_to_geo(x_m: float, y_m: float, *, origin_latitude: float, origin_longitude: float,
                 y_axis_bearing_deg: float) -> tuple[float, float]:
    if not finite(x_m, y_m, origin_latitude, origin_longitude, y_axis_bearing_deg):
        raise ValueError("Non-finite coordinate or reference")
    if abs(origin_latitude) > MAX_ABS_LATITUDE or not -180 < origin_longitude < 180:
        raise ValueError("Geographic reference outside the supported domain (|latitude| <= 75)")
    if math.hypot(x_m, y_m) > MAX_RADIUS_M:
        raise ValueError(f"Point beyond the {MAX_RADIUS_M:.0f} m radius of the local linear model")
    north, east = local_to_north_east(x_m, y_m, y_axis_bearing_deg)
    latitude = origin_latitude + north / METERS_PER_DEGREE_LATITUDE
    longitude = origin_longitude + east / (METERS_PER_DEGREE_LATITUDE * math.cos(math.radians(origin_latitude)))
    if not -180 < longitude < 180:
        raise ValueError("Point crosses the antimeridian")
    return latitude, longitude


def geo_to_local(latitude: float, longitude: float, *, origin_latitude: float, origin_longitude: float,
                 y_axis_bearing_deg: float) -> tuple[float, float]:
    """Inverse of local_to_geo, through the executor's own offset function."""
    from models.mission_definition import GeoPoint
    north, east = _calculate_local_offset_metres(
        GeoPoint(latitude=origin_latitude, longitude=origin_longitude, altitude_m=0.0), latitude, longitude)
    return north_east_to_local(north, east, y_axis_bearing_deg)
