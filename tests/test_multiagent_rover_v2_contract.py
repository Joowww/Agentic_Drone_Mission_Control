"""Contract tests against the rover's plan-bound v2 contract and its adapter of our requests, read with git show at the
pinned commit (never from a working tree; nothing of it is modified). Offline; no command, no executor."""
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys
import types

import pytest

from multiagent import rover_v2_bridge as cb, human_authorization as ha, integrated_mission as im
from multiagent import rover_executor_bridge as rb
from multiagent import historical_identifiers as hist  # adapter pinned at 1514053da
from multiagent.benchmark import run as bench

SITE, _ = im._site_fleet(im.load_context(im.CONTEXT))
FRAME = SITE.local_frame.frame_id
NOW = datetime.now(timezone.utc).replace(microsecond=0)  # the rover's adapter validates against the real clock
M4C_R1 = bench.ROOT / "multiagent/benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9"


def _show(path):
    try:
        return subprocess.run(["git", "show", f"{cb.ROVER_V2_CONTRACT_COMMIT}:{path}"], cwd=bench.ROOT, capture_output=True,
                              text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip(f"rover contract commit {cb.ROVER_V2_CONTRACT_COMMIT} not available")


@pytest.fixture(autouse=True)
def fresh_clock():
    """The adapter validates against the real clock (payloads expire after 60 s): each test takes a fresh NOW, so
    a long session (collection minutes before the test runs) cannot turn a valid fixture into an expired one."""
    global NOW
    NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture(scope="module")
def rover_side():
    """The rover's v2 validator and adapter as isolated modules (its 'from tools import ...' is served by a temporary
    package object, restored afterwards)."""
    contract = types.ModuleType("rover_v2_mission_payload")
    exec(compile(_show("tools/rover_mission_payload.py"), "rover_side@v2:rover_mission_payload.py", "exec"), contract.__dict__)
    saved = {k: sys.modules.get(k) for k in ("tools", "tools.rover_mission_payload")}
    fake = types.ModuleType("tools")
    fake.rover_mission_payload = contract
    sys.modules["tools"], sys.modules["tools.rover_mission_payload"] = fake, contract
    try:
        adapter = types.ModuleType("rover_v2_agent_adapter")
        exec(compile(_show("tools/rover_agent_adapter.py"), "rover_side@v2:rover_agent_adapter.py", "exec"), adapter.__dict__)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    import jsonschema
    schema = jsonschema.Draft202012Validator(json.loads(_show("schemas/rover-mission-execution-v2.schema.json")))
    return types.SimpleNamespace(contract=contract, adapter=adapter, schema=schema)


TASK = {"task_id": "GROUND_rover_01", "vehicle_id": "rover_01", "target_point": "POI_3", "start_point": "ROVER_START"}
DEPS = [{"task_id": "GROUND_rover_01", "after": "AIR_drone_02", "condition": "POI_REACHED", "point": "POI_3"}]
LIMITS = {"max_speed_mps": 0.3, "timeout_s": 30.0}
OP_LIMITS = {"max_distance_m": 12.0, "localization_max_uncertainty_m": 0.3, "localization_max_age_s": 1.0}
LOC = {"frame": FRAME, "x_m": 1.0, "y_m": -1.5, "uncertainty_m": 0.1, "source": "TEST_FIXTURE_ACCREDITED",
       "source_sha256": "c" * 64, "validated": True, "observed_at_utc": (NOW - timedelta(seconds=0.2)).isoformat(),
       "transform": None}


def request(limits=LIMITS, sign=True, signed_limits=None):
    req = rb.execution_request(TASK, SITE, proposal={"proposal_sha256": "b" * 64}, dependencies=DEPS, human_limits=limits)
    if sign and limits:
        signed = rb.execution_request(TASK, SITE, proposal={"proposal_sha256": "b" * 64}, dependencies=DEPS,
                                      human_limits=signed_limits or limits)
        rec = ha.record(signed, operator_id="op-fixture", at=NOW - timedelta(seconds=1), valid_for_s=300,
                        statement="fixture")
        req = rb.execution_request(TASK, SITE, proposal={"proposal_sha256": "b" * 64}, dependencies=DEPS,
                                   human_limits=limits, authorization=rec)
    return req


def adapt(rover_side, req, *, localization=LOC, receipt=None, now=None, receipt_for=None):
    now = NOW if now is None else now
    if localization is not None:  # a fixture localization is fresh at the moment of the (real-clock) validation
        localization = {**localization, "observed_at_utc": datetime.now(timezone.utc).isoformat()}
    kwargs = cb.adapter_inputs(req, platform="ArduRover SITL", observation_sha256="d" * 64, localization=localization,
                               operator_limits=OP_LIMITS, now=now)
    view = cb.bridge_view(req, now=now)
    if receipt == "fixture":  # a TEST_FIXTURE authenticated receipt, bound to the exact rover plan (never from an LLM)
        probe = rover_side.adapter.adapt_request(view, **kwargs, operator_verification={
            "bridge_scope_sha256": view["expected_scope_sha256"], "scope_sha256": "0" * 64})
        assert probe["decision"] == "REJECTED"  # first, a receipt for another plan is refused
        value = dict(receipt_for or {})
        receipt = {"bridge_scope_sha256": view["expected_scope_sha256"], "human_authorized": True,
                   "operator_id": "op-fixture", "operator_status": "AUTHENTICATED", "revocation_status": "ACTIVE",
                   "authorization_receipt_sha256": "e" * 64, **value}
        # the rover plan scope is derived exactly as the adapter does: build once without receipt binding
        payload = _rover_payload(rover_side, view, kwargs)
        receipt.setdefault("scope_sha256", rover_side.contract.authorization_scope_sha256(payload))
    return rover_side.adapter.adapt_request(view, **kwargs, operator_verification=receipt), view, kwargs


def _rover_payload(rover_side, view, kwargs):
    """The payload the rover's adapter builds (to compute its plan scope for a fixture receipt)."""
    plan = view["navigation_plan"]
    import hashlib
    value = {"schema": rover_side.contract.SCHEMA, "mission": kwargs["mission"], "plan_id": plan["plan_id"],
             "rover": kwargs["rover"], "goal": {"objective": "reach_agent_declared_point:" + view["target"]["point_id"],
                                                "frame": plan["frame"], "x_m": plan["target_x_m"],
                                                "y_m": plan["target_y_m"], "conditional": False},
             "localization": kwargs["localization"], "dependencies": list(kwargs["dependencies"]),
             "constraints": kwargs["constraints"],
             "operator_limits": {**kwargs["operator_limits"], "max_speed_mps": plan["max_speed_mps"],
                                 "timeout_s": plan["timeout_s"]},
             "provenance": {**kwargs["provenance"], "source": hist.SNAPSHOT_ADAPTER_PROVENANCE_SOURCE,
                            "source_sha256": hashlib.sha256(json.dumps(view, sort_keys=True, separators=(",", ":"))
                                                            .encode()).hexdigest()},
             "authorization": None, "validity": kwargs["validity"], "executor": kwargs["executor"],
             "stop_conditions": list(kwargs["stop_conditions"])}
    value["plan_sha256"] = rover_side.contract.plan_sha256(value)
    return value


def never_moves(result):
    assert result.get("commands", (result.get("proposal") or {}).get("commands")) == []
    assert result.get("movement_authorized", (result.get("proposal") or {}).get("movement_authorized")) is False


# ----------------------------------------------------------------------------------------- 15 contract items --
def test_01_the_real_m4c_r1_rover_plan_waits_in_rover_adapter(rover_side):
    """The sealed M4c-r1 request (Qwen's rover plan, validated): no human limits yet, so the rover side waits."""
    req = json.loads((M4C_R1 / "demo/result.json").read_text())["execution_request"]
    assert req["target"]["point_id"] == "POI_3" and req["navigation_plan"] is None
    assert "NAVIGATION_PLAN_PENDING" in rover_side.adapter.validate_bridge_request(req)
    result, _, _ = adapt(rover_side, req)
    assert result["decision"] == "WAITING" and result["proposal"]["coordinates"] is None
    never_moves(result)


def test_02_bridge_conversion_and_the_authorization_shape(rover_side):
    req = request()
    assert rover_side.adapter.validate_bridge_request(cb.bridge_view(req, now=NOW)) == []
    # COMPATIBILITY ISSUE (recorded): our record, passed raw, is not the shape the rover's adapter reads
    assert "BRIDGE_AUTHORIZATION_PLAN_MISMATCH" in rover_side.adapter.validate_bridge_request(req)
    # a record for another plan yields no authorization in the view
    assert cb.bridge_view(request(signed_limits={"max_speed_mps": 1.0, "timeout_s": 30.0}), now=NOW)["authorization"] is None


def test_03_a_complete_payload_matches_rover_v2_schema_and_is_only_ready_to_submit(rover_side):
    result, _, _ = adapt(rover_side, request(), receipt="fixture")
    assert result["decision"] == "READY_TO_SUBMIT", result["reasons"]
    never_moves(result)  # READY_TO_SUBMIT is neither an authorization of movement nor an execution
    # DISCREPANCY INSIDE THE ROVER CONTRACT (recorded for the rover side, not changed): the adapter requires
    # operator_verification.bridge_scope_sha256 and copies the receipt into payload.authorization, whose schema has
    # additionalProperties false without that field. The Python validator says READY_TO_SUBMIT; the JSON schema
    # rejects exactly that one field and nothing else.
    errors = list(rover_side.schema.iter_errors(result["payload"]))
    assert len(errors) == 1 and list(errors[0].absolute_path) == ["authorization"]
    trimmed = {**result["payload"], "authorization": {k: v for k, v in result["payload"]["authorization"].items()
                                                      if k != "bridge_scope_sha256"}}
    assert list(rover_side.schema.iter_errors(trimmed)) == []


def test_04_the_plan_hash_binds_every_field(rover_side):
    result, _, _ = adapt(rover_side, request(), receipt="fixture")
    payload = dict(result["payload"])
    assert rover_side.contract.plan_sha256(payload) == payload["plan_sha256"]
    tampered = {**payload, "operator_limits": {**payload["operator_limits"], "max_speed_mps": 2.0}}
    assert "PLAN_HASH_MISMATCH" in rover_side.contract.validate(tampered, now=NOW)["reasons"]


def test_05_goal_frame_is_the_site_frame(rover_side):
    result, _, _ = adapt(rover_side, request(), receipt="fixture")
    goal, poi = result["payload"]["goal"], SITE.point("POI_3")
    assert (goal["frame"], goal["x_m"], goal["y_m"], goal["conditional"]) == (FRAME, poi.x_m, poi.y_m, False)


RIGID = {"source_frame": "odom", "target_frame": FRAME, "validated": True, "source": "TEST_FIXTURE_SURVEY",
         "source_sha256": "f" * 64, "matrix": [[1.0, 0.0, 1.0], [0.0, 1.0, -1.5], [0.0, 0.0, 1.0]],
         "uncertainty_m": 0.05, "uncertainty_rad": 0.01,
         "not_before_utc": (NOW - timedelta(hours=1)).isoformat(), "expires_at_utc": (NOW + timedelta(hours=1)).isoformat()}


@pytest.mark.parametrize("transform, reason", [
    (None, "FRAME_TRANSFORM_REQUIRED"),
    ({**RIGID, "matrix": [[2.0, 0.0, 1.0], [0.0, 1.0, -1.5], [0.0, 0.0, 1.0]]}, "FRAME_TRANSFORM_NOT_RIGID_2D"),
    ({**RIGID, "validated": False}, "FRAME_TRANSFORM_NOT_VALIDATED"),
    ({**RIGID, "expires_at_utc": (NOW - timedelta(seconds=1)).isoformat()}, "FRAME_TRANSFORM_EXPIRED_OR_NOT_YET_VALID"),
    ({**RIGID, "target_frame": "map"}, "FRAME_TRANSFORM_ENDPOINT_MISMATCH"),
])
def test_06_localization_frame_and_transform(rover_side, transform, reason):
    loc = {**LOC, "frame": "odom", "x_m": 0.0, "y_m": 0.0, "transform": transform}
    result, _, _ = adapt(rover_side, request(), localization=loc, receipt="fixture")
    assert result["decision"] == "REJECTED" and reason in result["reasons"]
    never_moves(result)


def test_06b_an_accredited_rigid_transform_is_accepted(rover_side):
    loc = {**LOC, "frame": "odom", "x_m": 0.0, "y_m": 0.0, "transform": RIGID}
    result, _, _ = adapt(rover_side, request(), localization=loc, receipt="fixture")
    assert result["decision"] == "READY_TO_SUBMIT", result["reasons"]
    never_moves(result)


def test_07_aerial_dependencies_are_carried(rover_side):
    result, _, _ = adapt(rover_side, request(), receipt="fixture")
    assert result["payload"]["dependencies"] == ["AIR_drone_02:POI_REACHED:POI_3"]


def test_08_validity(rover_side):
    result, _, kwargs = adapt(rover_side, request(), receipt="fixture")
    assert "PAYLOAD_EXPIRED" in rover_side.contract.validate(result["payload"], now=NOW + timedelta(seconds=61))["reasons"]


@pytest.mark.parametrize("receipt, decision, reason", [
    (None, "WAITING", "AUTHENTICATED_OPERATOR_RECEIPT_UNAVAILABLE"),
    ({"revocation_status": "REVOKED"}, "REJECTED", "AUTHORIZATION_REVOKED"),
    ({"operator_status": "CLAIMED"}, "REJECTED", "OPERATOR_NOT_AUTHENTICATED"),
    ({"bridge_scope_sha256": "1" * 64}, "REJECTED", "OPERATOR_RECEIPT_NOT_BOUND_TO_BRIDGE_SCOPE"),
])
def test_09_authorization_needs_an_authenticated_receipt_bound_to_both_scopes(rover_side, receipt, decision, reason):
    if receipt is None:
        result, _, _ = adapt(rover_side, request())
    else:
        result, _, _ = adapt(rover_side, request(), receipt="fixture", receipt_for=receipt)
    assert result["decision"] == decision and reason in result["reasons"]
    never_moves(result)


def test_10_11_speed_and_timeout_come_from_the_human_plan(rover_side):
    result, _, _ = adapt(rover_side, request(), receipt="fixture")
    assert (result["payload"]["operator_limits"]["max_speed_mps"], result["payload"]["operator_limits"]["timeout_s"]) == \
        (0.3, 30.0)
    no_plan = request(limits=None, sign=False)
    assert adapt(rover_side, no_plan)[0]["decision"] == "WAITING"  # no human limits: nothing to submit


def test_12_errors_and_malformed_shapes_are_rejected(rover_side):
    for bad in (None, {"schema": "x"}, {**request(), "navigation_plan": "fast"}):
        out = rover_side.adapter.validate_bridge_request(bad) if bad is not None else ["UNKNOWN_BRIDGE_SCHEMA"]
        assert out
    assert rover_side.contract.validate({"schema": rover_side.contract.SCHEMA, "goal": "north"}, now=NOW)["decision"] == "REJECTED"


def test_13_stop_conditions_are_required_and_stop_needs_no_authorization(rover_side):
    result, _, _ = adapt(rover_side, request(), receipt="fixture")
    payload = {**result["payload"], "stop_conditions": []}
    assert "STOP_CONDITIONS_MISSING" in rover_side.contract.validate(payload, now=NOW)["reasons"]
    assert rb.stop_request(task_id="GROUND_rover_01", reason="HUMAN_STOP", at=NOW)["call"] == "RoverVehicleExecutor.stop()"


def test_14_observation_expiry_is_ours_to_enforce(rover_side):
    """The rover v2 does not know the observation's validity; our hand-off checks bound the payload by it."""
    from multiagent import rover_mission_payload_bridge as mp
    case = mp.contract_fixtures(SITE)["cases"]["validity_beyond_target"]
    ours = mp.handoff_checks(case["payload"], case["request"], now=mp.FIXTURE_NOW, limits=mp.FIXTURE_LIMITS,
                             **case["inputs"])
    assert any(r.startswith("VALIDITY_EXCEEDS_TARGET_VALIDITY") for r in ours)


def test_15_no_unauthorized_command_anywhere(rover_side):
    outcomes = [adapt(rover_side, request())[0], adapt(rover_side, request(), receipt="fixture")[0],
                adapt(rover_side, request(), localization=None, receipt="fixture")[0],
                adapt(rover_side, json.loads((M4C_R1 / "demo/result.json").read_text())["execution_request"])[0]]
    for o in outcomes:
        never_moves(o)
    assert not hasattr(rb, "send_command") and rb.DryRunRoverExecutor.physical_effect is False


def test_an_llm_decision_can_never_become_an_authorization(rover_side):
    """The rover agent's sealed reply (a planning decision) carries no authority: the request built from it has no
    authorization, the view has none, and the rover side waits for an authenticated receipt."""
    raw = [json.loads(l) for l in (M4C_R1 / "exchanges.jsonl").read_text().splitlines()][-1]
    assert raw["role"] == "rover_agent" and "authoriz" not in raw["raw_reply"].lower()
    req = json.loads((M4C_R1 / "demo/result.json").read_text())["execution_request"]
    assert req["authorization"] is None and cb.bridge_view(req, now=NOW)["authorization"] is None
