"""Multi-agent hand-off through the rover's final adapter (tools.rover_payload_executor_adapter), offline.

Real code on both sides: the multi-agent bridge, the rover v2 contract and agent adapter, the final payload -> executor
adapter and the executor admission with the operational policy as committed (disabled). Limits, authorization,
transform, localization, execution identity and stop state are TEST_FIXTURE declarations. No command is produced and
nothing moves."""
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from multiagent import integration_battery as ib, precision_demo as pd, rover_handoff as rh
from multiagent import rover_handoff_fixtures as fx
from tools import rover_agent_adapter, rover_payload_executor_adapter as final_adapter


@pytest.fixture(scope="module")
def demo():
    now = datetime.now(timezone.utc)
    result = pd.run_scenario("red_target", quiet=True, now=now, safety_policy="safety/4", keep_coordinator=True)
    result.pop("_coordinator", None)
    return result


@pytest.fixture
def rover_side():
    with rh.rover_contract() as side:
        yield side


def run(demo, rover_side, monkeypatch=None, **override):
    """The demo's request through the final contract path, with fixture inputs changed by ``override``."""
    if override:
        original = fx.synthetic_inputs
        monkeypatch.setattr(fx, "synthetic_inputs", lambda now, **kw: original(now, **{**kw, **override}))
    _, trace = ib.handoff_for(demo, rover_side, conversion_owner="ROVER_ADAPTER")
    return trace, {s["stage"]: s for s in trace["stages"]}


def test_final_adapter_receives_the_exact_v2_payload_and_converts_once(demo, rover_side, monkeypatch):
    seen = {}
    adapt, prepare = rover_agent_adapter.adapt_request, final_adapter.prepare_executor_request

    def spy_adapt(*a, **k):
        seen["adapted"] = adapt(*a, **k)
        return seen["adapted"]

    def spy_prepare(payload, **k):
        seen["received"] = payload
        seen["prepared"] = prepare(payload, **k)
        return seen["prepared"]
    monkeypatch.setattr(rover_agent_adapter, "adapt_request", spy_adapt)
    monkeypatch.setattr(final_adapter, "prepare_executor_request", spy_prepare)
    trace, stages = run(demo, rover_side)
    assert json.dumps(seen["received"], sort_keys=True, default=str) == \
        json.dumps(seen["adapted"]["payload"], sort_keys=True, default=str)
    assert stages["frames"]["conversion"]["applied_here"] is False          # this side never converts
    assert stages["executor_request"]["adapter_audit"]["transform_application_count"] == 1
    assert stages["executor_request"]["request"] == seen["prepared"]["request"]
    assert trace["classification"] == "READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED"
    assert stages["executor_admit"]["reasons"] == ["OPERATIONAL_ROVER_POLICY_DISABLED"]
    assert trace["commands"] == [] and trace["movement_executed"] is False


def test_request_limits_are_the_approved_plan_limits(demo, rover_side):
    trace, stages = run(demo, rover_side)
    plan = fx.HUMAN_LIMITS
    limits = stages["executor_request"]["request"]["limits"]
    assert (limits["max_forward_mps"], limits["max_duration_s"]) == (plan["max_speed_mps"], plan["timeout_s"])
    assert stages["executor_request"]["request"]["goal"]["timeout_s"] == plan["timeout_s"]


@pytest.mark.parametrize("limits,goal", [
    ({"max_forward_mps": 0.2, "max_duration_s": 20}, {}),          # the reproduced elevation of speed and duration
    ({"max_forward_mps": 0.0001}, {}),                              # even a lower value is not the plan's to change
    ({}, {"timeout_s": 999}),
    ({}, {"x_m": 100.0, "y_m": -50.0}),                             # moving the goal
    ({}, {"frame": "map", "transform": "SOMETHING_ELSE"}),
])
@pytest.mark.parametrize("owner", ["ROVER_ADAPTER", "MULTIAGENT_FRAMES2D"])
def test_executor_parameters_can_never_replace_plan_limits_or_goal(demo, rover_side, monkeypatch, limits, goal, owner):
    params = {"limits": {**fx.EXECUTOR_PARAMS["limits"], **limits}, "goal": {**fx.EXECUTOR_PARAMS["goal"], **goal}}
    original = fx.synthetic_inputs
    monkeypatch.setattr(fx, "synthetic_inputs", lambda now, **kw: original(now, **{**kw, "executor_params": params}))
    _, trace = ib.handoff_for(demo, rover_side, conversion_owner=owner)
    stages = {s["stage"]: s for s in trace["stages"]}
    assert stages["executor_request"]["status"] in ("REFUSED", "NOT_REACHED")
    assert any("EXECUTOR_PARAMETERS_OVERRIDE_PLAN" in r for r in stages["executor_request"]["reasons"])
    assert stages["executor_admit"]["status"] != "ADMITTED" and trace["commands"] == []


