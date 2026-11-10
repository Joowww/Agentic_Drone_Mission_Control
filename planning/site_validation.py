"""Deterministic checks of a site and of planned lines over it.

Results are lists of named checks (PASS / FAIL / NOT_CHECKABLE / REQUIRES_PLANNING), never a single
"safe" flag. Passing them shows that the PLANNED straight lines respect the declared geometry with the
declared margin; it does not show physical containment, absence of unknown obstacles or collision
avoidance. No path planner exists: a rover line that leaves its area is reported as REQUIRES_PLANNING.
"""
from __future__ import annotations

import math

from models.fleet import FleetVehicle
from models.site import Site
from planning.relative_routes import MAX_RADIUS_M
from planning.site_geometry import (
    INSIDE, OUTSIDE, point_location, polygon_problems, segment_clearance, segment_distance, segment_within,
)

def _xy(point):
    return None if point is None or point.x_m is None or point.y_m is None else (point.x_m, point.y_m)


def geographic_references(site: Site) -> dict:
    """What a geographic export needs and what is missing; never filled with defaults."""
    geo, vertical = site.geo_reference, site.vertical_reference
    missing = []
    if geo is None or geo.latitude is None or geo.longitude is None:
        missing.append("geo_reference.latitude/longitude")
    if site.local_frame.y_axis_bearing_deg is None:
        missing.append("local_frame.y_axis_bearing_deg")
    if vertical is None or vertical.origin_ground_amsl_m is None:
        missing.append("vertical_reference.origin_ground_amsl_m")
    verified = (site.status == "VERIFIED_DECLARED" and not missing
                and geo.verification == vertical.verification == site.local_frame.orientation_verification
                == "VERIFIED_DECLARED")
    return {"complete": not missing, "missing": missing, "field_verified_declared": verified}


