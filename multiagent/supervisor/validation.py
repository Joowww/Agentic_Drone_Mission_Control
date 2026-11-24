"""Global validation of the supervisor's plan: coverage, duplicates, separation, air-ground conflicts, dependencies,
registry and file-level checks of each ``.plan``. Individual checks stay with their owners (drone agent + Hermes
validation + the strict exporters' verifiers); this module only combines and cross-checks them.

Air-ground conflicts are spatial only (horizontal distance between planned straight lines). Timing is not modelled
for the rover, so a proximity below the declared separation is RESOLVED only by an explicit ordering dependency (the
rover starts after every drone task COMPLETED); otherwise it is a conflict. Nothing here is a physical guarantee.
"""
from __future__ import annotations

from planning.site_geometry import segment_distance

from multiagent.supervisor import registry as reg

ARDUCOPTER_TYPES, ARDUROVER_TYPES = {2}, {10}


def _segments(points):
    return list(zip(points, points[1:])) if len(points) > 1 else [(points[0], points[0])] if points else []


def min_distance(route_a, route_b) -> float | None:
    if not route_a or not route_b:
        return None
    return min(segment_distance(a1, a2, b1, b2) for a1, a2 in _segments(route_a) for b1, b2 in _segments(route_b))


def _check(name, status, detail=None):
    return {"check": name, "status": status, "detail": detail}


def dependency_cycle(dependencies: list[dict]) -> list[str] | None:
    graph = {}
    for d in dependencies:
        graph.setdefault(d["task_id"], set()).add(d["after"])
    seen, stack = set(), []

    def visit(node):
        if node in stack:
            return stack[stack.index(node):] + [node]
        if node in seen:
            return None
        seen.add(node)
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            cycle = visit(nxt)
            if cycle:
                return cycle
        stack.pop()
        return None

    for n in sorted(graph):
        cycle = visit(n)
        if cycle:
            return cycle
    return None


def validate_global(*, plan: dict, registry: dict, separation_policy, files: dict) -> dict:
    """``plan``: the supervisor's assembled plan (aerial tasks, ground task, sectors, ground points, dependencies).
    ``files``: {vehicle_id: {"header": plan_header, "verify": verifier result}}."""
    checks = []
    air, ground = plan["aerial_tasks"], plan.get("ground_task")
    # coverage: every declared survey point of every sector, every ground point
    wanted_air = [p for s in plan["sectors"] for p in s["points"]]
    covered = [p for t in air for p in t["poi_sequence"]]
    missing = sorted(set(wanted_air) - set(covered))
    checks.append(_check("aerial coverage", "FAIL" if missing else "PASS", {"missing": missing}))
    dup = sorted({p for p in covered if covered.count(p) > 1})
    checks.append(_check("aerial points visited once", "FAIL" if dup else "PASS", dup))
    if plan["ground_points"]:
        got = (ground or {}).get("point_sequence") or []
        miss = sorted(set(plan["ground_points"]) - set(got))
        checks.append(_check("ground coverage", "FAIL" if miss or ground is None else "PASS", {"missing": miss}))
    # registry: every assigned vehicle exists, is available and of the right class
    for task in [*air, *([ground] if ground else [])]:
        v = reg.vehicle(registry, task["vehicle_id"])
        ok = v is not None and v["availability"]["status"] == "AVAILABLE_DECLARED"
        checks.append(_check(f"registry {task['vehicle_id']}", "PASS" if ok else "FAIL",
                             None if ok else (v or {}).get("availability")))
    # file headers: the .plan type matches the registry class; no aerial command in a ground plan
    for vid, f in files.items():
        v = reg.vehicle(registry, vid) or {}
        header = f.get("header") or {}
        expected = ARDUROVER_TYPES if v.get("vehicle_class") == "ArduRover" else ARDUCOPTER_TYPES
        ok = header.get("firmwareType") == 3 and header.get("vehicleType") in expected
        if v.get("vehicle_class") == "ArduRover":
            ok = ok and not {21, 22} & set(header.get("commands") or [])
        checks.append(_check(f"plan header {vid}", "PASS" if ok else "FAIL", header))
        verify = (f.get("verify") or {}).get("status")
        checks.append(_check(f"plan file {vid}", "PASS" if verify == "FILE_MATCHES_EXPECTATIONS" else "FAIL", verify))
    # drone-drone separation (planning-time, from the drone agent's deconfliction)
    if len(air) > 1:
        status = (plan.get("swarm_coordination") or {}).get("status")
        checks.append(_check("drone separation", "PASS" if status in ("CLEAR", "DECONFLICTED_BY_START_DELAY")
                             else "FAIL", status))
    # air-ground proximity -> needs an ordering dependency
    deps = plan["dependencies"]
    if ground is not None and air:
        required = separation_policy.required_distance_m() if separation_policy else None
        rover_route = [(w["x_m"], w["y_m"]) for w in ([ground["start"]] if ground.get("start") else [])
                       + ground.get("waypoints", [])]
        for t in air:
            d = min_distance([tuple(p) for p in t["route_local"]], rover_route)
            ordered = any(x["task_id"] == ground["task_id"] and x["after"] == t["task_id"]
                          and x["condition"] == "COMPLETED" for x in deps)
            if required is None:
                status = "PASS" if ordered else "FAIL"
                detail = "no declared separation policy: only an ordering dependency resolves it"
            elif d is not None and d < required:
                status = "PASS" if ordered else "FAIL"
                detail = f"min {d:.2f} m < {required:.2f} m: " + ("resolved by ordering" if ordered else "CONFLICT")
            else:
                status, detail = "PASS", f"min {d:.2f} m >= {required:.2f} m"
            checks.append(_check(f"air-ground {t['vehicle_id']}/{ground['vehicle_id']}", status, detail))
    tasks = {t["task_id"] for t in air} | ({ground["task_id"]} if ground else set())
    bad = [d for d in deps if d["task_id"] not in tasks or d["after"] not in tasks]
    checks.append(_check("dependencies reference planned tasks", "FAIL" if bad else "PASS", bad))
    cycle = dependency_cycle(deps)
    checks.append(_check("dependencies acyclic", "FAIL" if cycle else "PASS", cycle))
    status = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
    return {"status": status, "checks": checks,
            "scope": "planning-time checks over declared inputs; not a physical separation guarantee"}
