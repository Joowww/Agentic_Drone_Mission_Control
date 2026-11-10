"""A human authorization is a RECORD bound to one exact plan, never a boolean (tfg.multiagent.human-authorization/1).

What a human authorizes: this mission, this rover, this proposal, this navigation plan (sha256) and these limits,
inside a validity window, signed by an identified operator. check() recomputes the plan and scope digests from the
request itself, so an authorization for another plan, rover, proposal or speed is refused, and so is a tampered one.
Offline, records are TEST_FIXTURE only: nothing here can come from a model, and nothing here moves anything.
A validated proposal is not an authorization; an authorization is not an execution (the executor still checks).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

from multiagent import rover_executor_bridge as rb

SCHEMA = "tfg.multiagent.human-authorization/1"
ACCEPTED_SOURCES = {"OFFLINE_TEST": ("TEST_FIXTURE",),  # tests and offline demos only
                    "OPERATIONAL": ()}                  # a real UI/console source is added only with its accreditation


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def plan_sha256(plan: dict) -> str:
    return _sha(plan)


def _body(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k != "authorization_id"}


def record(req: dict, *, operator_id: str, at: datetime, valid_for_s: float, statement: str,
           source: str = "TEST_FIXTURE") -> dict:
    plan = req.get("navigation_plan")
    if not plan:
        raise ValueError("no navigation plan: a human sets the limits first, then authorizes that exact plan")
    rec = {"schema": SCHEMA, "source": source,
           "authorized_by": {"role": "HUMAN_OPERATOR", "id": operator_id},
           "mission_id": req["task_id"], "rover_id": req["vehicle_id"], "proposal_sha256": req["proposal_sha256"],
           "plan_id": plan["plan_id"], "plan_sha256": plan_sha256(plan), "scope_sha256": req["expected_scope_sha256"],
           "operator_limits": {"max_speed_mps": plan["max_speed_mps"], "timeout_s": plan["timeout_s"]},
           "authorized_at_utc": at.astimezone(timezone.utc).isoformat(),
           "expires_at_utc": (at + timedelta(seconds=valid_for_s)).astimezone(timezone.utc).isoformat(),
           "statement": statement}
    return {**rec, "authorization_id": _sha(rec)}


def check(rec, req: dict, *, now: datetime, mode: str = "OFFLINE_TEST") -> list[str]:
    """[] only when the record authorizes exactly this request now. In mode OPERATIONAL a TEST_FIXTURE record is
    never accepted, whatever else it says (a fixture cannot leak into a productive path)."""
    if not isinstance(rec, dict) or rec.get("schema") != SCHEMA:
        return ["NOT_A_HUMAN_AUTHORIZATION_RECORD: a boolean or a bare scope is not an authorization"]
    reasons = []
    if rec.get("authorization_id") != _sha(_body(rec)):
        reasons.append("TAMPERED: the record does not match its own digest")
    if mode not in ACCEPTED_SOURCES:
        return [f"UNKNOWN_MODE: {mode!r}"]
    if mode == "OPERATIONAL" and rec.get("source") == "TEST_FIXTURE":
        reasons.append("FIXTURE_AUTHORIZATION_NOT_ACCEPTED_IN_OPERATIONAL_MODE")
    elif rec.get("source") not in ACCEPTED_SOURCES[mode]:
        reasons.append(f"SOURCE_NOT_ACCEPTED: {rec.get('source')!r} in mode {mode}")
    who = rec.get("authorized_by") or {}
    if who.get("role") != "HUMAN_OPERATOR" or not who.get("id"):
        reasons.append("NO_IDENTIFIED_HUMAN_OPERATOR")
    plan = req.get("navigation_plan")
    if not plan:
        return reasons + ["NO_NAVIGATION_PLAN"]
    for field, expected in (("mission_id", req["task_id"]), ("rover_id", req["vehicle_id"]),
                            ("proposal_sha256", req["proposal_sha256"]), ("plan_id", plan["plan_id"]),
                            ("plan_sha256", plan_sha256(plan))):
        if rec.get(field) != expected:
            reasons.append(f"{field.upper()}_MISMATCH")
    scope = rb.authorization_scope(plan, proposal_sha256=req["proposal_sha256"], vehicle_id=req["vehicle_id"])
    if rec.get("scope_sha256") != scope or req.get("expected_scope_sha256") != scope:
        reasons.append("SCOPE_MISMATCH: the scope is recomputed from the plan, vehicle and proposal")
    if rec.get("operator_limits") != {"max_speed_mps": plan["max_speed_mps"], "timeout_s": plan["timeout_s"]}:
        reasons.append("LIMITS_MISMATCH")
    try:
        start = datetime.fromisoformat(rec["authorized_at_utc"])
        end = datetime.fromisoformat(rec["expires_at_utc"])
        if not start <= now <= end:
            reasons.append("OUTSIDE_VALIDITY_WINDOW")
    except (KeyError, TypeError, ValueError):
        reasons.append("VALIDITY_WINDOW_INVALID")
    return reasons