def validate_site(site: Site) -> dict:
    errors, missing, warnings = [], [], []
    expected_kind = {"SYNTHETIC": "SYNTHETIC", "TEMPLATE_PENDING_MEASUREMENT": "TEMPLATE",
                     "MEASURED_UNVERIFIED": "MEASURED", "VERIFIED_DECLARED": "MEASURED"}[site.status]
    if site.provenance.kind != expected_kind:
        errors.append(f"status {site.status} requires provenance.kind {expected_kind}")
    if expected_kind == "MEASURED" and not (site.provenance.source and site.provenance.measured_on):
        errors.append("measured sites need provenance.source and provenance.measured_on")

    zone_ids = [site.operation_perimeter.zone_id, *[z.zone_id for z in site.exclusions],
                *[z.zone_id for z in site.takeoff_landing_zones], *[z.zone_id for z in site.rover_start_zones],
                *([site.rover_drivable_area.zone_id] if site.rover_drivable_area else [])]
    point_ids = [p.point_id for p in site.points]
    for kind, ids in (("zone", zone_ids), ("point", point_ids)):
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            errors.append(f"duplicate {kind} ids: {duplicates}")

    zones = site.zones()
    for zone_id, zone in zones.items():
        if zone.polygon is None:
            missing.append(f"zone {zone_id}.polygon")
            continue
        polygon = [list(p) for p in zone.polygon]
        errors.extend(f"zone {zone_id}: {p}" for p in polygon_problems(polygon))
        if any(math.hypot(*p) > MAX_RADIUS_M for p in polygon):
            errors.append(f"zone {zone_id}: vertex beyond the {MAX_RADIUS_M:.0f} m local-model radius")
    if site.rover_drivable_area is None:
        warnings.append("no rover_drivable_area: ground lines cannot be checked")

    origin = site.point(site.local_frame.origin_point_id)
    if origin is None or origin.kind != "reference":
        errors.append(f"local_frame.origin_point_id {site.local_frame.origin_point_id!r} must be a point of kind reference")
    elif _xy(origin) not in (None, (0.0, 0.0)):
        errors.append("the reference point is the local origin and must be at (0, 0)")

    perimeter = site.operation_perimeter.polygon
    ok = lambda zone: zone is not None and zone.polygon is not None and not polygon_problems([list(p) for p in zone.polygon])  # noqa: E731
    air = [z for z in site.exclusions if "air" in z.applies_to and ok(z)]
    takeoff_ids = {z.zone_id for z in site.takeoff_landing_zones}
    start_ids = {z.zone_id for z in site.rover_start_zones}
    for point in site.points:
        xy = _xy(point)
        if xy is None:
            missing.append(f"point {point.point_id}.x_m/y_m")
            continue
        if point.kind in ("planned_takeoff", "rover_start"):
            allowed = takeoff_ids if point.kind == "planned_takeoff" else start_ids
            zone = zones.get(point.zone_id)
            if point.zone_id not in allowed:
                errors.append(f"point {point.point_id}: zone {point.zone_id!r} is not a "
                              f"{'takeoff/landing' if point.kind == 'planned_takeoff' else 'rover start'} zone")
            elif ok(zone) and point_location(xy, zone.polygon) != INSIDE:
                errors.append(f"point {point.point_id}: not strictly inside zone {point.zone_id}")
        if point.kind == "rover_start" and ok(site.rover_drivable_area) and \
                point_location(xy, site.rover_drivable_area.polygon) != INSIDE:
            errors.append(f"point {point.point_id}: rover start outside the drivable area")
        if point.kind in ("poi", "planned_takeoff") and ok(site.operation_perimeter) and \
                point_location(xy, perimeter) != INSIDE:
            errors.append(f"point {point.point_id}: not strictly inside the operation perimeter")
        for zone in air:
            if point.kind != "reference" and point_location(xy, zone.polygon) != OUTSIDE:
                warnings.append(f"point {point.point_id} lies in air exclusion {zone.zone_id}")
    if ok(site.operation_perimeter):
        for zone in site.takeoff_landing_zones:
            if not ok(zone):
                continue
            ring = list(zone.polygon)
            if any(segment_within(a, b, perimeter) != INSIDE for a, b in zip(ring, ring[1:] + ring[:1])):
                errors.append(f"takeoff zone {zone.zone_id} is not inside the operation perimeter")
            for exclusion in air:
                if any(segment_clearance(a, b, exclusion.polygon) == 0 for a, b in zip(ring, ring[1:] + ring[:1])) \
                        or any(point_location(p, ring) != OUTSIDE for p in exclusion.polygon):
                    errors.append(f"takeoff zone {zone.zone_id} overlaps air exclusion {exclusion.zone_id}")

    references = geographic_references(site)
    status = "INVALID" if errors else "INCOMPLETE" if missing else "VALID"
    geographic = status == "VALID" and references["complete"] and site.status != "TEMPLATE_PENDING_MEASUREMENT"
    blocked = []
    if not geographic:
        blocked.append(f"site {status}" if status != "VALID" else "geographic references missing: "
                       + ", ".join(references["missing"]))
    field_blocks = list(blocked)
    if site.status == "SYNTHETIC":
        field_blocks.append("SYNTHETIC site: never a proposal for hardware")
    elif not references["field_verified_declared"]:
        field_blocks.append("site, geo/vertical reference and frame orientation are not all VERIFIED_DECLARED")
    return {"site_id": site.site_id, "version": site.version, "site_status": site.status, "status": status,
            "errors": errors, "missing": missing, "warnings": warnings,
            "geographic_references": references,
            "capabilities": {"local_design": status == "VALID",
                             "sitl_geographic_export": geographic,
                             "field_export": not field_blocks},
            "export_blocks": {"sitl": blocked, "field": field_blocks},
            "note": "VERIFIED_DECLARED is a declaration in the file, not an authentication"}


def _check(name, status, detail):
    return {"check": name, "status": status, "detail": detail}


def margin_status(site: Site, vehicle: FleetVehicle | None, elements: list, planning_margin_m: float) -> dict:
    """Declared planning margin vs. what could support it. Never 'accredited' with missing inputs."""
    needed = {"vehicle.max_horizontal_extent_m": vehicle and vehicle.max_horizontal_extent_m,
              "vehicle.horizontal_position_uncertainty_m": vehicle and vehicle.horizontal_position_uncertainty_m}
    for element in elements:
        label = f"point {element.point_id}" if hasattr(element, "point_id") else f"zone {element.zone_id}"
        needed[f"{label}.uncertainty_m"] = element.uncertainty_m
    absent = sorted(k for k, v in needed.items() if v is None)
    result = {"planning_margin_m": planning_margin_m, "kind": "DECLARED_PLANNING_MARGIN"}
    if absent:
        return {**result, "status": "NOT_ACCREDITED", "missing_inputs": absent}
    required = (vehicle.max_horizontal_extent_m / 2 + vehicle.horizontal_position_uncertainty_m
                + max(e.uncertainty_m for e in elements))
    return {**result, "status": "COVERS_DECLARED_VALUES" if planning_margin_m >= required else "BELOW_DECLARED_VALUES",
            "required_from_declared_values_m": required,
            "note": "derived from declared values only; not a physical guarantee"}


