"""Offline joint multi-agent v2 -> the rover frame owner -> existing executor request contract."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from tools import rover_payload_executor_adapter as handoff
from tools import rover_ground_executor as executor
from tools import rover_mission_payload as payload_contract
from tests import test_rover_bridge_contract as bridge_tests

EXECUTOR_PARAMS = {
    "limits": {"max_yaw_rate_rad_s": 0.5, "call_timeout_s": 2.0, "stop_timeout_s": 2.0,
               "observation_max_age_s": 0.5, "stopped_linear_mps": 0.02, "stopped_angular_rad_s": 0.02},
    "goal": {"tolerance_m": 0.3, "yaw_tolerance_rad": 0.5, "dwell_s": 1.0, "command_hz": 10.0,
             "no_progress_s": 10.0, "progress_m": 0.05, "progress_rad": 0.05, "max_samples": 64}}
IDENTITY = {"vehicle_id": "rover_01", "host_boot_id": "fixture-host-boot", "container_boot_id": "fixture-container-boot"}


_MODULE_PATCH = None


@pytest.fixture(autouse=True)
def _bridge_module_patch(monkeypatch):
    """The pinned bridge modules are registered through this test's monkeypatch and restored afterwards."""
    global _MODULE_PATCH
    _MODULE_PATCH = monkeypatch
    yield
    _MODULE_PATCH = None


def make_payload(now):
    mods = bridge_tests.pinned_bridge_modules(_MODULE_PATCH)
    bridge_tests.NOW = now
    req = bridge_tests.signed_request(mods, at=now - timedelta(seconds=1), valid_for_s=120)
    matrix = {"source_frame": "odom", "target_frame": "orchard_local", "validated": True,
        "source": "TEST_FIXTURE_SURVEY", "source_sha256": "f"*64,
        "matrix": [[0.0,-1.0,1.0],[1.0,0.0,-1.5],[0.0,0.0,1.0]],
        "uncertainty_m": 0.02, "uncertainty_rad": 0.001,
        "not_before_utc": (now-timedelta(hours=1)).isoformat(),
        "expires_at_utc": (now+timedelta(hours=1)).isoformat()}
    loc = bridge_tests.localization("odom", transform=matrix, now=now)
    result, _, _ = bridge_tests.adapt(mods, req, loc=loc, now=now)
    return result.get("payload"), result


def fixture_provider(payload, *, identity=None, localization=None, evidence_source="TEST_FIXTURE", transformed=None):
    evidence = {"status": "FRESH", "evidence_source": evidence_source,
        "identity": dict(IDENTITY if identity is None else identity),
        "localization": deepcopy(payload["localization"] if localization is None else localization)}
    if transformed is not None:
        evidence["goal_rover"] = transformed
    return lambda _payload: evidence


def prepare(payload, *, provider=None, dependency=True, stop="CONFIRMED", mode="OFFLINE_TEST",
            expected_identity=None, now=None):
    return handoff.prepare_executor_request(payload,
        transform_provider=provider or fixture_provider(payload), executor_params=EXECUTOR_PARAMS,
        dependency_check=lambda _deps: dependency, expected_identity=IDENTITY if expected_identity is None else expected_identity,
        mode=mode, stop_state=stop, now=now)


def test_v2_site_goal_is_transformed_once_by_rover_and_executor_admission_stays_blocked(monkeypatch):
    now = datetime.now(timezone.utc)
    payload, bridge_result = make_payload(now)
    assert bridge_result["decision"] == "READY_TO_SUBMIT"
    prepared = prepare(payload, now=now)
    assert prepared["status"] == "REQUEST_VALID"
    assert prepared["admission"] == "NOT_SUBMITTED"
    assert prepared["audit"]["site_frame"] == "orchard_local"
    assert prepared["audit"]["rover_frame"] == "odom"
    assert prepared["audit"]["transform_application_count"] == 1
    assert prepared["audit"]["rover_goal"]["x_m"] == -2.75
    assert prepared["audit"]["rover_goal"]["y_m"] == -11.5
    assert executor._request(prepared["request"]).max_forward_mps == payload["operator_limits"]["max_speed_mps"]
    monkeypatch.setattr(executor, "OPERATIONAL_ROVER_ENABLED", False)
    admitted = handoff.admit_executor_request(prepared, mission_path="/does/not/exist.json",
        request_key="offline-only", authorization=None)
    assert admitted["submission_status"] == "ATTEMPTED"
    assert admitted["executor_result"]["status"] == "BLOCKED"
    assert admitted["executor_result"]["reason"] == "OPERATIONAL_ROVER_POLICY_DISABLED"
    assert admitted["execution_started"] is False
    assert prepared["commands"] == [] and prepared["movement_authorized"] is False


