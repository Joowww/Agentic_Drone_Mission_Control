"""Deterministic spatio-temporal separation check between individual drone plans (planning time, offline).

Time model (only what the project models; nothing finer is invented):
- each route is the planned straight segments in the site frame (pad -> POIs -> pad);
- each segment lasts the time the project's route analysis gives for that leg (wind-aware ground speed,
  tools.route_flight_analysis); acceleration, turns, hover and climb profiles are NOT modelled;
- takeoff climb and landing are DECLARED durations spent above the pad (SeparationPolicy);
- a delayed drone waits on its pad before takeoff; time on the ground is not airborne and is not checked,
  except that two drones sharing a takeoff point may never overlap in time;
- vertical separation is never credited: altitudes are relative to each drone's own effective home.

Conservative test, so it can say CLEAR but never prove a physical guarantee:
- a schedule uncertainty u(t) = timing_uncertainty_s + timing_uncertainty_fraction * elapsed widens every
  segment's time window;
- two segments conflict when their widened windows overlap AND the minimum distance between the two
  segments (anywhere along them) is below required = min_separation + 2 * position_uncertainty + extent.
This over-reports conflicts (it ignores where each drone actually is inside the overlap) and is sound only
within the declared inputs.

Resolution: drones are scheduled one by one (longest flight first, then id); each gets the smallest start
delay on the declared grid that clears every drone already scheduled, within max_start_delay_s and
max_mission_duration_s. Greedy, not optimal: a failure here means "no delay found by this rule", and the
caller then tries another allocation or rejects. Without a SeparationPolicy the result is
PENDING_MISSING_DATA, never CLEAR.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from planning.site_geometry import segment_distance

SCHEMA = "tfg.multiagent.deconfliction/1"
STATUSES = ("NOT_APPLICABLE", "CLEAR", "DECONFLICTED_BY_START_DELAY", "UNRESOLVED", "PENDING_MISSING_DATA")
ASSUMPTIONS = [
    "straight segments at the analysed ground speed; acceleration, turns, hover and climb profiles not modelled",
    "takeoff climb and landing: declared durations above the pad",
    "a delayed drone waits on its pad with motors off (no battery use while waiting)",
    "vertical separation never credited (altitudes relative to each drone's own home)",
    "ground segments are not checked, except a shared takeoff point",
    "planning declarations only: not a physical separation guarantee",
]


@dataclass(frozen=True)
class Segment:
    vehicle_id: str
    index: int
    label: str
    kind: str  # climb | leg | landing
    p0: tuple
    p1: tuple
    t0: float  # seconds from mission start, nominal
    t1: float
    start: float  # this vehicle's start (for the elapsed-time uncertainty)


def timeline(vehicle_id: str, route_local, labels, leg_minutes, policy, start_s: float = 0.0) -> list[Segment]:
    pad = tuple(route_local[0])
    t = start_s
    segments = [Segment(vehicle_id, 0, f"{labels[0]} climb", "climb", pad, pad, t, t + policy.takeoff_climb_s, start_s)]
    t += policy.takeoff_climb_s
    for i, minutes in enumerate(leg_minutes):
        duration = minutes * 60.0
        segments.append(Segment(vehicle_id, i + 1, f"{labels[i]} -> {labels[i + 1]}", "leg", tuple(route_local[i]),
                                tuple(route_local[i + 1]), t, t + duration, start_s))
        t += duration
    end = tuple(route_local[-1])
    segments.append(Segment(vehicle_id, len(leg_minutes) + 1, f"{labels[-1]} landing", "landing", end, end, t,
                            t + policy.landing_s, start_s))
    return segments


def _window(segment: Segment, policy) -> tuple[float, float]:
    u = lambda t: policy.timing_uncertainty_s + policy.timing_uncertainty_fraction * max(0.0, t - segment.start)  # noqa: E731
    return segment.t0 - u(segment.t0), segment.t1 + u(segment.t1)


def pair_conflicts(a: list[Segment], b: list[Segment], policy) -> list[dict]:
    required = policy.required_distance_m()
    conflicts = []
    for sa in a:
        wa = _window(sa, policy)
        for sb in b:
            wb = _window(sb, policy)
            overlap = (max(wa[0], wb[0]), min(wa[1], wb[1]))
            if overlap[0] > overlap[1]:
                continue
            distance = segment_distance(sa.p0, sa.p1, sb.p0, sb.p1)
            if distance < required:
                conflicts.append({"kind": "DRONE_DRONE", "vehicles": [sa.vehicle_id, sb.vehicle_id],
                                  "segments": [sa.label, sb.label], "min_distance_m": round(distance, 3),
                                  "required_m": round(required, 3),
                                  "time_overlap_s": [round(overlap[0], 2), round(overlap[1], 2)]})
    return conflicts


def _span(segments, policy):
    return _window(segments[0], policy)[0], _window(segments[-1], policy)[1]


def _shared_pad(a, b, policy) -> list[dict]:
    if a[0].p0 != b[0].p0:
        return []
    (a0, a1), (b0, b1) = _span(a, policy), _span(b, policy)
    if max(a0, b0) <= min(a1, b1):
        return [{"kind": "SHARED_TAKEOFF_POINT", "vehicles": [a[0].vehicle_id, b[0].vehicle_id],
                 "segments": ["whole mission", "whole mission"], "min_distance_m": 0.0,
                 "required_m": round(policy.required_distance_m(), 3),
                 "time_overlap_s": [round(max(a0, b0), 2), round(min(a1, b1), 2)]}]
    return []


def conflicts_between(a, b, policy):
    return _shared_pad(a, b, policy) + pair_conflicts(a, b, policy)


def deconflict(plans: dict, policy) -> dict:
    """``plans``: {vehicle_id: {"route_local": [...], "labels": [...], "leg_minutes": [...]}}."""
    base = {"schema": SCHEMA, "vehicles": sorted(plans), "assumptions": ASSUMPTIONS}
    if len(plans) <= 1:
        result = {**base, "status": "NOT_APPLICABLE", "initial_conflicts": [], "residual_conflicts": [],
                  "schedule": {v: {"start_delay_s": 0.0} for v in plans}, "reason": "one drone or none"}
        if policy is not None and plans:
            (vehicle, p), = plans.items()
            result["makespan_s"] = round(timeline(vehicle, p["route_local"], p["labels"], p["leg_minutes"], policy)[-1].t1, 2)
        return result
    missing = [v for v, p in plans.items() if not p.get("leg_minutes") or
               len(p["leg_minutes"]) != len(p["route_local"]) - 1 or
               any(not isinstance(m, (int, float)) or not math.isfinite(m) or m <= 0 for m in p["leg_minutes"])]
    if policy is None or missing:
        return {**base, "status": "PENDING_MISSING_DATA", "initial_conflicts": [], "residual_conflicts": [],
                "schedule": {}, "reason": "no declared separation policy" if policy is None else
                f"leg times missing for {missing}",
                "note": "separation NOT evaluated: two independent plans are not a coordinated swarm"}
    nominal = {v: timeline(v, p["route_local"], p["labels"], p["leg_minutes"], policy) for v, p in plans.items()}
    ids = sorted(plans)
    initial = [c for i, x in enumerate(ids) for y in ids[i + 1:] for c in conflicts_between(nominal[x], nominal[y], policy)]
    duration = {v: segs[-1].t1 for v, segs in nominal.items()}
    order = sorted(ids, key=lambda v: (-duration[v], v))
    scheduled, schedule, tried, blocked = {}, {}, {}, None
    steps = int(policy.max_start_delay_s // policy.start_delay_step_s)
    for vehicle in order:
        p = plans[vehicle]
        chosen = None
        for k in range(steps + 1):
            delay = k * policy.start_delay_step_s
            segs = timeline(vehicle, p["route_local"], p["labels"], p["leg_minutes"], policy, delay)
            if _span(segs, policy)[1] > policy.max_mission_duration_s:
                break
            found = [c for other in scheduled.values() for c in conflicts_between(segs, other, policy)]
            if not found:
                chosen = (delay, segs)
                break
            blocked = found[0]
        tried[vehicle] = k + 1
        if chosen is None:
            residual = [c for other in scheduled.values()
                        for c in conflicts_between(timeline(vehicle, p["route_local"], p["labels"], p["leg_minutes"],
                                                            policy, 0.0), other, policy)]
            return {**base, "status": "UNRESOLVED", "initial_conflicts": initial, "residual_conflicts": residual,
                    "schedule": schedule, "unscheduled": vehicle, "delays_tried": tried,
                    "blocking_example": blocked, "policy": policy.model_dump(),
                    "reason": f"no start delay <= {policy.max_start_delay_s} s within "
                              f"{policy.max_mission_duration_s} s clears {vehicle}"}
        scheduled[vehicle] = chosen[1]
        schedule[vehicle] = {"start_delay_s": chosen[0], "nominal_end_s": round(chosen[1][-1].t1, 2)}
    makespan = max(s[-1].t1 for s in scheduled.values())
    status = "CLEAR" if not initial else "DECONFLICTED_BY_START_DELAY"
    return {**base, "status": status, "initial_conflicts": initial, "residual_conflicts": [],
            "schedule": {v: schedule[v] for v in ids}, "priority_order": order, "delays_tried": tried,
            "makespan_s": round(makespan, 2), "required_distance_m": round(policy.required_distance_m(), 3),
            "policy": policy.model_dump(), "method": "greedy start-delay grid, longest flight first (not optimal)"}
