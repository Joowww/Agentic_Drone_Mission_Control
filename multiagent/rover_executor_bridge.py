"""Bridge proposal between the Rover Agent's validated ground task and the rover's rover executor contract
(tools/rover_vehicle_contract.py, commit 218697f40 on the rover's branch: NavigationPlan, ExecutionAuthorization,
ExecutionFeedback, RoverVehicleExecutor.observe/execute/stop). The rover's code is NOT imported or modified: the same
field names are produced and checked as plain dicts, so the hand-off can be wired later without changing either side.

Separation kept explicit: the LLM proposes (a typed decision); rover_gate + the deterministic rover agent validate;
the supervisor's coordinator makes it READY_FOR_AUTHORIZATION; a HUMAN authorizes a scope (speed, timeout, the exact
plan); only then could an executor be called, and only after every precondition below holds at that moment.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def navigation_plan(task: dict, site, *, proposal_sha256: str, human_limits: dict) -> dict:
    """NavigationPlan fields from a validated ground task. Target = the declared POI in the SITE frame; speed and
    timeout come only from ``human_limits`` (part of the human authorization), never from a model reply."""
    point = site.point(task["target_point"])
    if point is None or point.kind != "poi" or point.x_m is None or point.y_m is None:
        raise ValueError(f"{task.get('target_point')!r} is not a declared POI with coordinates")
    for key in ("max_speed_mps", "timeout_s"):
        if not isinstance(human_limits.get(key), (int, float)) or human_limits[key] <= 0:
            raise ValueError(f"{key} must be set by the human authorization")
    body = {"frame": site.local_frame.frame_id, "target_x_m": point.x_m, "target_y_m": point.y_m,
            "max_speed_mps": float(human_limits["max_speed_mps"]), "timeout_s": float(human_limits["timeout_s"])}
    return {"plan_id": "NAV-" + _sha({"task": task["task_id"], "proposal": proposal_sha256, **body})[:16], **body}


def authorization_scope(plan: dict, *, proposal_sha256: str, vehicle_id: str) -> str:
    """ExecutionAuthorization.scope_sha256: what exactly a human authorizes (this plan, this vehicle, this proposal)."""
    return _sha({"plan": plan, "vehicle_id": vehicle_id, "proposal_sha256": proposal_sha256})


def preconditions(*, plan: dict, authorization: dict | None, expected_scope: str, capabilities: dict, state: dict,
                  health: dict, state_at: datetime | None, now: datetime, max_state_age_s: float = 1.0,
                  adapter_dry_run: bool = True, request: dict | None = None) -> list[str]:
    """Every reason not to call execute(); [] only if all hold NOW. Order: authority, localization, freshness, health.
    The authority is a tfg.multiagent.human-authorization/1 RECORD checked against its request (plan and scope
    digests recomputed); a boolean or a bare scope is never an authorization."""
    from multiagent import human_authorization as ha
    reasons = []
    if not authorization:
        reasons.append("NOT_AUTHORIZED: no human authorization")
    elif authorization.get("schema") != ha.SCHEMA:
        reasons.append("NOT_AUTHORIZED: a boolean or bare scope is not a human authorization record")
    elif request is None:
        reasons.append("NOT_AUTHORIZED: the record cannot be checked without its request")
    else:
        found = ha.check(authorization, request, now=now)
        if authorization.get("scope_sha256") != expected_scope:
            found.append("SCOPE_MISMATCH: not the expected scope")
        if any(f.split(":")[0].endswith("MISMATCH") or f.startswith("TAMPERED") for f in found):
            reasons.append("AUTHORIZATION_SCOPE_MISMATCH: " + "; ".join(found[:4]))
        elif "OUTSIDE_VALIDITY_WINDOW" in found:
            reasons.append("AUTHORIZATION_EXPIRED: outside the authorization's validity window")
        elif found:
            reasons.append("NOT_AUTHORIZED: " + "; ".join(found[:4]))
    if not capabilities.get("position_sources"):
        reasons.append("NO_POSITION_SOURCE: the vehicle declares no position source; it cannot go to a coordinate")
    if state.get("frame") != plan["frame"]:
        reasons.append(f"FRAME_MISMATCH: vehicle state in {state.get('frame')!r}, plan in {plan['frame']!r} "
                       "(site-frame to odometry transform not accredited)")
    if state.get("x_m") is None or state.get("y_m") is None:
        reasons.append("NO_POSITION: the vehicle reports no position")
    if state_at is None or (now - state_at).total_seconds() > max_state_age_s:
        reasons.append(f"ODOMETRY_STALE: last state older than {max_state_age_s} s")
    if health.get("healthy") is not True:
        reasons.append(f"VEHICLE_NOT_HEALTHY: {health.get('detail')}")
    if health.get("failsafes"):
        reasons.append(f"FAILSAFE_ACTIVE: {list(health['failsafes'])}")
    cap = capabilities.get("max_speed_mps")
    if cap is None or plan["max_speed_mps"] > cap:
        reasons.append(f"SPEED_NOT_WITHIN_CAPABILITY: {plan['max_speed_mps']} vs {cap}")
    if adapter_dry_run:
        reasons.append("DRY_RUN_ADAPTER: no physical adapter exists (JetRacerDryRunAdapter refuses execute)")
    return reasons


def feedback_event(feedback: dict, *, task_id: str, at: datetime) -> dict:
    """ExecutionFeedback -> an event for the supervisor's coordinator. Errors propagate; nothing is inferred from silence."""
    status = feedback.get("status")
    if feedback.get("physical_effect"):
        kind = "GROUND_TASK_PHYSICAL_EFFECT_REPORTED"  # never expected offline; the supervisor must stop and review
    elif status in ("REFUSED_DRY_RUN_ONLY", "NO_PHYSICAL_OUTPUT") or str(status).startswith("REFUSED"):
        kind = "GROUND_TASK_REFUSED_BY_EXECUTOR"
    elif feedback.get("error"):
        kind = "GROUND_TASK_FAILED"
    else:
        kind = "GROUND_TASK_STATUS"
    return {"type": kind, "task_id": task_id, "status": status, "error": feedback.get("error"),
            "physical_effect": bool(feedback.get("physical_effect")), "at": at}


