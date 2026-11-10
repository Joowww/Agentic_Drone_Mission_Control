"""Offline v2 to bounded executor-request adapter.

Codex applies the site-to-navigation transform once, from the validated v2
localization transform. This module prepares a request only: it has no
operational provider and never authenticates an operator or starts execution.
"""
from __future__ import annotations

import math
from tools import rover_mission_payload
from tools import rover_ground_executor


def prepare_executor_request(payload, *, transform_provider, executor_params,
                             dependency_check, expected_identity,
                             mode="OFFLINE_TEST", stop_state="CONFIRMED",
                             rover_frame="odom", now=None):
    """Validate a v2 proposal and prepare its sole bounded executor request.

    The provider returns a current localization snapshot and identity evidence;
    it must match the localization/transform already bound into the canonical
    proposal. Provider-supplied transformed coordinates are deliberately not
    accepted. Operational mode remains unavailable until a protected provider
    and admission route exist.
    """
    if mode != "OFFLINE_TEST":
        return _refuse("OPERATIONAL_RUNTIME_NOT_WIRED")
    if stop_state != "CONFIRMED":
        return _refuse("STOP_STATE_UNCERTAIN")
    checked = rover_mission_payload.validate(payload, now=now)
    if checked.get("decision") != "READY_TO_SUBMIT":
        return _refuse("PAYLOAD_NOT_READY_TO_SUBMIT", payload_decision=checked)
    if payload["goal"].get("conditional") is not False:
        return _refuse("CONDITIONAL_GOAL_NOT_EXECUTABLE")
    if not callable(dependency_check):
        return _refuse("DEPENDENCY_PROVIDER_MISSING")
    try:
        dependencies = dependency_check(payload["dependencies"])
    except Exception:
        return _refuse("DEPENDENCY_STATUS_UNKNOWN")
    if dependencies is not True:
        return _refuse("DEPENDENCY_NOT_SATISFIED")
    if not callable(transform_provider):
        return _refuse("LOCALIZATION_PROVIDER_MISSING")
    try:
        evidence = transform_provider(payload)
    except Exception:
        return _refuse("LOCALIZATION_PROVIDER_UNKNOWN")
    refusal = _validate_provider_evidence(payload, evidence, expected_identity)
    if refusal:
        return _refuse(refusal)
    if isinstance(evidence.get("goal_rover"), dict) or "transformed_goal" in evidence:
        return _refuse("PRETRANSFORMED_GOAL_REJECTED")

    goal = payload["goal"]
    localization = payload["localization"]
    transform = localization.get("transform")
    if transform is None:
        if localization["frame"] != goal["frame"]:
            return _refuse("FRAME_TRANSFORM_REQUIRED")
        if goal["frame"] != rover_frame:
            return _refuse("NAVIGATION_FRAME_MISMATCH")
        x_rover, y_rover = goal["x_m"], goal["y_m"]
        transform_count = 0
        transform_digest = None
        transform_source = "IDENTITY_ALREADY_IN_NAVIGATION_FRAME"
        transform_source_sha256 = None
        sigma_m = localization["uncertainty_m"]
    else:
        if (transform.get("source_frame") != localization["frame"]
                or transform.get("target_frame") != goal["frame"]
                or transform.get("source_frame") != rover_frame):
            return _refuse("FRAME_TRANSFORM_ENDPOINT_MISMATCH")
        # Payload transform is localization-frame -> site-goal-frame. Invert it
        # here to map the site target into rover navigation coordinates once.
        matrix = transform["matrix"]
        a, b, tx = matrix[0]
        c, d, ty = matrix[1]
        x_rover = a*goal["x_m"] + c*goal["y_m"] - a*tx - c*ty
        y_rover = b*goal["x_m"] + d*goal["y_m"] - b*tx - d*ty
        transform_count = 1
        transform_digest = rover_mission_payload._digest(transform)
        transform_source = transform["source"]
        transform_source_sha256 = transform["source_sha256"]
        sigma_m = math.hypot(localization["uncertainty_m"], transform["uncertainty_m"])
    if not all(math.isfinite(v) for v in (x_rover, y_rover, sigma_m)):
        return _refuse("TRANSFORMED_GOAL_INVALID")
    limits_contract = payload["operator_limits"]
    if sigma_m > limits_contract["localization_max_uncertainty_m"]:
        return _refuse("TRANSFORM_UNCERTAINTY_EXCEEDS_OPERATOR_LIMIT")
    distance_m = math.hypot(x_rover-localization["x_m"], y_rover-localization["y_m"])
    if distance_m <= 0 or distance_m > limits_contract["max_distance_m"]:
        return _refuse("TRANSFORMED_GOAL_OUTSIDE_DISTANCE_LIMIT")
    if not isinstance(executor_params, dict) or set(executor_params) != {"limits", "goal"}:
        return _refuse("EXECUTOR_PARAMETERS_MISSING")
    if not isinstance(executor_params["limits"], dict) or not isinstance(executor_params["goal"], dict):
        return _refuse("EXECUTOR_PARAMETERS_INVALID")
    limits = dict(executor_params["limits"])
    limits.update(max_forward_mps=limits_contract["max_speed_mps"],
                  max_duration_s=limits_contract["timeout_s"])
    internal_goal = dict(executor_params["goal"])
    internal_goal.update(x_m=x_rover, y_m=y_rover,
                         yaw_rad=math.atan2(y_rover-localization["y_m"], x_rover-localization["x_m"]),
                         frame=rover_frame, unit="m",
                         transform="IDENTITY_SAME_ACCREDITED_FRAME",
                         timeout_s=limits_contract["timeout_s"])
    request = {"kind": "ROVER_NAVIGATE_V1", "limits": limits, "goal": internal_goal,
               "profile": "rover_only"}
    try:
        rover_ground_executor._request(request)
    except (TypeError, ValueError, KeyError) as exc:
        return _refuse("EXECUTOR_REQUEST_REJECTED", detail=str(exc))
    audit = {"site_goal": dict(goal), "site_frame": goal["frame"],
             "rover_goal": {"frame": rover_frame, "x_m": x_rover, "y_m": y_rover,
                            "sigma_m": sigma_m},
             "rover_frame": rover_frame, "transform_application_count": transform_count,
             "transform_sha256": transform_digest, "transform_source": transform_source,
             "transform_source_sha256": transform_source_sha256,
             "identity": dict(expected_identity), "payload_plan_sha256": checked.get("plan_sha256"),
             "authorization_scope_sha256": checked.get("authorization_scope_sha256"),
             "commands": [], "movement_authorized": False}
    return {"status": "REQUEST_VALID", "admission": "NOT_SUBMITTED",
            "request": request, "audit": audit, "commands": [], "movement_authorized": False}


