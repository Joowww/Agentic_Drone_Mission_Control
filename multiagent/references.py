"""Typed references to aerial objectives and site points (tfg.multiagent.reference/1).

One rule for every drone tool: a reference is
- OBJECTIVE: an objective id of the current task -> its point and its required sensor (checked against the drone);
- POINT: a declared POI of the site -> that point (the objectives at it are listed; their sensors are checked too);
- UNRESOLVED: anything else (unknown id, a non-POI point, free coordinates, empty) -> refused with the reason.
Nothing is ever resolved by guessing: no nearest point, no coordinates are fabricated.
"""
from __future__ import annotations


def resolve(problem, ref) -> dict:
    if not isinstance(ref, str) or not ref.strip():
        return {"ref": ref, "kind": "UNRESOLVED", "reason": "empty or non-text reference"}
    objective = problem.objective(ref)
    if objective is not None:
        return {"ref": ref, "kind": "OBJECTIVE", "objective_ids": [ref], "point_id": objective.point_id,
                "required_sensors": [objective.required_sensor] if objective.required_sensor else []}
    point = problem.site.point(ref)
    if point is not None and point.kind == "poi":
        at = [o for o in problem.objectives if o.point_id == ref]
        return {"ref": ref, "kind": "POINT", "objective_ids": [o.objective_id for o in at], "point_id": ref,
                "required_sensors": sorted({o.required_sensor for o in at if o.required_sensor})}
    if point is not None:
        return {"ref": ref, "kind": "UNRESOLVED", "reason": f"{ref} is a {point.kind} point, not a POI"}
    return {"ref": ref, "kind": "UNRESOLVED",
            "reason": f"{ref!r} is neither an objective of this task nor a declared POI of the site"}


def resolve_sequence(problem, refs, drone=None) -> dict:
    """Resolved references, the visiting order of points (first occurrence), unresolved ones, and, when a drone is
    given, the sensor/availability/wind reasons it cannot serve the referenced objectives (swarm.eligibility)."""
    from multiagent.swarm import eligibility
    resolved = [resolve(problem, r) for r in refs]
    points, unresolved, ineligible = [], [], []
    for r in resolved:
        if r["kind"] == "UNRESOLVED":
            unresolved.append(r)
            continue
        if r["point_id"] not in points:
            points.append(r["point_id"])
        if drone is not None:
            for objective_id in r["objective_ids"]:
                ineligible += [f"{objective_id}: {reason}" for reason in
                               eligibility(problem, problem.objective(objective_id), drone)]
    return {"references": resolved, "points": points, "unresolved": unresolved, "ineligible": sorted(set(ineligible))}