def test_bridge_scope_digest_is_optional_versioned_and_plan_bound():
    now = datetime.now(timezone.utc); payload, result = make_payload(now)
    assert result["decision"] == "READY_TO_SUBMIT"
    changed = deepcopy(payload)
    changed["authorization"]["bridge_scope_sha256"] = "9"*64
    assert "AUTHORIZATION_PLAN_SCOPE_MISMATCH" in payload_contract.validate(changed, now=now)["reasons"]
    changed["authorization"]["bridge_scope_sha256"] = "z"*64
    assert "BRIDGE_SCOPE_HASH_INVALID" in payload_contract.validate(changed, now=now)["reasons"]


def test_changed_goal_or_transform_cannot_reuse_old_authorization():
    now = datetime.now(timezone.utc); payload, _ = make_payload(now)
    changed_goal = deepcopy(payload); changed_goal["goal"]["x_m"] += 0.01
    reasons = payload_contract.validate(changed_goal, now=now)["reasons"]
    assert "PLAN_HASH_MISMATCH" in reasons
    changed_goal["plan_sha256"] = payload_contract.plan_sha256(changed_goal)
    reasons = payload_contract.validate(changed_goal, now=now)["reasons"]
    assert "AUTHORIZATION_PLAN_SCOPE_MISMATCH" in reasons
    changed_transform = deepcopy(payload)
    changed_transform["localization"]["transform"]["matrix"][0][2] += 0.05
    reasons = payload_contract.validate(changed_transform, now=now)["reasons"]
    assert "PLAN_HASH_MISMATCH" in reasons
    changed_transform["plan_sha256"] = payload_contract.plan_sha256(changed_transform)
    reasons = payload_contract.validate(changed_transform, now=now)["reasons"]
    assert "AUTHORIZATION_PLAN_SCOPE_MISMATCH" in reasons


def test_provider_identity_pose_and_transform_must_match_bound_payload():
    now = datetime.now(timezone.utc); payload, _ = make_payload(now)
    wrong_vehicle = {**IDENTITY, "vehicle_id": "rover_02"}
    assert prepare(payload, provider=fixture_provider(payload, identity=wrong_vehicle), now=now)["reason"] == "LOCALIZATION_IDENTITY_MISMATCH"
    wrong_boot = {**IDENTITY, "container_boot_id": "other-boot"}
    assert prepare(payload, provider=fixture_provider(payload, identity=wrong_boot), now=now)["reason"] == "LOCALIZATION_IDENTITY_MISMATCH"
    changed_pose = deepcopy(payload["localization"]); changed_pose["x_m"] += 0.1
    assert prepare(payload, provider=fixture_provider(payload, localization=changed_pose), now=now)["reason"] == "LOCALIZATION_EVIDENCE_DIFFERS_FROM_PLAN"
    assert prepare(payload, provider=fixture_provider(payload, evidence_source="CALLER_ASSERTED"), now=now)["reason"] == "UNVERIFIED_LOCALIZATION_EVIDENCE"


def test_conditional_goal_expired_pose_bad_frames_expired_dependency_and_stop_refuse():
    now = datetime.now(timezone.utc); payload, _ = make_payload(now)
    conditional = deepcopy(payload); conditional["goal"]["conditional"] = True
    assert prepare(conditional, now=now)["reason"] == "PAYLOAD_NOT_READY_TO_SUBMIT"
    stale = deepcopy(payload); stale["localization"]["observed_at_utc"] = (now-timedelta(hours=1)).isoformat()
    assert "LOCALIZATION_STALE" in prepare(stale, now=now)["payload_decision"]["reasons"]
    wrong_frame = deepcopy(payload); wrong_frame["goal"]["frame"] = "map"
    assert "FRAME_TRANSFORM_ENDPOINT_MISMATCH" in prepare(wrong_frame, now=now)["payload_decision"]["reasons"]
    assert prepare(payload, dependency=False, now=now)["reason"] == "DEPENDENCY_NOT_SATISFIED"
    assert prepare(payload, dependency={"state": "EXPIRED"}, now=now)["reason"] == "DEPENDENCY_NOT_SATISFIED"
    assert prepare(payload, stop="UNCONFIRMED", now=now)["reason"] == "STOP_STATE_UNCERTAIN"


def test_pretransformed_provider_output_and_operational_mode_are_never_accepted():
    now = datetime.now(timezone.utc); payload, _ = make_payload(now)
    pretransformed = {"frame": "odom", "x_m": 1.0, "y_m": 2.0, "sigma_m": 0.1}
    assert prepare(payload, provider=fixture_provider(payload, transformed=pretransformed), now=now)["reason"] == "PRETRANSFORMED_GOAL_REJECTED"
    assert prepare(payload, mode="OPERATIONAL", now=now)["reason"] == "OPERATIONAL_RUNTIME_NOT_WIRED"
