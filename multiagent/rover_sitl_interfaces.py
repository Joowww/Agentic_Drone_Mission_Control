"""Interfaces between the multi-agent planner and the rover's PROTECTED ArduRover executor (SITL first). Types and pure
functions only: no control loop, no command, no second executor. the rover's executor implements RoverExecutorPort; this
side only prepares what it consumes and maps what it reports back into coordinator events.

Flow (future): Mission Orchestrator -> Drone Agent -> Rover Agent -> Mission Coordinator -> rover execution bridge ->
safety validator (handoff_checks + the rover v2 validator) -> ArduRover executor (the rover side) -> ArduRover SITL -> Gazebo.

Frames: the agents plan in the SITE frame (declared POIs). The rover navigates in its ODOMETRY frame ("odom"). A
target crosses frames only through an ACCREDITED rigid 2-D transform in the rover's v2 shape (validated, provenance,
uncertainty, validity window); without one, nothing is converted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Protocol

RIGID_TOL = 1e-6


@dataclass(frozen=True)
class SiteGoal:
    """A validated ground target in the site frame (from the perception gate)."""
    frame: str
    x_m: float
    y_m: float
    sigma_m: float
    observation_id: str
    matched_poi: str


def transform_problems(t: dict | None, *, source_frame: str, target_frame: str, now: datetime) -> list[str]:
    """The same acceptance rules as the rover's v2 _valid_transform (tested against it): [] = usable now."""
    if not isinstance(t, dict):
        return ["FRAME_TRANSFORM_REQUIRED"]
    out = []
    if t.get("source_frame") != source_frame or t.get("target_frame") != target_frame or source_frame == target_frame:
        out.append("FRAME_TRANSFORM_ENDPOINT_MISMATCH")
    if t.get("validated") is not True:
        out.append("FRAME_TRANSFORM_NOT_VALIDATED")
    sha = t.get("source_sha256")
    if not t.get("source") or not (isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
        out.append("FRAME_TRANSFORM_PROVENANCE_MISSING")
    m = t.get("matrix")
    if not (isinstance(m, list) and len(m) == 3 and all(isinstance(r, list) and len(r) == 3 for r in m)
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for r in m for v in r)):
        out.append("FRAME_TRANSFORM_MATRIX_INVALID")
    else:
        (a, b, _), (c, d, _), bottom = m
        if (abs(bottom[0]) > RIGID_TOL or abs(bottom[1]) > RIGID_TOL or abs(bottom[2] - 1) > RIGID_TOL
                or abs(a * a + c * c - 1) > RIGID_TOL or abs(b * b + d * d - 1) > RIGID_TOL
                or abs(a * b + c * d) > RIGID_TOL or abs(a * d - b * c - 1) > RIGID_TOL):
            out.append("FRAME_TRANSFORM_NOT_RIGID_2D")
    if not all(isinstance(t.get(k), (int, float)) and math.isfinite(t[k]) and t[k] >= 0
               for k in ("uncertainty_m", "uncertainty_rad")):
        out.append("FRAME_TRANSFORM_UNCERTAINTY_INVALID")
    try:
        start, end = datetime.fromisoformat(t["not_before_utc"]), datetime.fromisoformat(t["expires_at_utc"])
        if start >= end:
            out.append("FRAME_TRANSFORM_VALIDITY_INVALID")
        elif start > now or end <= now:
            out.append("FRAME_TRANSFORM_EXPIRED_OR_NOT_YET_VALID")
    except (KeyError, TypeError, ValueError):
        out.append("FRAME_TRANSFORM_VALIDITY_INVALID")
    return out


def site_goal_to_odom(goal: SiteGoal, odom_from_site: dict, *, now: datetime) -> dict:
    """The goal in the rover's odom frame, with first-order uncertainty: sigma^2 = goal^2 + transform_m^2 +
    (range x transform_rad)^2 (range from the transform origin). Refuses (raises) without an accredited transform."""
    problems = transform_problems(odom_from_site, source_frame=goal.frame, target_frame="odom", now=now)
    if problems:
        raise ValueError("NO_ACCREDITED_TRANSFORM: " + ", ".join(problems))
    (a, b, tx), (c, d, ty), _ = odom_from_site["matrix"]
    x, y = a * goal.x_m + b * goal.y_m + tx, c * goal.x_m + d * goal.y_m + ty
    rng = math.hypot(goal.x_m, goal.y_m)
    sigma = math.sqrt(goal.sigma_m ** 2 + odom_from_site["uncertainty_m"] ** 2 +
                      (rng * odom_from_site["uncertainty_rad"]) ** 2)
    return {"frame": "odom", "x_m": round(x, 6), "y_m": round(y, 6), "sigma_m": round(sigma, 6),
            "from": {"frame": goal.frame, "x_m": goal.x_m, "y_m": goal.y_m},
            "transform_sha256": odom_from_site["source_sha256"], "observation_id": goal.observation_id}


class RoverExecutorPort(Protocol):
    """What the rover's protected executor exposes to this side (implemented ONLY there; the dry-run adapter here)."""

    def observe(self) -> tuple[dict, dict]: ...                       # state (incl. localization), health
    def submit(self, payload: dict, authorization_receipt: dict) -> dict: ...  # v2 payload READY_TO_SUBMIT + receipt
    def status(self, task_id: str) -> dict: ...                       # RUNNING / COMPLETED / FAILED / ...
    def stop(self, reason: str) -> dict: ...                          # always allowed; acknowledged by observation


# What the executor reports -> coordinator event (EXECUTOR_FEEDBACK feedback_type). Anything else becomes UNKNOWN.
FEEDBACK_TO_EVENT = {
    "REFUSED": "GROUND_TASK_REFUSED_BY_EXECUTOR",
    "RUNNING": "GROUND_TASK_STATUS",
    "COMPLETED_UNVERIFIED": "GROUND_TASK_STATUS",   # completion is NOT accepted until the localization confirms it
    "FAILED": "GROUND_TASK_FAILED",
    "STOP_CONFIRMED_BY_OBSERVATION": "GROUND_TASK_STATUS",
}


def feedback_type(executor_status: str) -> str:
    """Unknown, uncertain or unconfirmed statuses (e.g. a STOP without an observed standstill) are passed as they are,
    and the coordinator turns any unrecognised feedback into UNKNOWN: never assumed to be success."""
    return FEEDBACK_TO_EVENT.get(executor_status, f"UNRECOGNISED:{executor_status}")
