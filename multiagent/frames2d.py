"""Planar rigid frames for the ground target: site -> rover map/odom -> rover base_link. Pure geometry with provenance;
no vehicle, no default frame, no zero filled in for something unknown.

A Transform maps coordinates expressed in ``child`` into ``parent`` (p_parent = R(yaw) p_child + t). It carries units
(m, rad), a validity window, a provenance (source + sha256) and an accreditation flag, and a first-order uncertainty
(translation sigma in m, heading sigma in rad). Composition propagates uncertainty and intersects validity; the
inverse keeps provenance. The matrix form is the rover's v2 shape ([[c,-s,tx],[s,c,ty],[0,0,1]], source_frame=child,
target_frame=parent), so the same transform can be checked by rover_sitl_interfaces.transform_problems (= the rover's
rules). A FrameGraph resolves a chain between two frames and refuses unknown frames, inaccessible frames and loops
whose paths disagree.

goal_for_rover() is what the coordinator calls before anything is handed to an executor: site goal -> rover frame,
with every check below; it never moves anything.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import math

LOOP_TOL_M, LOOP_TOL_RAD = 1e-6, 1e-9


def _finite(*vals) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in vals)


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


@dataclass(frozen=True)
class Transform:
    parent: str
    child: str
    x_m: float
    y_m: float
    yaw_rad: float
    sigma_m: float
    sigma_rad: float
    not_before: datetime
    expires: datetime
    source: str
    source_sha256: str
    accredited: bool
    unit_length: str = "m"
    unit_angle: str = "rad"
    chain: tuple = field(default=())

    def problems(self, now: datetime) -> list[str]:
        out = []
        if not self.parent or not self.child or self.parent == self.child:
            out.append("FRAME_IDENTITY_INVALID")
        if self.unit_length != "m" or self.unit_angle != "rad":
            out.append(f"UNITS_INVALID: {self.unit_length}/{self.unit_angle}")
        if not _finite(self.x_m, self.y_m, self.yaw_rad):
            out.append("POSE_NOT_FINITE")
        if not _finite(self.sigma_m, self.sigma_rad) or self.sigma_m < 0 or self.sigma_rad < 0:
            out.append("UNCERTAINTY_INVALID")
        if not self.accredited:
            out.append("NOT_ACCREDITED")
        sha = self.source_sha256
        if not self.source or not (isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
            out.append("PROVENANCE_MISSING")
        if self.not_before >= self.expires:
            out.append("VALIDITY_INVALID")
        elif not self.not_before <= now < self.expires:
            out.append("EXPIRED_OR_NOT_YET_VALID")
        return out

    def apply(self, x: float, y: float) -> tuple[float, float]:
        c, s = math.cos(self.yaw_rad), math.sin(self.yaw_rad)
        return c * x - s * y + self.x_m, s * x + c * y + self.y_m

    def inverse(self) -> "Transform":
        c, s = math.cos(self.yaw_rad), math.sin(self.yaw_rad)
        return replace(self, parent=self.child, child=self.parent, x_m=-(c * self.x_m + s * self.y_m),
                       y_m=-(-s * self.x_m + c * self.y_m), yaw_rad=_wrap(-self.yaw_rad),
                       sigma_m=math.hypot(self.sigma_m, math.hypot(self.x_m, self.y_m) * self.sigma_rad),
                       chain=self.chain + (f"inverse({self.parent}<-{self.child})",))

    def matrix(self) -> list[list[float]]:
        c, s = math.cos(self.yaw_rad), math.sin(self.yaw_rad)
        return [[c, -s, self.x_m], [s, c, self.y_m], [0.0, 0.0, 1.0]]

    def to_rover_matrix(self) -> dict:
        """The rover v2 transform dict (source_frame = child, target_frame = parent)."""
        return {"source_frame": self.child, "target_frame": self.parent, "validated": self.accredited,
                "source": self.source, "source_sha256": self.source_sha256, "matrix": self.matrix(),
                "uncertainty_m": self.sigma_m, "uncertainty_rad": self.sigma_rad,
                "not_before_utc": self.not_before.isoformat(), "expires_at_utc": self.expires.isoformat()}


def compose(a_from_b: Transform, b_from_c: Transform) -> Transform:
    """a<-c = a<-b o b<-c. The child of the first must be the parent of the second."""
    if a_from_b.child != b_from_c.parent:
        raise ValueError(f"FRAME_MISMATCH: {a_from_b.parent}<-{a_from_b.child} o {b_from_c.parent}<-{b_from_c.child}")
    x, y = a_from_b.apply(b_from_c.x_m, b_from_c.y_m)
    lever = math.hypot(b_from_c.x_m, b_from_c.y_m)
    return Transform(parent=a_from_b.parent, child=b_from_c.child, x_m=x, y_m=y,
                     yaw_rad=_wrap(a_from_b.yaw_rad + b_from_c.yaw_rad),
                     sigma_m=math.sqrt(a_from_b.sigma_m ** 2 + b_from_c.sigma_m ** 2 + (lever * a_from_b.sigma_rad) ** 2),
                     sigma_rad=math.hypot(a_from_b.sigma_rad, b_from_c.sigma_rad),
                     not_before=max(a_from_b.not_before, b_from_c.not_before),
                     expires=min(a_from_b.expires, b_from_c.expires),
                     source=f"{a_from_b.source}+{b_from_c.source}",
                     source_sha256=hashlib.sha256((a_from_b.source_sha256 + b_from_c.source_sha256).encode()).hexdigest()
                     if a_from_b.accredited and b_from_c.accredited else "",
                     accredited=a_from_b.accredited and b_from_c.accredited,
                     unit_length="m" if a_from_b.unit_length == b_from_c.unit_length == "m" else "INCONSISTENT",
                     unit_angle="rad" if a_from_b.unit_angle == b_from_c.unit_angle == "rad" else "INCONSISTENT",
                     chain=(a_from_b.chain or (f"{a_from_b.parent}<-{a_from_b.child}",)) +
                           (b_from_c.chain or (f"{b_from_c.parent}<-{b_from_c.child}",)))


class FrameGraph:
    """Registered transforms (each usable in both directions). resolve(target, source) gives target<-source."""

    def __init__(self, transforms=()):
        self.edges: dict[str, list[tuple[str, Transform, Transform]]] = {}  # (next, next<-node, ORIGINAL)
        for t in transforms:
            self.add(t)

    def add(self, t: Transform) -> None:
        self.edges.setdefault(t.parent, []).append((t.child, t.inverse(), t))  # parent -> child: child<-parent
        self.edges.setdefault(t.child, []).append((t.parent, t, t))            # child -> parent: parent<-child

    def frames(self) -> set[str]:
        return set(self.edges)

    def resolve(self, target: str, source: str, *, now: datetime) -> Transform:
        if target not in self.edges or source not in self.edges:
            raise ValueError(f"UNKNOWN_FRAME: {sorted({target, source} - self.frames())}")
        if target == source:
            raise ValueError("SAME_FRAME: no transform needed (and none is invented)")
        paths = self._paths(source, target)
        if not paths:
            raise ValueError(f"NO_CHAIN: {source} -> {target}")
        # the REGISTERED transforms are checked, never derived ones (an inverse would hide e.g. a negative sigma)
        bad = sorted({f"{o.parent}<-{o.child}: {p}" for path in paths for _, o in path for p in o.problems(now)})
        if bad:
            raise ValueError("CHAIN_NOT_USABLE: " + "; ".join(bad))
        results = []
        for path in paths:
            acc = None
            for t, _ in path:       # t: next<-current; acc: current<-source
                acc = t if acc is None else compose(t, acc)
            results.append(acc)
        first = results[0]
        for other in results[1:]:  # a loop must close: every path gives the same transform
            if (abs(other.x_m - first.x_m) > LOOP_TOL_M or abs(other.y_m - first.y_m) > LOOP_TOL_M
                    or abs(_wrap(other.yaw_rad - first.yaw_rad)) > LOOP_TOL_RAD):
                raise ValueError("CIRCULAR_INCONSISTENT: two chains between the frames disagree")
        problems = first.problems(now)
        if problems:
            raise ValueError("CHAIN_NOT_USABLE: " + ", ".join(problems))
        return first

    def _paths(self, source: str, target: str, limit: int = 8) -> list[list[tuple[Transform, Transform]]]:
        out, queue = [], deque([(source, [], {source})])
        while queue and len(out) < limit:
            node, path, seen = queue.popleft()
            for nxt, t, original in self.edges.get(node, []):
                if nxt == target:
                    out.append(path + [(t, original)])
                elif nxt not in seen and len(path) < 6:
                    queue.append((nxt, path + [(t, original)], seen | {nxt}))
        return out


def goal_for_rover(goal: dict, graph: FrameGraph, *, rover_frame: str, localization: dict | None, limits: dict,
                   now: datetime, authorized_area: list[tuple[float, float]] | None,
                   rover_identity: dict | None = None, apply: bool = True) -> dict:
    """``goal``: {frame, x_m, y_m, sigma_m} in the site frame (from the perception gate). ``localization``: the
    rover's ACCREDITED pose {frame, x_m, y_m, yaw_rad, sigma_m, validated, source, source_sha256, observed_at}.
    ``limits``: max_total_sigma_m, localization_max_age_s, max_distance_m. ``authorized_area``: polygon in the
    site frame. Returns status OK with the goal in rover_frame (and relative to base_link), or REFUSED with every
    reason. Nothing defaults: a missing input is a reason.

    ``apply=False`` (the conversion belongs to another component, e.g. the rover's executor adapter): the SAME checks run
    and the transform is resolved and described (``transform_reference``), but the goal is NOT converted: no
    ``goal_rover``, no ``conversion``. The one check that needs the converted goal (distance from the rover) is listed
    in ``delegated_checks`` for the converting component."""
    reasons = []
    out = {"status": None, "reasons": reasons, "goal_rover": None, "goal_base_link": None, "chain": None,
           "applied": False, "transform_reference": None, "delegated_checks": []}
    if not isinstance(goal, dict) or not _finite(goal.get("x_m"), goal.get("y_m"), goal.get("sigma_m")):
        reasons.append("GOAL_INVALID")
    if authorized_area is None:
        reasons.append("AUTHORIZED_AREA_UNKNOWN")
    elif not reasons and not _inside((goal["x_m"], goal["y_m"]), authorized_area):
        reasons.append("GOAL_OUTSIDE_AUTHORIZED_AREA")
    loc_ok = isinstance(localization, dict) and localization.get("validated") is True
    if not loc_ok:
        reasons.append("ROVER_LOCALIZATION_NOT_ACCREDITED")
    else:
        sha = localization.get("source_sha256")
        if not localization.get("source") or not (isinstance(sha, str) and len(sha) == 64):
            reasons.append("ROVER_LOCALIZATION_PROVENANCE_MISSING")
        if rover_identity is not None:  # the pose must be THIS rover's, from its CURRENT boot
            if localization.get("vehicle_id") != rover_identity.get("vehicle_id"):
                reasons.append(f"ROVER_IDENTITY_MISMATCH: {localization.get('vehicle_id')} vs {rover_identity.get('vehicle_id')}")
            if localization.get("boot_id") != rover_identity.get("boot_id"):
                reasons.append(f"ROVER_BOOT_CHANGED: pose from boot {localization.get('boot_id')}, "
                               f"rover now {rover_identity.get('boot_id')}")
        if localization.get("frame") != rover_frame:
            reasons.append(f"ROVER_LOCALIZATION_FRAME_MISMATCH: {localization.get('frame')} vs {rover_frame}")
        if not _finite(localization.get("x_m"), localization.get("y_m"), localization.get("yaw_rad"),
                       localization.get("sigma_m")):
            reasons.append("ROVER_POSE_NOT_FINITE")
        at = localization.get("observed_at")
        if not isinstance(at, datetime) or at > now:
            reasons.append("ROVER_LOCALIZATION_TIME_INVALID")
        elif limits.get("localization_max_age_s") is None or (now - at).total_seconds() > limits["localization_max_age_s"]:
            reasons.append("ROVER_LOCALIZATION_STALE")
    chain = None
    if not reasons or (goal and isinstance(goal, dict) and goal.get("frame")):
        try:
            chain = graph.resolve(rover_frame, goal.get("frame"), now=now)
        except (ValueError, AttributeError) as exc:
            reasons.append(str(exc).split(":")[0] + ": " + str(exc).split(":", 1)[-1].strip())
    if chain is not None and not [r for r in reasons if r.startswith("GOAL_INVALID")]:
        lever = math.hypot(goal["x_m"], goal["y_m"])
        sigma = math.sqrt(goal["sigma_m"] ** 2 + chain.sigma_m ** 2 + (lever * chain.sigma_rad) ** 2)
        out["chain"] = list(chain.chain)
        out["transform_reference"] = {"target_frame": rover_frame, "source_frame": goal["frame"],
                                      "chain": list(chain.chain), "chain_source_sha256": chain.source_sha256,
                                      "accredited": chain.accredited, "valid_until": chain.expires.isoformat(),
                                      "sigma_m": chain.sigma_m, "sigma_rad": chain.sigma_rad,
                                      "goal_sigma_after_transform_m": sigma, "rover_matrix": chain.to_rover_matrix()}
        if apply:
            gx, gy = chain.apply(goal["x_m"], goal["y_m"])
            out["goal_rover"] = {"frame": rover_frame, "x_m": gx, "y_m": gy, "sigma_m": sigma}
            out["conversion"] = {"converted_by": "multiagent.frames2d", "from": dict(goal),
                                 "to": dict(out["goal_rover"]), "chain": list(chain.chain),
                                 "chain_source_sha256": chain.source_sha256,
                                 "valid_until": chain.expires.isoformat(), "at": now.isoformat()}
            out["applied"] = True
        else:
            out["delegated_checks"].append("GOAL_DISTANCE_FROM_ROVER: needs the converted goal")
        if limits.get("max_total_sigma_m") is None:
            reasons.append("UNCERTAINTY_LIMIT_UNKNOWN")
        elif loc_ok and _finite(localization.get("sigma_m")) and \
                math.hypot(sigma, localization["sigma_m"]) > limits["max_total_sigma_m"]:
            reasons.append(f"UNCERTAINTY_TOO_HIGH: {math.hypot(sigma, localization['sigma_m']):.3f} m > "
                           f"{limits['max_total_sigma_m']} m")
        if apply and loc_ok and _finite(localization.get("x_m"), localization.get("y_m"), localization.get("yaw_rad")) \
                and localization.get("frame") == rover_frame:
            dx, dy = gx - localization["x_m"], gy - localization["y_m"]
            c, s = math.cos(localization["yaw_rad"]), math.sin(localization["yaw_rad"])
            out["goal_base_link"] = {"frame": "base_link", "x_m": c * dx + s * dy, "y_m": -s * dx + c * dy}
            if limits.get("max_distance_m") is None:
                reasons.append("DISTANCE_LIMIT_UNKNOWN")
            elif math.hypot(dx, dy) > limits["max_distance_m"]:
                reasons.append(f"GOAL_BEYOND_MAX_DISTANCE: {math.hypot(dx, dy):.2f} m > {limits['max_distance_m']} m")
    out["status"] = "REFUSED" if reasons else "OK"
    return out


def _inside(p, poly) -> bool:
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside
