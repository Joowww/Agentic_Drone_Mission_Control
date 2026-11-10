"""Resolve an objective to a DECLARED site point. The site is the only authority for coordinates.

- a point id must exist in the site and be of the expected kind;
- a raw coordinate is accepted only when it coincides (within the context tolerance) with one declared point of
  that kind; otherwise the objective needs a site point and nothing is invented;
- a point id together with a coordinate that does not match it is a contradiction, not a choice.
"""
from __future__ import annotations

import math

from models.site import Site


def resolve_point(site: Site, *, point_id: str | None, coordinates, kind: str, tolerance_m: float) -> tuple[str | None, list[str]]:
    """(point_id, reasons): reasons is empty only when the point is resolved."""
    if point_id is None and coordinates is None:
        return None, ["MISSING_COORDINATES: the objective names no site point and gives no coordinates"]
    declared = None
    if point_id is not None:
        declared = site.point(point_id)
        if declared is None:
            return None, [f"UNKNOWN_SITE_POINT: {point_id!r} is not declared in site {site.site_id}"]
        if declared.kind != kind:
            return None, [f"WRONG_POINT_KIND: {point_id} is a {declared.kind}, a {kind} is required"]
        if declared.x_m is None or declared.y_m is None:
            return None, [f"POINT_NOT_MEASURED: {point_id} has no coordinates in site {site.site_id}"]
    if coordinates is not None:
        x, y = coordinates
        if not (math.isfinite(x) and math.isfinite(y)):
            return None, ["INVALID_COORDINATES: non-finite value"]
        if declared is not None:
            if math.dist((x, y), (declared.x_m, declared.y_m)) > tolerance_m:
                return None, [f"CONTRADICTORY_COORDINATES: {point_id} is at ({declared.x_m}, {declared.y_m}), "
                              f"the request says ({x}, {y})"]
            return point_id, []
        matches = [p for p in site.points if p.kind == kind and p.x_m is not None and p.y_m is not None
                   and math.dist((x, y), (p.x_m, p.y_m)) <= tolerance_m]
        if len(matches) != 1:
            return None, [f"COORDINATES_NOT_A_DECLARED_SITE_POINT: ({x}, {y}) matches {len(matches)} declared "
                          f"{kind} points; declare it in the site before planning"]
        return matches[0].point_id, []
    return point_id, []