def stop_request(*, task_id: str, reason: str, at: datetime) -> dict:
    """What the supervisor sends when it must stop a ground task: always allowed, needs no authorization, and the
    executor's stop() feedback is propagated with feedback_event (NO_PHYSICAL_OUTPUT on the dry-run adapter)."""
    return {"type": "STOP_REQUESTED", "task_id": task_id, "reason": reason, "at": at, "call": "RoverVehicleExecutor.stop()"}


# ------------------------------------------------------------------- neutral request + dry-run executor --
REQUEST_SCHEMA = "tfg.multiagent.rover-execution-request/1"


def execution_request(task: dict, site, *, proposal: dict, dependencies: list[dict], human_limits: dict | None,
                      authorization: dict | None = None) -> dict:
    """A versioned, executor-neutral request: the validated ground task, its NavigationPlan (only if a human set the
    limits), its dependencies and the authorization slot. It never carries an implicit authorization: the slot is
    None unless a human authorization object is passed, and building it grants nothing."""
    plan = navigation_plan(task, site, proposal_sha256=proposal["proposal_sha256"], human_limits=human_limits) \
        if human_limits else None
    scope = authorization_scope(plan, proposal_sha256=proposal["proposal_sha256"], vehicle_id=task["vehicle_id"]) \
        if plan else None
    return {"schema": REQUEST_SCHEMA, "task_id": task["task_id"], "vehicle_id": task["vehicle_id"],
            "proposal_sha256": proposal["proposal_sha256"], "frame": site.local_frame.frame_id,
            "target": {"point_id": task["target_point"], "start_point": task.get("start_point")},
            "dependencies": [d for d in dependencies if d.get("task_id") == task["task_id"]],
            "navigation_plan": plan, "expected_scope_sha256": scope,
            "authorization": authorization, "state": "AWAITING_HUMAN_AUTHORIZATION" if authorization is None else
            "AUTHORIZATION_ATTACHED_NOT_EXECUTED"}


def validate_request(req: dict) -> list[str]:
    """What an executor checks before even looking at its own preconditions."""
    problems = []
    if req.get("schema") != REQUEST_SCHEMA:
        problems.append(f"UNKNOWN_SCHEMA: {req.get('schema')!r}")
    for key in ("task_id", "vehicle_id", "proposal_sha256", "frame", "target", "dependencies"):
        if req.get(key) in (None, ""):
            problems.append(f"MISSING_FIELD: {key}")
    if req.get("navigation_plan") is None:
        problems.append("NO_NAVIGATION_PLAN: speed and timeout were not set by a human")
    elif req["navigation_plan"].get("frame") != req.get("frame"):
        problems.append("FRAME_MISMATCH: request and plan frames differ")
    if not (req.get("target") or {}).get("point_id"):
        problems.append("CONDITIONAL_TARGET: no validated target; a conditional task never produces movement")
    return problems


class DryRunRoverExecutor:
    """Behaves like the rover's JetRacerDryRunAdapter (tools/jetracer_dry_run_adapter.py @218697f40), as dicts: no driver,
    no position source, execute() always refused, stop() without physical output. Physical effect is always False."""
    physical_effect = False

    def identity(self):
        return {"vehicle_id": "jetracer-unconfigured", "platform": "Waveshare JetRacer Pro AI Kit", "firmware": None}

    def capabilities(self):
        return {"steering_model": "ACKERMANN", "max_speed_mps": None,
                "sensors": ("IMX219_CAMERA_UNVERIFIED_MODIFICATIONS",), "position_sources": ()}

    def observe(self):
        return ({"x_m": None, "y_m": None, "frame": None},
                {"healthy": None, "detail": "No hardware driver or sensor source configured", "failsafes": ()})

    def execute(self, plan, authorization):
        return {"status": "REFUSED_DRY_RUN_ONLY", "state": None, "error": "No physical adapter is implemented; plan is not sent",
                "physical_effect": False}

    def stop(self):
        return {"status": "NO_PHYSICAL_OUTPUT", "state": None, "error": "No actuator interface exists in this adapter",
                "physical_effect": False}
