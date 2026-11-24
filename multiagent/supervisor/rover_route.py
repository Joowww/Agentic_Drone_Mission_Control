"""RoverAgent route planning: a multi-point ground route for ONE ArduRover, validated leg by leg. No ROS, no command.

Extends the single-target Rover Agent (multiagent.rover_agent.plan_ground, unchanged) to a route start -> P1 -> ... ->
Pn [-> start]. Every leg is checked with the project's ground-line rule (planning.site_validation: target inside the
declared drivable area, the straight line within it, clearance from ground exclusions); a leg that needs a path
planner is NOT feasible (no planner exists). Limits come from the scenario's DECLARED rover limits: speed, leg length,
route length and an energy model. A missing limit is a missing parameter: planning still reports the route, but the
route cannot be exported (no speed) or executed (no energy model), and nothing is invented.

Output: a ground proposal with the legs, totals, waypoints in WGS84 (from the site's declared georeference) and
the findings. It never produces TAKEOFF/LAND, never transforms into the rover's odometry frame and never authorizes.
"""
from __future__ import annotations

import math

from planning import site_validation as sv
from planning.site_geometry import local_to_geo

AGENT = "rover_agent"


def _xy(point):
    return (point.x_m, point.y_m)


def _finding(kind, detail, action):
    return {"kind": kind, "detail": detail, "action": action}


def order_points(site, start_id: str, points: list[str], ordering: str) -> list[str]:
    """AS_GIVEN keeps the operator's order; MIN_MAX_LEG searches every order (<= 7 points) for the shortest longest
    leg, then the shortest route; NEAREST_NEIGHBOUR is the greedy fallback. All deterministic."""
    if ordering == "AS_GIVEN":
        return list(points)
    if ordering == "MIN_MAX_LEG" and len(points) <= 7:
        import itertools
        start = _xy(site.point(start_id))

        def cost(seq):
            stops = [start, *[_xy(site.point(q)) for q in seq]]
            legs = [math.dist(a, b) for a, b in zip(stops, stops[1:])]
            return (round(max(legs), 6), round(sum(legs), 6), seq)
        return list(min((cost(list(seq)) for seq in itertools.permutations(points)))[2])
    if ordering not in ("NEAREST_NEIGHBOUR", "MIN_MAX_LEG"):
        raise ValueError(f"unknown ordering {ordering!r}")
    remaining, route, here = list(points), [], _xy(site.point(start_id))
    while remaining:
        nxt = min(remaining, key=lambda p: (math.dist(here, _xy(site.point(p))), p))
        route.append(nxt)
        remaining.remove(nxt)
        here = _xy(site.point(nxt))
    return route


