"""Offline, versioned adapter to the rover's plan-bound contract tfg.rover.mission-execution/2 and to its adapter of our
requests (tools/rover_agent_adapter.py), both at rover contract commit 1514053da. The rover's code is NOT imported from a working tree
or modified: the contract tests read it with git show at that commit.

Two things are bridged, nothing is invented:
1. AUTHORIZATION SHAPE. the rover's adapter expects request.authorization = {scope_sha256, human_authorized: true}. Our
   request carries a tfg.multiagent.human-authorization/1 RECORD. bridge_view() derives the rover's shape ONLY from a
   record that human_authorization.check() accepts now; otherwise authorization is None. The record stays the
   authority; a model decision can never produce it.
2. ADAPTER INPUTS. adapter_inputs() builds the keyword arguments the rover's adapt_request() needs from our request and
   from ACCREDITED inputs given by the caller (localization with its uncertainty and timestamp, an optional rigid
   frame transform, the operator's limits). A missing input stays missing (None), so the rover's validator rejects.
The authenticated operator receipt (operator_verification) is produced by an operator-verification service, never
here. READY_TO_SUBMIT is not an authorization and not an execution: the rover side returns commands [] and
movement_authorized false in every case.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from multiagent import human_authorization as ha

ROVER_V2_CONTRACT_COMMIT = "1514053da"
ROVER_V2_CONTRACT_FILES = ("tools/rover_mission_payload.py", "tools/rover_agent_adapter.py",
                  "schemas/rover-mission-execution-v2.schema.json")
STOP_CONDITIONS = ("HUMAN_STOP", "AUTHORIZATION_EXPIRED", "ODOMETRY_STALE", "LOCALIZATION_LOST", "FAILSAFE_ACTIVE",
                   "TIMEOUT", "MISSION_CANCELLED", "OBSERVATION_INVALIDATED")


def bridge_view(req: dict, *, now: datetime) -> dict:
    """The request as the rover's adapter reads it. authorization is derived from a CHECKED record, or None."""
    view = {k: v for k, v in req.items() if k != "authorization"}
    rec = req.get("authorization")
    ok = rec is not None and ha.check(rec, req, now=now) == []
    view["authorization"] = ({"scope_sha256": req["expected_scope_sha256"], "human_authorized": True,
                              "authorization_record_id": rec["authorization_id"]} if ok else None)
    return view


def adapter_inputs(req: dict, *, platform: str, observation_sha256: str | None, localization: dict | None,
                   operator_limits: dict, now: datetime, validity_s: float = 60.0,
                   executor: tuple[str, str] = ("protected-ardurover-executor", "unbound")) -> dict:
    """Keyword arguments for the rover's adapt_request (without operator_verification). ``localization`` must come from
    an accredited source in the rover's v2 shape {frame, x_m, y_m, uncertainty_m, source, source_sha256, validated,
    observed_at_utc, transform}; None stays None. ``operator_limits``: max_distance_m, localization_max_uncertainty_m,
    localization_max_age_s (speed and timeout come from the human-set navigation plan)."""
    return {"mission": {"id": req["task_id"], "sha256": req["proposal_sha256"]},
            "rover": {"vehicle_id": req["vehicle_id"], "platform": platform},
            "localization": dict(localization) if localization else None,
            "dependencies": [f"{d['after']}:{d['condition']}" + (f":{d['point']}" if d.get("point") else "")
                             for d in req.get("dependencies") or []],
            "constraints": {"plan_id": (req.get("navigation_plan") or {}).get("plan_id"),
                            "max_distance_m": operator_limits.get("max_distance_m")},
            "operator_limits": dict(operator_limits),
            "provenance": {"source_sha256": observation_sha256 or ""},
            "validity": {"not_before_utc": now.astimezone(timezone.utc).isoformat(),
                         "expires_at_utc": (now + timedelta(seconds=validity_s)).astimezone(timezone.utc).isoformat()},
            "executor": {"id": executor[0], "version": executor[1]},
            "stop_conditions": list(STOP_CONDITIONS)}


DISCREPANCIES_V2 = [
    {"item": "authorization shape", "ours": "tfg.multiagent.human-authorization/1 record (operator, plan sha, scope, "
     "limits, validity, own digest)", "rover_side": "adapter expects {scope_sha256, human_authorized: true}; payload "
     "expects an authenticated operator receipt", "handling": "bridge_view() derives the rover's shape only from a checked "
     "record; the receipt comes from an operator-verification service (none exists offline)"},
    {"item": "dependencies", "ours": "objects {after, condition, point} in the request",
     "rover_side": "the payload carries strings", "handling": "after:condition[:point] in the payload"},
    {"item": "authorization in the v2 payload (inside the rover's contract)", "ours": "-",
     "rover_side": "rover_agent_adapter requires operator_verification.bridge_scope_sha256 and copies the receipt into "
     "payload.authorization; the v2 JSON schema's authorization has additionalProperties false without that field",
     "handling": "the Python validator returns READY_TO_SUBMIT but the schema rejects that one field; open point for "
     "the rover side (drop the field from the copy or add it to the schema)"},
    {"item": "observation validity", "ours": "a READY target expires (ready_hold_s); handoff_checks bound the payload "
     "validity by the target's", "rover_side": "v2 does not know the observation's validity", "handling": "both checks"},
    {"item": "aerial dependencies satisfied", "ours": "coordinator READY_FOR_AUTHORIZATION",
     "rover_side": "v2 checks only their shape", "handling": "our handoff_checks before submitting"},
]