def validate_aerial_route(site: Site, takeoff_id: str, poi_ids: list[str], altitude_m: float,
                          planning_margin_m: float, vehicle: FleetVehicle | None = None) -> dict:
    checks = []
    takeoff = site.point(takeoff_id)
    pois = [site.point(p) for p in poi_ids]
    if takeoff is None or takeoff.kind != "planned_takeoff":
        checks.append(_check("references", "FAIL", f"{takeoff_id!r} is not a planned_takeoff point of the site"))
    for poi_id, poi in zip(poi_ids, pois):
        if poi is None or poi.kind != "poi":
            checks.append(_check("references", "FAIL", f"{poi_id!r} is not a POI of the site"))
    if checks:
        return {"status": "FAIL", "checks": checks, "route_local": None}
    return _aerial_legs(site, takeoff, list(poi_ids), [_xy(p) for p in pois], altitude_m, planning_margin_m,
                        vehicle, pois)


def validate_aerial_local_route(site: Site, takeoff_id: str, waypoints: list[tuple[str, tuple[float, float]]],
                                altitude_m: float, planning_margin_m: float, vehicle: FleetVehicle | None = None) -> dict:
    """The same checks for a route given in the site's local frame (labels, xy) instead of site POIs, e.g. a
    finalized mission re-based on a planned takeoff point. Waypoints carry no declared uncertainty of their own."""
    takeoff = site.point(takeoff_id)
    if takeoff is None or takeoff.kind != "planned_takeoff":
        return {"status": "FAIL", "checks": [_check("references", "FAIL",
                                                    f"{takeoff_id!r} is not a planned_takeoff point of the site")],
                "route_local": None}
    return _aerial_legs(site, takeoff, [label for label, _ in waypoints], [tuple(xy) for _, xy in waypoints],
                        altitude_m, planning_margin_m, vehicle, [])


def _aerial_legs(site, takeoff, waypoint_labels, waypoints_xy, altitude_m, planning_margin_m, vehicle, elements):
    checks = []
    takeoff_id = takeoff.point_id
    route = [_xy(takeoff), *waypoints_xy, _xy(takeoff)]
    if None in route or site.operation_perimeter.polygon is None:
        return {"status": "FAIL", "checks": [_check("coordinates", "FAIL", "unmeasured point or perimeter")],
                "route_local": None}
    labels = [takeoff_id, *waypoint_labels, f"{takeoff_id} (return)"]
    perimeter = site.operation_perimeter.polygon
    air = [z for z in site.exclusions if "air" in z.applies_to and z.polygon is not None]
    for i, (a, b) in enumerate(zip(route, route[1:])):
        leg = f"{labels[i]} -> {labels[i + 1]}"
        within = segment_within(a, b, perimeter)
        checks.append(_check(f"perimeter {leg}", "PASS" if within == INSIDE else "FAIL",
                             "inside" if within == INSIDE else f"line {within.lower()} the operation perimeter"))
        for zone in air:
            clearance = segment_clearance(a, b, zone.polygon)
            status = "PASS" if clearance >= planning_margin_m and clearance > 0 else "FAIL"
            detail = (f"crosses or touches exclusion {zone.zone_id}" if clearance == 0 else
                      f"clearance {clearance:.3f} m to {zone.zone_id} vs margin {planning_margin_m} m")
            checks.append(_check(f"exclusion {zone.zone_id} {leg}", status, detail))
    takeoff_zone = site.zones().get(takeoff.zone_id)
    checks.append(_check("takeoff in takeoff/landing zone",
                         "PASS" if takeoff_zone and takeoff_zone.polygon and
                         point_location(_xy(takeoff), takeoff_zone.polygon) == INSIDE else "FAIL", takeoff.zone_id))
    limit, vertical = site.vertical_limits.max_altitude_m, site.vertical_reference
    if limit is None:
        checks.append(_check("vertical limit", "NOT_CHECKABLE", "the site defines no maximum altitude"))
    elif vertical is None or vertical.terrain != "DECLARED_FLAT":
        checks.append(_check("vertical limit", "NOT_CHECKABLE",
                             "limit is above the site origin ground but the mission altitude is relative to the "
                             "effective home; without declared flat terrain the references are not comparable"))
    else:
        checks.append(_check("vertical limit", "PASS" if altitude_m <= limit else "FAIL",
                             f"{altitude_m} m above effective home vs {limit} m above origin ground (declared flat)"))
    margin = margin_status(site, vehicle, [site.operation_perimeter, *air, takeoff, *elements], planning_margin_m)
    status = "FAIL" if any(c["status"] == "FAIL" for c in checks) else "PASS"
    return {"status": status, "checks": checks, "route_local": [list(p) for p in route], "labels": labels,
            "margin": margin, "unchecked": [c["check"] for c in checks if c["status"] == "NOT_CHECKABLE"],
            "scope": "planned straight lines, including the return to the planned takeoff coordinate at the "
                     "mission altitude (as exported: NAV_LAND with location, no RTL); not the flown trajectory"}