def plan_rover_route(*, site, fleet, context, limits, rover_id: str, points: list[str], return_to_start: bool,
                     ordering: str = "AS_GIVEN", tracer=None) -> dict:
    findings, legs = [], []
    profile = next((r for r in context.rovers if r.vehicle_id == rover_id), None)
    vehicle = fleet.vehicle(rover_id)
    base = {"agent": AGENT, "vehicle_id": rover_id, "task_id": f"GROUND_{rover_id}", "kind": "GROUND_ROUTE",
            "return_to_start": return_to_start, "ordering": ordering, "movement_authorized": False,
            "commands_sent": 0, "state": "PENDING_AUTHORIZATION"}
    if profile is None or vehicle is None or vehicle.category != "rover":
        return {**base, "status": "INFEASIBLE", "legs": [], "waypoints": [],
                "findings": [_finding("ROVER_NOT_DECLARED", rover_id, "REJECTED")]}
    unknown = [p for p in points if site.point(p) is None or site.point(p).kind != "poi"]
    if unknown:
        return {**base, "status": "NEEDS_CLARIFICATION", "legs": [], "waypoints": [],
                "findings": [_finding("UNKNOWN_GROUND_POINT", f"{unknown} are not declared site POIs", "CLARIFY")]}
    if len(set(points)) != len(points):
        findings.append(_finding("DUPLICATE_GROUND_POINT", str(points), "REJECTED"))
    start = site.point(profile.start_point)
    route = order_points(site, profile.start_point, points, ordering)
    stops = [start, *[site.point(p) for p in route]] + ([start] if return_to_start else [])
    total = 0.0
    for a, b in zip(stops, stops[1:]):
        if a.kind == "rover_start":
            check = sv.validate_ground_route(site, a.point_id, b.point_id, context.planning_margin_m, vehicle)
        else:  # POI -> POI and POI -> start: the same ground-line rule, from a declared point
            check = sv._ground_line(site, a, _xy(b), [b] if b.kind == "poi" else [], context.planning_margin_m,
                                    vehicle)
        length = math.dist(_xy(a), _xy(b))
        total += length
        leg = {"from": a.point_id, "to": b.point_id, "length_m": round(length, 3), "status": check["status"],
               "failed_checks": [c for c in check.get("checks", []) if c["status"] != "PASS"]}
        legs.append(leg)
        if tracer is not None:
            tracer.validation(AGENT, f"ground_leg:{rover_id}:{a.point_id}->{b.point_id}", check["status"],
                              leg["failed_checks"])
        if check["status"] != "PASS":
            findings.append(_finding("ROUTE_NOT_FEASIBLE", f"leg {a.point_id}->{b.point_id}: " + "; ".join(
                f"{c['check']}: {c['detail']}" for c in leg["failed_checks"]) + " (no path planner exists)",
                "REJECTED"))
        if limits.max_leg_length_m is not None and length > limits.max_leg_length_m:
            findings.append(_finding("LEG_TOO_LONG", f"{a.point_id}->{b.point_id} {length:.1f} m > "
                                     f"{limits.max_leg_length_m} m", "REJECTED"))
    if limits.max_route_length_m is not None and total > limits.max_route_length_m:
        findings.append(_finding("ROUTE_TOO_LONG", f"{total:.1f} m > {limits.max_route_length_m} m", "REJECTED"))
    if limits.max_speed_mps is None:
        findings.append(_finding("SPEED_LIMIT_NOT_DECLARED", "no declared rover speed limit: no .plan, no timeout",
                                 "PENDING_PARAMETERS"))
        duration = timeout = None
    else:
        duration = total / limits.max_speed_mps
        timeout = duration * limits.timeout_margin_factor
    energy = {"status": "NOT_EVALUATED", "basis": None}
    if None in (limits.battery_percent, limits.consumption_percent_per_km, limits.minimum_battery_reserve_percent):
        findings.append(_finding("ENERGY_MODEL_NOT_DECLARED", "rover battery/consumption/reserve not declared; "
                                 "the route cannot be checked against a battery", "PENDING_PARAMETERS"))
    else:
        need = total / 1000.0 * limits.consumption_percent_per_km
        remaining = limits.battery_percent - need
        energy = {"status": "PASS" if remaining >= limits.minimum_battery_reserve_percent else "FAIL",
                  "required_percent": round(need, 3), "remaining_percent": round(remaining, 3),
                  "reserve_percent": limits.minimum_battery_reserve_percent,
                  "basis": f"declared linear model ({limits.provenance}); not a measured discharge"}
        if energy["status"] == "FAIL":
            findings.append(_finding("BATTERY_INSUFFICIENT", f"route needs {need:.1f} %, leaves {remaining:.1f} % < "
                                     f"reserve {limits.minimum_battery_reserve_percent} %", "REJECTED"))
    geo = site.geo_reference
    waypoints = []
    if geo is None or geo.latitude is None or geo.longitude is None:
        findings.append(_finding("GEOREFERENCE_MISSING", "waypoints cannot be placed geographically",
                                 "PENDING_PARAMETERS"))
    else:
        bearing = site.local_frame.y_axis_bearing_deg or 0.0
        for p in [start, *[site.point(q) for q in route]]:
            lat, lon = local_to_geo(p.x_m, p.y_m, origin_latitude=geo.latitude, origin_longitude=geo.longitude,
                                    y_axis_bearing_deg=bearing)
            waypoints.append({"waypoint_id": p.point_id, "latitude": lat, "longitude": lon, "x_m": p.x_m, "y_m": p.y_m})
    actions = {f["action"] for f in findings}
    status = ("INFEASIBLE" if "REJECTED" in actions else "PENDING_PARAMETERS" if "PENDING_PARAMETERS" in actions
              else "PROPOSED_PENDING_AUTHORIZATION")
    return {**base, "status": status, "start_point": profile.start_point, "point_sequence": route, "legs": legs,
            "length_m": round(total, 3), "estimated_duration_s": None if duration is None else round(duration, 3),
            "timeout_s": None if timeout is None else round(timeout, 3), "speed_limit_mps": limits.max_speed_mps,
            "energy": energy, "start": waypoints[0] if waypoints else None, "waypoints": waypoints[1:],
            "availability": f"DECLARED_{profile.provenance}" if profile.available else "UNAVAILABLE",
            "frame_transform_to_rover": "NOT_APPLIED: the rover executor owns the site->odometry conversion",
            "findings": findings}