@pytest.mark.parametrize("params,code", [
    (None, "EXECUTOR_PARAMETERS_NOT_DECLARED"),
    ({"limits": {}}, "EXECUTOR_PARAMETERS_INVALID"),
    ({"limits": [], "goal": {}}, "EXECUTOR_PARAMETERS_INVALID"),
    ({"limits": {}, "goal": {}, "extra": {}}, "EXECUTOR_PARAMETERS_INVALID"),
])
def test_missing_or_malformed_executor_parameters_are_refused(demo, rover_side, monkeypatch, params, code):
    trace, stages = run(demo, rover_side, monkeypatch, executor_params=params)
    assert stages["executor_request"]["status"] == "REFUSED"
    assert stages["executor_request"]["reasons"][0].startswith(code)
    assert trace["commands"] == []


@pytest.mark.parametrize("override,code", [
    ({"execution_identity": None}, "EXPECTED_IDENTITY_INCOMPLETE"),
    ({"execution_identity": {"host_boot_id": "rover-boot-1"}}, "EXPECTED_IDENTITY_INCOMPLETE"),
    ({"execution_identity": {"host_boot_id": "", "container_boot_id": ""}}, "LOCALIZATION_BOOT_ID_MISSING"),
    ({"stop_state": None}, "STOP_STATE_UNCERTAIN"),
    ({"stop_state": "UNCONFIRMED"}, "STOP_STATE_UNCERTAIN"),
])
def test_incomplete_inputs_are_refused_by_the_final_adapter(demo, rover_side, monkeypatch, override, code):
    trace, stages = run(demo, rover_side, monkeypatch, **override)
    assert stages["executor_request"]["status"] == "REFUSED" and stages["executor_request"]["reasons"] == [code]
    assert stages["executor_admit"]["status"] == "NOT_REACHED" and trace["commands"] == []


def test_final_adapter_never_raises_limits_even_when_called_directly(demo, rover_side, monkeypatch):
    """Defence in depth: the adapter itself writes the plan limits over any executor parameter."""
    captured = {}
    prepare = final_adapter.prepare_executor_request

    def spy(payload, **k):
        captured["payload"], captured["kwargs"] = payload, k
        return prepare(payload, **k)
    monkeypatch.setattr(final_adapter, "prepare_executor_request", spy)
    run(demo, rover_side)
    kwargs = dict(captured["kwargs"])
    kwargs["executor_params"] = {"limits": {**fx.EXECUTOR_PARAMS["limits"], "max_forward_mps": 9.0,
                                            "max_duration_s": 9999}, "goal": {**fx.EXECUTOR_PARAMS["goal"],
                                                                              "timeout_s": 9999}}
    out = prepare(captured["payload"], **kwargs)
    ops = captured["payload"]["operator_limits"]
    assert out["request"]["limits"]["max_forward_mps"] == ops["max_speed_mps"]
    assert out["request"]["limits"]["max_duration_s"] == ops["timeout_s"]
    assert out["request"]["goal"]["timeout_s"] == ops["timeout_s"]


def test_operational_mode_and_unsafe_admission_are_refused(rover_side, monkeypatch):
    out = rover_side.call("prepare_executor_request", payload={}, mode="OPERATIONAL", executor_params=None,
                          localization_evidence=None, dependencies_satisfied=True, expected_identity={},
                          stop_state="CONFIRMED")
    assert out["ok"] and out["result"]["reason"] == "OPERATIONAL_RUNTIME_NOT_WIRED"
    bad = rover_side.call("admit_executor_request", prepared={"status": "REQUEST_VALID", "request": {"sitl_trial": {}}})
    assert not bad["ok"] and "sitl_trial" in bad["error"]
    monkeypatch.setattr(rover_side.executor, "OPERATIONAL_ROVER_ENABLED", True)
    monkeypatch.setattr(rover_side.executor, "admit_ground_trial", lambda *a, **k: pytest.fail("executor reached"))
    refused = rover_side.call("admit_executor_request", prepared={"status": "REQUEST_VALID", "request": {}})
    assert not refused["ok"] and "operational rover policy is enabled" in refused["error"]


def test_historical_snapshots_keep_their_sealed_behaviour(demo, tmp_path):
    from tests.history_requirements import require_commits
    require_commits(rh.ROVER_CONTRACT_COMMIT)
    with rh.rover_contract(tmp_path / "committed") as snapshot:
        _, trace = ib.handoff_for(demo, snapshot, conversion_owner="ROVER_ADAPTER")
    assert trace["classification"] == "V2_READY_AWAITING_ROVER_ADAPTER" and trace["commands"] == []
