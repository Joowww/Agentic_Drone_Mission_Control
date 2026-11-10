"""Our rover-execution-request/1 -> the rover's agent-to-rover mission proposal tfg.rover.mission-execution/1
(schemas/rover-mission-execution-v1.schema.json and tools/rover_mission_payload.py at rover contract commit f2fd78ae1, the
latest change of both, contained in b6d07388a). The rover's code is NOT imported or modified here; the contract tests read
it from git at that commit.

Conservative by construction: a field we do not have is left empty, never invented, so the rover's validator REJECTS the
payload rather than accepting a guess:
- no accredited rover localization -> LOCALIZATION_* reasons (the JetRacer case today);
- no human limits (speed, timeout) -> empty constraints;
- no human authorization, or one whose scope is not this request's scope -> human_authorized false.
Building or validating a payload never authorizes or moves anything (the rover side: never READY_TO_EXECUTE, commands []).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

SCHEMA = "tfg.rover.mission-execution/1"
ROVER_CONTRACT_COMMIT = "f2fd78ae1"  # last change of rover_mission_payload.py and the schema (in b6d07388a)
STOP_CONDITIONS = ("HUMAN_STOP", "AUTHORIZATION_EXPIRED", "ODOMETRY_STALE", "LOCALIZATION_LOST", "FAILSAFE_ACTIVE",
                   "TIMEOUT", "MISSION_CANCELLED", "OBSERVATION_INVALIDATED")


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def mission_payload(req: dict, site, *, platform: str, observation_sha256: str | None, now: datetime,
                    validity_s: float = 60.0, localization: dict | None = None,
                    executor: tuple[str, str] = ("multiagent.DryRunRoverExecutor", "1")) -> dict:
    """The rover payload for a request whose target has been validated (goal coordinates known). A conditional task
    still waiting for its observation has no goal coordinates: it is not translated (raises), the coordinator keeps
    it. ``localization`` must come from an accredited source: {frame, x_m, y_m, source, source_sha256, validated}."""
    point = site.point((req.get("target") or {}).get("point_id") or "")
    if point is None or point.x_m is None or point.y_m is None:
        raise ValueError("the request has no validated target with coordinates (a waiting task is not translated)")
    from multiagent import human_authorization
    plan = req.get("navigation_plan")
    scope = req.get("expected_scope_sha256")
    # human_authorized is set only from a checked tfg.multiagent.human-authorization/1 record bound to this plan
    authorized = scope is not None and human_authorization.check(req.get("authorization"), req, now=now) == []
    loc = dict(localization) if localization else {}
    return {
        "schema": SCHEMA,
        "mission": {"id": req["task_id"], "sha256": req["proposal_sha256"]},
        "rover": {"vehicle_id": req["vehicle_id"], "platform": platform},
        "goal": {"frame": req["frame"], "x_m": float(point.x_m), "y_m": float(point.y_m), "conditional": False},
        "localization": loc,
        "dependencies": [f"{d['after']}:{d['condition']}" + (f":{d['point']}" if d.get("point") else "")
                         for d in req.get("dependencies") or []],
        "constraints": ({"max_speed_mps": plan["max_speed_mps"], "timeout_s": plan["timeout_s"], "plan_id": plan["plan_id"]}
                        if plan else {}),
        "provenance": {"source": "tfg.multiagent.observation/1", "source_sha256": observation_sha256 or ""},
        # the scope is carried only when it is THIS request's scope; the rover's validator checks only its shape
        "authorization": {"scope_sha256": scope or "", "human_authorized": authorized},
        "validity": {"not_before_utc": now.astimezone(timezone.utc).isoformat(),
                     "expires_at_utc": (now + timedelta(seconds=validity_s)).astimezone(timezone.utc).isoformat()},
        "executor": {"id": executor[0], "version": executor[1]},
        "stop_conditions": list(STOP_CONDITIONS),
    }


DISCREPANCIES = [
    {"field": "goal", "ours": "declared POI id (target.point_id) in the site frame", "rover_side": "frame + x_m/y_m",
     "handling": "translated from the site's declared point; only validated targets"},
    {"field": "goal.conditional", "ours": "a waiting task lives in the coordinator (CONDITIONAL_AWAITING_OBSERVATION) "
     "without coordinates", "rover_side": "conditional:true -> WAITING, but x_m/y_m are still required",
     "handling": "a waiting task is not translated (no invented coordinates); conditional is always false here"},
    {"field": "authorization.scope_sha256", "ours": "scope = sha256(plan, vehicle, proposal); preconditions() refuses "
     "a mismatch", "rover_side": "validator checks only the 64-hex shape and human_authorized",
     "handling": "the adapter sets human_authorized only when the scope equals this request's; a mismatch must still be "
     "re-checked by the protected executor (recorded as an open point for the rover side)"},
    {"field": "constraints", "ours": "typed NavigationPlan max_speed_mps, timeout_s (human limits only)",
     "rover_side": "free-form object, minProperties 1", "handling": "copied as named keys; absent without human limits"},
    {"field": "localization", "ours": "preconditions(): position source, frame equal to the plan's, freshness <= 1 s",
     "rover_side": "frame equal to goal frame, validated:true, provenance sha; freshness only via observed_monotonic_s (optional)",
     "handling": "never filled without an accredited source; freshness stays in preconditions()"},
    {"field": "validity", "ours": "observation max age at the coordinator; authorization tied to a scope",
     "rover_side": "not_before/expires_at window", "handling": "window from now, validity_s (default 60 s)"},
    {"field": "feedback / stop / failsafe", "ours": "feedback_event(), stop_request() -> RoverVehicleExecutor.stop()",
     "rover_side": "stop_conditions strings in the payload; ExecutionFeedback in rover_vehicle_contract",
     "handling": "stop conditions listed; feedback mapping unchanged (bridge)"},
    {"field": "localization.frame (inside the rover side)", "ours": "-", "rover_side": "the JSON schema cannot express "
     "localization.frame == goal.frame; only rover_mission_payload.validate() rejects it",
     "handling": "always run the rover's validator, not only the schema (open point for the rover side)"},
    {"field": "operator limits (v1)", "ours": "handoff_checks(): uncertainty (target + localization) and "
     "localization age against the operator's limits, dependencies satisfied (coordinator READY), payload validity "
     "within the authorization's and the target's", "rover_side": "v1 checks none of these (READY_TO_SUBMIT in the "
     "fixtures); its uncommitted v2 draft adds operator_limits", "handling": "both must pass before a submission"},
    {"field": "frame transform (v1)", "ours": "an ACCREDITED transform {from, to, sha256} may relate odometry and "
     "the site frame", "rover_side": "v1 requires localization.frame == goal.frame", "handling": "the transform must be "
     "applied before the payload is built; none is accredited today (fixture frame_with_accredited_transform)"},
    {"field": "dependencies", "ours": "objects {after, condition, point}", "rover_side": "strings",
     "handling": "after:condition[:point]"},
]


# ------------------------------------------------------------------ our hand-off checks (stricter than the rover v1) --
def handoff_checks(payload: dict, req: dict, *, now: datetime, ground_state: str | None, limits: dict,
                   target_sigma_m: float | None, localization_sigma_m: float | None, localization_age_s: float | None,
                   transform: dict | None = None, observation_valid_until: datetime | None = None) -> list[str]:
    """Every reason not to hand ``payload`` to the rover's protected executor; [] = it may be SUBMITTED (still not an
    execution: the executor's own preconditions run at that moment). ``limits`` are the operator's
    (localization_max_uncertainty_m, localization_max_age_s); ``transform`` an accredited frame transform
    {from_frame, to_frame, accredited, sha256}. Nothing is inferred from a missing value."""
    from multiagent import human_authorization as ha
    reasons = []
    goal, loc = payload.get("goal") or {}, payload.get("localization") or {}
    if goal.get("conditional") or ground_state != "READY_FOR_AUTHORIZATION":
        reasons.append(f"NOT_READY: conditional target or dependencies not satisfied (ground state {ground_state})")
    if (payload.get("mission") or {}) != {"id": req["task_id"], "sha256": req["proposal_sha256"]}:
        reasons.append("MISSION_IDENTITY_MISMATCH")
    if (payload.get("rover") or {}).get("vehicle_id") != req["vehicle_id"]:
        reasons.append("ROVER_IDENTITY_MISMATCH")
    plan = req.get("navigation_plan")
    if not plan or (payload.get("constraints") or {}).get("plan_id") != plan["plan_id"]:
        reasons.append("PLAN_MISMATCH: the payload does not carry the request's plan")
    auth_problems = ha.check(req.get("authorization"), req, now=now)
    if auth_problems:
        reasons.append("AUTHORIZATION: " + "; ".join(auth_problems[:3]))
    elif (payload.get("authorization") or {}).get("scope_sha256") != req["expected_scope_sha256"]:
        reasons.append("SCOPE_MISMATCH")
    if not loc or loc.get("validated") is not True:
        reasons.append("LOCALIZATION_NOT_ACCREDITED")
    elif loc.get("frame") != goal.get("frame"):
        t = transform or {}
        if not (t.get("accredited") is True and t.get("from_frame") == loc.get("frame")
                and t.get("to_frame") == goal.get("frame") and t.get("sha256")):
            reasons.append(f"FRAME_MISMATCH_NO_ACCREDITED_TRANSFORM: {loc.get('frame')} -> {goal.get('frame')}")
    if localization_age_s is None or limits.get("localization_max_age_s") is None:
        reasons.append("LOCALIZATION_AGE_UNKNOWN")
    elif localization_age_s > limits["localization_max_age_s"]:
        reasons.append(f"LOCALIZATION_STALE: {localization_age_s} s > {limits['localization_max_age_s']} s")
    if target_sigma_m is None or localization_sigma_m is None or limits.get("localization_max_uncertainty_m") is None:
        reasons.append("UNCERTAINTY_UNKNOWN")
    else:
        total = (target_sigma_m ** 2 + localization_sigma_m ** 2) ** 0.5
        if total > limits["localization_max_uncertainty_m"]:
            reasons.append(f"UNCERTAINTY_TOO_HIGH: {total:.3f} m > {limits['localization_max_uncertainty_m']} m")
    try:
        start = datetime.fromisoformat(payload["validity"]["not_before_utc"])
        end = datetime.fromisoformat(payload["validity"]["expires_at_utc"])
        if not start <= now <= end:
            reasons.append("OUTSIDE_PAYLOAD_VALIDITY")
        rec = req.get("authorization") or {}
        if rec.get("expires_at_utc") and end > datetime.fromisoformat(rec["expires_at_utc"]):
            reasons.append("VALIDITY_EXCEEDS_AUTHORIZATION")
        if observation_valid_until is not None and end > observation_valid_until:
            reasons.append("VALIDITY_EXCEEDS_TARGET_VALIDITY")
    except (KeyError, TypeError, ValueError):
        reasons.append("VALIDITY_INVALID")
    return reasons


FIXTURE_NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)
FIXTURE_LIMITS = {"localization_max_uncertainty_m": 0.5, "localization_max_age_s": 1.0}


def contract_fixtures(site) -> dict:
    """Offline contract fixtures (TEST_FIXTURE, fixed time): each case is a the rover v1 payload plus the inputs of our
    hand-off checks and the decisions both sides must give. Regenerated by the tests to detect drift."""
    from multiagent import human_authorization as ha, rover_executor_bridge as rb
    now = FIXTURE_NOW
    task = {"task_id": "GROUND_rover_01", "vehicle_id": "rover_01", "target_point": "POI_3", "start_point": "ROVER_START"}
    proposal = {"proposal_sha256": "b" * 64}
    deps = [{"task_id": "GROUND_rover_01", "after": "AIR_drone_02", "condition": "POI_REACHED", "point": "POI_3"}]
    limits = {"max_speed_mps": 0.3, "timeout_s": 30.0}
    loc = {"frame": site.local_frame.frame_id, "x_m": 1.0, "y_m": -1.5, "source": "TEST_FIXTURE_ACCREDITED_SOURCE",
           "source_sha256": "c" * 64, "validated": True}

    def req_with(auth_limits=limits, sign=True, *, at=now - timedelta(seconds=1), valid_for_s=300.0):
        req = rb.execution_request(task, site, proposal=proposal, dependencies=deps, human_limits=limits)
        if not sign:
            return req
        signed = rb.execution_request(task, site, proposal=proposal, dependencies=deps, human_limits=auth_limits)
        rec = ha.record(signed, operator_id="op-fixture", at=at, valid_for_s=valid_for_s, statement="fixture")
        return rb.execution_request(task, site, proposal=proposal, dependencies=deps, human_limits=limits,
                                    authorization=rec)
    base_in = {"ground_state": "READY_FOR_AUTHORIZATION", "target_sigma_m": 0.12, "localization_sigma_m": 0.1,
               "localization_age_s": 0.2, "transform": None, "observation_valid_until": None}
    cases = {}

    def add(name, req, rover_side, ours, *, localization=loc, conditional=False, validity_s=60.0, **inputs):
        p = mission_payload(req, site, platform="ArduRover SITL", observation_sha256="d" * 64, now=now,
                            validity_s=validity_s, localization=localization)
        p["goal"]["conditional"] = conditional
        cases[name] = {"payload": p, "request": req, "inputs": {**base_in, **inputs}, "expected_rover": rover_side,
                       "expected_ours": ours}
    add("complete", req_with(), "READY_TO_SUBMIT", [])
    add("no_localization", req_with(), "REJECTED", ["LOCALIZATION_NOT_ACCREDITED"], localization=None)
    add("boolean_is_not_authorization", {**req_with(sign=False), "authorization": {"human_authorized": True}},
        "REJECTED", ["AUTHORIZATION"])
    add("authorized_another_plan", req_with(auth_limits={"max_speed_mps": 1.0, "timeout_s": 30.0}), "REJECTED",
        ["AUTHORIZATION"])
    add("authorization_expired", req_with(at=now - timedelta(seconds=400)), "REJECTED",
        ["AUTHORIZATION", "VALIDITY_EXCEEDS_AUTHORIZATION"])
    add("frame_mismatch", req_with(), "REJECTED", ["FRAME_MISMATCH_NO_ACCREDITED_TRANSFORM"],
        localization={**loc, "frame": "odom"})
    add("frame_with_accredited_transform", req_with(), "REJECTED", [], localization={**loc, "frame": "odom"},
        transform={"from_frame": "odom", "to_frame": site.local_frame.frame_id, "accredited": True, "sha256": "f" * 64})
    add("uncertainty_too_high", req_with(), "READY_TO_SUBMIT", ["UNCERTAINTY_TOO_HIGH"], target_sigma_m=0.6)
    add("uncertainty_unknown", req_with(), "READY_TO_SUBMIT", ["UNCERTAINTY_UNKNOWN"], localization_sigma_m=None)
    add("localization_stale", req_with(), "READY_TO_SUBMIT", ["LOCALIZATION_STALE"], localization_age_s=3.0)
    add("validity_beyond_authorization", req_with(valid_for_s=30.0), "READY_TO_SUBMIT",
        ["VALIDITY_EXCEEDS_AUTHORIZATION"], validity_s=120.0)
    add("validity_beyond_target", req_with(), "READY_TO_SUBMIT", ["VALIDITY_EXCEEDS_TARGET_VALIDITY"],
        observation_valid_until=now + timedelta(seconds=10))
    add("dependencies_not_satisfied", req_with(), "READY_TO_SUBMIT", ["NOT_READY"], ground_state="TARGET_VALIDATED")
    add("conditional_target_never_moves", req_with(), "WAITING", ["NOT_READY"], conditional=True,
        ground_state="CONDITIONAL_AWAITING_OBSERVATION")
    return {"schema": "tfg.multiagent.rover-contract-fixtures/1", "rover_contract": f"{SCHEMA} @ {ROVER_CONTRACT_COMMIT}",
            "data_kind": "TEST_FIXTURE", "now_utc": now.isoformat(), "limits": FIXTURE_LIMITS, "cases": cases}