def admit_executor_request(prepared, *, mission_path, request_key, authorization,
                           coordination_context=None):
    """Pass a prepared request to the existing executor admission function.

    The executor's result is returned verbatim. Admission does not start
    execution, and its legacy caller-declaration field is not authentication.
    """
    if not isinstance(prepared, dict) or prepared.get("status") != "REQUEST_VALID":
        return {"submission_status": "NOT_ATTEMPTED", "executor_result": None,
                "execution_started": False, "commands": [], "movement_authorized": False}
    result = rover_ground_executor.admit_ground_trial(
        mission_path, request_key, prepared["request"], authorization,
        coordination_context=coordination_context)
    return {"submission_status": "ATTEMPTED", "executor_result": result,
            "execution_started": False, "commands": [], "movement_authorized": False}


def _validate_provider_evidence(payload, evidence, expected_identity):
    required = {"vehicle_id", "host_boot_id", "container_boot_id"}
    if not isinstance(expected_identity, dict) or set(expected_identity) != required:
        return "EXPECTED_IDENTITY_INCOMPLETE"
    if (not isinstance(evidence, dict) or evidence.get("status") != "FRESH"
            or evidence.get("evidence_source") != "TEST_FIXTURE"):
        return "UNVERIFIED_LOCALIZATION_EVIDENCE"
    identity = evidence.get("identity")
    if not isinstance(identity, dict) or identity != expected_identity:
        return "LOCALIZATION_IDENTITY_MISMATCH"
    if expected_identity["vehicle_id"] != payload.get("rover", {}).get("vehicle_id"):
        return "LOCALIZATION_VEHICLE_MISMATCH"
    if any(not isinstance(value, str) or not value for value in expected_identity.values()):
        return "LOCALIZATION_BOOT_ID_MISSING"
    if evidence.get("localization") != payload.get("localization"):
        return "LOCALIZATION_EVIDENCE_DIFFERS_FROM_PLAN"
    return None


def _refuse(code, **details):
    return {"status": "REFUSED", "reason": code, **details,
            "request": None, "commands": [], "movement_authorized": False}
