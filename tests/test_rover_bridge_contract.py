"""Contract tests against the latest committed multi-agent v2 bridge, loaded with git show.

No file of another checkout is imported or written; no actuator or executor is called.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types
from types import SimpleNamespace

import jsonschema
import pytest

from tools import rover_mission_payload as payload_contract
from tools import rover_agent_adapter as agent_adapter
from multiagent import historical_identifiers as hist

ROOT = Path(__file__).resolve().parents[1]
# The multi-agent bridge is part of this repository; its pinned commit is read from this repository's history,
# never from another checkout or working tree.
BRIDGE_REPO = ROOT
# Pinned commit, file names at that commit and their SHA-256: see multiagent.historical_identifiers.
BRIDGE_COMMIT_PINNED = hist.PINNED_BRIDGE_COMMIT
SOURCES = dict(hist.PINNED_BRIDGE_SOURCES)
NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture(autouse=True)
def refresh_now():
    global NOW
    NOW = datetime.now(timezone.utc).replace(microsecond=0)


LIMITS = {"max_speed_mps": 0.2, "timeout_s": 30.0}
OP_LIMITS = {"max_distance_m": 12.0, "localization_max_uncertainty_m": 0.3, "localization_max_age_s": 1.0}
DEPENDENCIES = [{"task_id": "GROUND_rover_01", "after": "AIR_drone_02", "condition": "POI_REACHED",
                 "point": "POI_3"}]


def pinned_bridge_modules(monkeypatch):
    # A fixed Git object prevents one test run from mixing moving revisions of the bridge.
    head = BRIDGE_COMMIT_PINNED
    if subprocess.run(["git", "cat-file", "-e", f"{head}^{{commit}}"], cwd=BRIDGE_REPO, capture_output=True).returncode:
        pytest.skip(f"pinned bridge commit {head} is not in this repository's history")
    package = types.ModuleType("multiagent")
    package.__path__ = [str(BRIDGE_REPO / "multiagent")]
    # Registered through monkeypatch: the real multiagent package is restored after each test, so the pinned
    # modules never leak into other tests of the same session.
    for name in [m for m in sys.modules if m == "multiagent" or m.startswith("multiagent.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "multiagent", package)

    def load(name):
        rel = "multiagent/" + name
        source = subprocess.run(["git", "show", f"{head}:{rel}"], cwd=BRIDGE_REPO, capture_output=True, check=True).stdout
        assert hashlib.sha256(source).hexdigest() == SOURCES[name], (
            f"{name} changed at the pinned multi-agent commit {head}; review its new committed source before updating this test")
        module = types.ModuleType("multiagent." + name.removesuffix(".py"))
        module.__file__ = str(BRIDGE_REPO / rel)
        module.__package__ = "multiagent"
        monkeypatch.setitem(sys.modules, module.__name__, module)
        setattr(package, name.removesuffix(".py"), module)
        exec(compile(source, f"multiagent@{head}:{rel}", "exec"), module.__dict__)
        return module

    rb = load("rover_executor_bridge.py")
    ha = load("human_authorization.py")
    cb = load(hist.PINNED_V2_BRIDGE_FILE)
    return SimpleNamespace(bridge=cb, executor_bridge=rb, human_auth=ha, head=head)


@pytest.fixture
def modules(monkeypatch):
    return pinned_bridge_modules(monkeypatch)


def site():
    frame = SimpleNamespace(frame_id="orchard_local")
    poi = SimpleNamespace(kind="poi", x_m=12.5, y_m=-4.25)
    return SimpleNamespace(local_frame=frame, point=lambda point_id: poi if point_id == "POI_3" else None)


def request(mods, *, limits=LIMITS, auth=None):
    task = {"task_id": "GROUND_rover_01", "vehicle_id": "rover_01", "target_point": "POI_3",
            "start_point": "ROVER_START"}
    return mods.executor_bridge.execution_request(task, site(),
        proposal={"proposal_sha256": "b" * 64}, dependencies=DEPENDENCIES,
        human_limits=limits, authorization=auth)


def signed_request(mods, *, limits=LIMITS, at=None, valid_for_s=60.0):
    at = NOW if at is None else at
    unsigned = request(mods, limits=limits)
    record = mods.human_auth.record(unsigned, operator_id="TEST_FIXTURE_operator", at=at,
                                   valid_for_s=valid_for_s, statement="TEST_FIXTURE only")
    return request(mods, limits=limits, auth=record)


_UNSET = object()


def localization(frame="orchard_local", *, transform=None, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    return {"frame": frame, "x_m": 1.0, "y_m": -1.5, "uncertainty_m": 0.1,
            "source": "TEST_FIXTURE_accredited", "source_sha256": "c" * 64, "validated": True,
            "observed_at_utc": now.isoformat(), "transform": transform}


def inputs(mods, req, *, loc=_UNSET, validity_s=60.0, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    return mods.bridge.adapter_inputs(req, platform="ArduRover SITL", observation_sha256="d" * 64,
        localization=localization(now=now) if loc is _UNSET else loc, operator_limits=OP_LIMITS, now=now,
        validity_s=validity_s)


def proposal_value(req, kwargs, verification):
    plan = req["navigation_plan"]
    value = {"schema": payload_contract.SCHEMA, "mission": kwargs["mission"], "plan_id": plan["plan_id"],
        "rover": kwargs["rover"], "goal": {"objective": "reach_agent_declared_point:" + req["target"]["point_id"],
        "frame": plan["frame"], "x_m": plan["target_x_m"], "y_m": plan["target_y_m"], "conditional": False},
        "localization": kwargs["localization"], "dependencies": list(kwargs["dependencies"]),
        "constraints": kwargs["constraints"],
        "operator_limits": {**kwargs["operator_limits"], "max_speed_mps": plan["max_speed_mps"],
                            "timeout_s": plan["timeout_s"]},
        "provenance": {**kwargs["provenance"], "source": agent_adapter.PROVENANCE_SOURCE,
            "source_sha256": hashlib.sha256(json.dumps(req, sort_keys=True, separators=(",", ":")).encode()).hexdigest()},
        "authorization": (verification if verification is not None else
                         {"bridge_scope_sha256": req["expected_scope_sha256"]}),
        "validity": kwargs["validity"], "executor": kwargs["executor"],
        "stop_conditions": list(kwargs["stop_conditions"])}
    value["plan_sha256"] = payload_contract.plan_sha256(value)
    return value


def adapt(mods, req, *, loc=_UNSET, validity_s=60.0, revocation="ACTIVE", verification_override=None, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    view = mods.bridge.bridge_view(req, now=now)
    kwargs = inputs(mods, req, loc=loc, validity_s=validity_s, now=now)
    if req.get("navigation_plan") is None or view.get("authorization") is None:
        result = agent_adapter.adapt_request(view, **kwargs)
        return result, view, kwargs
    base = proposal_value(view, kwargs, None)
    verification = {"bridge_scope_sha256": req["expected_scope_sha256"], "scope_sha256":
        payload_contract.authorization_scope_sha256(base), "human_authorized": True,
        "operator_id": "TEST_FIXTURE_operator", "operator_status": "AUTHENTICATED",
        "revocation_status": revocation, "authorization_receipt_sha256": "e" * 64}
    if verification_override:
        verification.update(verification_override)
    result = agent_adapter.adapt_request(view, **kwargs, operator_verification=verification)
    return result, view, kwargs


def never_moves(result):
    assert result.get("commands", (result.get("proposal") or {}).get("commands", [])) == []
    movement = result.get("movement_authorized", (result.get("proposal") or {}).get("movement_authorized"))
    assert movement is False or result.get("physical_effect") is False


def test_latest_v2_bridge_preserves_plan_scope_frames_and_human_limits(modules):
    mods = modules
    req = signed_request(mods)
    plan = req["navigation_plan"]
    expected = hashlib.sha256(json.dumps({"plan": plan, "vehicle_id": req["vehicle_id"],
        "proposal_sha256": req["proposal_sha256"]}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert req["task_id"] == "GROUND_rover_01" and req["proposal_sha256"] == "b" * 64
    assert req["expected_scope_sha256"] == expected
    assert plan["frame"] == req["frame"] == site().local_frame.frame_id
    assert plan["target_x_m"] == 12.5 and plan["target_y_m"] == -4.25
    assert (plan["max_speed_mps"], plan["timeout_s"]) == (0.2, 30.0)
    assert mods.human_auth.check(req["authorization"], req, now=NOW) == []
    view = mods.bridge.bridge_view(req, now=NOW)
    assert view["authorization"]["scope_sha256"] == expected
    assert view["authorization"]["human_authorized"] is True



def test_sealed_m4c_r1_request_replays_as_waiting_without_authority(modules):
    """Historical Qwen output is data replay, not a fresh model call or approval."""
    result_path = "multiagent/benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9/demo/result.json"
    raw = subprocess.run(["git", "show", f"{BRIDGE_COMMIT_PINNED}:{result_path}"], cwd=BRIDGE_REPO,
                         check=True, capture_output=True).stdout
    historical = json.loads(raw)["execution_request"]
    assert historical["target"]["point_id"] == "POI_3"
    assert historical["navigation_plan"] is None
    decision, _, _ = adapt(modules, historical)
    assert decision["decision"] == "WAITING"
    assert decision["proposal"]["conditional"] is True
    assert decision["proposal"]["coordinates"] is None
    never_moves(decision)

def test_plan_converts_to_v2_proposal_but_remains_submit_only(modules):
    req = signed_request(modules)
    result, view, _ = adapt(modules, req)
    assert result["decision"] == "READY_TO_SUBMIT", result["reasons"]
    payload = result["payload"]
    assert payload["schema"] == payload_contract.SCHEMA
    assert payload["plan_id"] == req["navigation_plan"]["plan_id"]
    assert payload["mission"] == {"id": req["task_id"], "sha256": req["proposal_sha256"]}
    assert payload["plan_sha256"] == payload_contract.plan_sha256(payload)
    assert payload["operator_limits"]["max_speed_mps"] == 0.2
    assert payload["operator_limits"]["timeout_s"] == 30.0
    assert payload["authorization"]["scope_sha256"] == payload_contract.authorization_scope_sha256(payload)
    assert payload["authorization"]["bridge_scope_sha256"] == view["expected_scope_sha256"]
    schema = json.loads((ROOT / "schemas/rover-mission-execution-v2.schema.json").read_text())
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(payload))
    assert errors == [], [error.message for error in errors]
    never_moves(result)


def test_absent_limits_localization_or_authorization_and_expiry_are_no_go(modules):
    no_limits = request(modules, limits=None)
    assert no_limits["navigation_plan"] is None
    waiting, _, _ = adapt(modules, no_limits)
    assert waiting["decision"] == "WAITING"
    never_moves(waiting)
    req = signed_request(modules)
    missing_loc, _, _ = adapt(modules, req, loc=None)
    assert missing_loc["decision"] == "REJECTED"
    assert "LOCALIZATION_MISSING_OR_UNVALIDATED" in missing_loc["reasons"]
    never_moves(missing_loc)
    unsigned = request(modules)
    waiting, _, _ = adapt(modules, unsigned)
    assert waiting["decision"] == "WAITING"
    assert "AUTHENTICATED_OPERATOR_RECEIPT_UNAVAILABLE" in waiting["reasons"]
    never_moves(waiting)
    expired, _, _ = adapt(modules, req, validity_s=1.0)
    expires = datetime.fromisoformat(expired["payload"]["validity"]["expires_at_utc"].replace("Z", "+00:00"))
    assert "PAYLOAD_EXPIRED" in payload_contract.validate(expired["payload"], now=expires + timedelta(seconds=1))["reasons"]
    never_moves(expired)


def test_wrong_plan_revocation_and_frames_fail_closed(modules):
    base = signed_request(modules)
    wrong = signed_request(modules, limits={"max_speed_mps": 0.3, "timeout_s": 30.0})
    # A record for another plan is discarded by the bridge view.
    req = request(modules, auth=wrong["authorization"])
    view = modules.bridge.bridge_view(req, now=NOW)
    assert view["authorization"] is None
    missing, _, _ = adapt(modules, base, revocation="REVOKED")
    assert missing["decision"] == "REJECTED" and "AUTHORIZATION_REVOKED" in missing["reasons"]
    never_moves(missing)
    mismatch_now = datetime.now(timezone.utc)
    mismatched_frame, _, _ = adapt(modules, base, loc=localization("odom", now=mismatch_now), now=mismatch_now)
    assert mismatched_frame["decision"] == "REJECTED"
    assert "FRAME_TRANSFORM_REQUIRED" in mismatched_frame["reasons"]
    never_moves(mismatched_frame)
    transform = {"source_frame": "odom", "target_frame": "orchard_local", "validated": True,
        "source": "TEST_FIXTURE_survey", "source_sha256": "f" * 64,
        "matrix": [[1.0, 0.0, 1.0], [0.0, 1.0, -1.5], [0.0, 0.0, 1.0]],
        "uncertainty_m": 0.05, "uncertainty_rad": 0.01, "not_before_utc": (NOW-timedelta(hours=1)).isoformat(),
        "expires_at_utc": (NOW+timedelta(hours=1)).isoformat()}
    transform_now = datetime.now(timezone.utc)
    transform["not_before_utc"] = (transform_now-timedelta(hours=1)).isoformat()
    transform["expires_at_utc"] = (transform_now+timedelta(hours=1)).isoformat()
    accepted_frame, _, _ = adapt(modules, base,
        loc=localization("odom", transform=transform, now=transform_now), now=transform_now)
    assert accepted_frame["decision"] == "READY_TO_SUBMIT", accepted_frame["reasons"]
    never_moves(accepted_frame)


def test_conditional_target_error_feedback_and_dry_run_have_no_physical_effect(modules):
    with pytest.raises(ValueError, match="not a declared POI"):
        modules.executor_bridge.navigation_plan(
            {"task_id": "task", "vehicle_id": "rover_01", "target_point": "missing"}, site(),
            proposal_sha256="b" * 64, human_limits=LIMITS)
    event = modules.executor_bridge.feedback_event(
        {"status": "FAILED", "error": "stale odometry", "physical_effect": False},
        task_id="GROUND_rover_01", at=NOW)
    assert event["type"] == "GROUND_TASK_FAILED" and event["error"] == "stale odometry"
    executor = modules.executor_bridge.DryRunRoverExecutor()
    output = executor.execute({"plan_id": "p"}, {"scope_sha256": "a" * 64})
    assert output["status"] == "REFUSED_DRY_RUN_ONLY" and output["physical_effect"] is False
    never_moves(output)
    stopped = executor.stop()
    assert stopped["status"] == "NO_PHYSICAL_OUTPUT" and stopped["physical_effect"] is False