def validate_ground_route(site: Site, start_id: str, target_id: str, planning_margin_m: float,
                          vehicle: FleetVehicle | None = None) -> dict:
    start, target = site.point(start_id), site.point(target_id)
    if start is None or start.kind != "rover_start" or target is None or target.kind != "poi":
        return {"status": "FAIL", "checks": [_check("references", "FAIL",
                                                    f"{start_id!r} must be a rover_start and {target_id!r} a POI")]}
    return _ground_line(site, start, _xy(target), [target], planning_margin_m, vehicle)


def validate_ground_local_target(site: Site, start_id: str, target_xy: tuple[float, float] | None,
                                 planning_margin_m: float, vehicle: FleetVehicle | None = None) -> dict:
    """The same straight-line checks towards a target given in the site's local frame (e.g. a waypoint of a
    re-based finalized mission); ``None`` when that target could not be resolved."""
    start = site.point(start_id)
    if start is None or start.kind != "rover_start":
        return {"status": "FAIL", "checks": [_check("references", "FAIL", f"{start_id!r} must be a rover_start")]}
    return _ground_line(site, start, None if target_xy is None else tuple(target_xy), [], planning_margin_m, vehicle)


def _ground_line(site, start, target_xy, elements, planning_margin_m, vehicle):
    area = site.rover_drivable_area
    if area is None or area.polygon is None or _xy(start) is None or target_xy is None:
        return {"status": "NOT_CHECKABLE", "checks": [_check("drivable area", "NOT_CHECKABLE",
                                                            "no measured drivable area or points")]}
    a, b = _xy(start), target_xy
    checks = [_check("target in drivable area", "PASS" if point_location(b, area.polygon) == INSIDE else "FAIL",
                     area.zone_id)]
    within = segment_within(a, b, area.polygon)
    checks.append(_check("straight line within drivable area", "PASS" if within == INSIDE else "REQUIRES_PLANNING",
                         "the aerial perimeter is never used for the rover"))
    for zone in (z for z in site.exclusions if "ground" in z.applies_to and z.polygon is not None):
        clearance = segment_clearance(a, b, zone.polygon)
        checks.append(_check(f"ground exclusion {zone.zone_id}",
                             "PASS" if clearance >= planning_margin_m and clearance > 0 else "REQUIRES_PLANNING",
                             f"clearance {clearance:.3f} m vs margin {planning_margin_m} m"))
    statuses = {c["status"] for c in checks}
    status = "FAIL" if "FAIL" in statuses else "REQUIRES_PLANNING" if "REQUIRES_PLANNING" in statuses else "PASS"
    return {"status": status, "checks": checks, "line_local": [list(a), list(b)],
            "margin": margin_status(site, vehicle, [area, start, *elements], planning_margin_m),
            "scope": "straight planned line only; no path planner; rover frame transform not accredited"}


def route_separation(routes: dict[str, list]) -> list[dict]:
    """Minimum horizontal distance between planned routes in a common frame (spatial only, no timing)."""
    names = sorted(routes)
    result = []
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            a, b = routes[first], routes[second]
            distance = min(segment_distance(p, q, r, s) for p, q in zip(a, a[1:]) for r, s in zip(b, b[1:]))
            result.append({"pair": [first, second], "min_horizontal_distance_m": round(distance, 3),
                           "temporal_deconfliction": "NOT_EVALUATED",
                           "simultaneous_execution": "NOT_CLEARED"})
    return result
