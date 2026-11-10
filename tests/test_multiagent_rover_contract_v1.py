"""Contract tests: our validated ground task -> the rover's tfg.rover.mission-execution/1, checked by THE ROVER'S OWN validator
and JSON schema read from git at the pinned commit (never from the rover's working tree, never modified). Offline."""
from datetime import timedelta
import json
import subprocess
import types

import pytest

from multiagent import integrated_mission as im, perception, precision_demo as pd, rover_executor_bridge as rb
from multiagent import rover_mission_payload_bridge as mp
from multiagent.benchmark import run as bench


def _git_show(path):
    try:
        return subprocess.run(["git", "show", f"{mp.ROVER_CONTRACT_COMMIT}:{path}"], cwd=bench.ROOT, capture_output=True,
                              text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip(f"rover contract commit {mp.ROVER_CONTRACT_COMMIT} not available")


@pytest.fixture(scope="module")
def rover_side():
    module = types.ModuleType("rover_v1_mission_payload")
    exec(compile(_git_show("tools/rover_mission_payload.py"), "rover_side:rover_mission_payload.py", "exec"), module.__dict__)
    schema = json.loads(_git_show("schemas/rover-mission-execution-v1.schema.json"))
    import jsonschema
    return module, jsonschema.Draft202012Validator(schema)


SITE, FLEET = im._site_fleet(im.load_context(im.CONTEXT))
NOW = perception.utc_now()
TASK = {"task_id": "GROUND_rover_01", "vehicle_id": "rover_01", "target_point": "POI_3", "start_point": "ROVER_START"}
PROPOSAL = {"proposal_sha256": "b" * 64}
DEPS = [{"task_id": "GROUND_rover_01", "after": "AIR_drone_02", "condition": "POI_REACHED", "point": "POI_3"}]
LIMITS = {"max_speed_mps": 0.3, "timeout_s": 30.0}
LOC = {"frame": "synthetic_orchard_local", "x_m": 1.0, "y_m": -1.5, "source": "TEST_FIXTURE_ACCREDITED_SOURCE",
       "source_sha256": "c" * 64, "validated": True}
OBS = "d" * 64


def request(*, limits=LIMITS, authorize=True, authorize_limits=None):
    """authorize_limits: the human authorized ANOTHER plan (other limits) than the one in the request."""
    from multiagent import human_authorization as ha
    req = rb.execution_request(TASK, SITE, proposal=PROPOSAL, dependencies=DEPS, human_limits=limits)
    if authorize and req["expected_scope_sha256"]:
        signed = rb.execution_request(TASK, SITE, proposal=PROPOSAL, dependencies=DEPS,
                                      human_limits=authorize_limits or limits)
        rec = ha.record(signed, operator_id="op-fixture", at=NOW - timedelta(seconds=1), valid_for_s=300,
                        statement="fixture")
        req = rb.execution_request(TASK, SITE, proposal=PROPOSAL, dependencies=DEPS, human_limits=limits,
                                   authorization=rec)
    return req


def payload(req=None, **kw):
    return mp.mission_payload(req or request(), SITE, platform="ArduRover SITL", now=NOW,
                              **{"localization": LOC, "observation_sha256": OBS, **kw})


def check(rover_side, p, now=NOW):
    module, schema = rover_side
    return module.validate(p, now=now + timedelta(seconds=1)), sorted(e.message for e in schema.iter_errors(p))


def test_a_complete_fixture_is_ready_to_submit_and_still_authorizes_nothing(rover_side):
    out, schema_errors = check(rover_side, payload())
    assert schema_errors == [] and out["decision"] == "READY_TO_SUBMIT" and out["reasons"] == []
    assert out["commands"] == [] and out["movement_authorized"] is False and out["execution_requires_protected_executor"]


def test_identity_frame_dependencies_provenance_and_stop_are_carried(rover_side):
    p = payload()
    assert p["mission"] == {"id": "GROUND_rover_01", "sha256": "b" * 64} and p["rover"]["vehicle_id"] == "rover_01"
    poi = SITE.point("POI_3")
    assert p["goal"] == {"frame": SITE.local_frame.frame_id, "x_m": poi.x_m, "y_m": poi.y_m, "conditional": False}
    assert p["dependencies"] == ["AIR_drone_02:POI_REACHED:POI_3"]
    assert p["provenance"]["source_sha256"] == OBS and "HUMAN_STOP" in p["stop_conditions"]
    assert p["constraints"]["max_speed_mps"] == 0.3 and p["constraints"]["timeout_s"] == 30.0


def test_the_demo_request_today_is_rejected_by_rover_for_the_right_reasons(rover_side):
    """The red_target request as the demo builds it: no human limits, no authorization, no localization."""
    req = pd.run_scenario("red_target", quiet=True)["execution_request"]
    p = mp.mission_payload(req, SITE, platform="JetRacer", observation_sha256=OBS, now=NOW)
    out, schema_errors = check(rover_side, p)
    assert out["decision"] == "REJECTED" and schema_errors
    assert {"LOCALIZATION_MISSING_OR_UNVALIDATED", "LOCALIZATION_PROVENANCE_MISSING", "CONSTRAINTS_MISSING",
            "HUMAN_AUTHORIZATION_MISSING_OR_INVALID"} <= set(out["reasons"])


@pytest.mark.parametrize("change, reason", [
    (dict(localization=None), "LOCALIZATION_MISSING_OR_UNVALIDATED"),
    (dict(localization={**LOC, "frame": "odom"}), "LOCALIZATION_MISSING_OR_UNVALIDATED"),
    (dict(localization={**LOC, "validated": False}), "LOCALIZATION_MISSING_OR_UNVALIDATED"),
    (dict(localization={k: v for k, v in LOC.items() if k != "source_sha256"}), "LOCALIZATION_PROVENANCE_MISSING"),
    (dict(observation_sha256=None), "MISSION_PROVENANCE_MISSING"),
])
def test_missing_or_unaccredited_inputs_are_rejected(rover_side, change, reason):
    out, _ = check(rover_side, payload(**change))
    assert out["decision"] == "REJECTED" and reason in out["reasons"]


def test_rover_schema_alone_misses_a_frame_mismatch(rover_side):
    """DISCREPANCY inside the rover's contract (recorded for the rover side, not changed): the JSON schema cannot express
    localization.frame == goal.frame; only the Python validator rejects it. A consumer must run the validator."""
    out, schema_errors = check(rover_side, payload(localization={**LOC, "frame": "odom"}))
    assert schema_errors == [] and out["decision"] == "REJECTED"


def test_no_implicit_authorization(rover_side):
    out, _ = check(rover_side, payload(request(authorize=False)))
    assert "HUMAN_AUTHORIZATION_MISSING_OR_INVALID" in out["reasons"]
    out, _ = check(rover_side, payload(request(limits=None)))  # no human limits: no plan, no scope, no constraints
    assert {"HUMAN_AUTHORIZATION_MISSING_OR_INVALID", "CONSTRAINTS_MISSING"} <= set(out["reasons"])


def test_an_authorization_for_another_scope_is_not_passed_on(rover_side):
    """DISCREPANCY: the rover's validator checks only the shape of scope_sha256. The adapter refuses to mark a mismatched
    authorization as human_authorized, and our preconditions() refuses it too."""
    req = request(authorize_limits={"max_speed_mps": 1.0, "timeout_s": 30.0})  # signed for a faster plan
    p = payload(req)
    assert p["authorization"]["human_authorized"] is False
    assert "HUMAN_AUTHORIZATION_MISSING_OR_INVALID" in check(rover_side, p)[0]["reasons"]
    forged = {**p, "authorization": {"scope_sha256": "e" * 64, "human_authorized": True}}
    assert check(rover_side, forged)[0]["decision"] == "READY_TO_SUBMIT"  # the rover side alone would accept the shape
    reasons = rb.preconditions(plan=req["navigation_plan"], authorization=req["authorization"],
                               expected_scope=req["expected_scope_sha256"], capabilities={}, state={}, health={},
                               state_at=None, now=NOW, request=req)
    assert any(r.startswith("AUTHORIZATION_SCOPE_MISMATCH") for r in reasons)


def test_validity_window(rover_side):
    module, _ = rover_side
    p = payload(validity_s=5)
    assert "PAYLOAD_EXPIRED" in module.validate(p, now=NOW + timedelta(seconds=6))["reasons"]
    assert "PAYLOAD_NOT_YET_VALID" in module.validate(p, now=NOW - timedelta(seconds=1))["reasons"]


def test_a_waiting_task_is_not_translated():
    """No goal coordinates exist before the observation is validated; nothing is invented."""
    req = request()
    with pytest.raises(ValueError, match="no validated target"):
        mp.mission_payload({**req, "target": {"point_id": None}}, SITE, platform="x", observation_sha256=OBS, now=NOW)


def test_rover_never_answers_ready_to_execute(rover_side):
    module, _ = rover_side
    for p in (payload(), payload(localization=None), {"schema": "x"}, None):
        out = module.validate(p, now=NOW)
        assert out["decision"] in ("REJECTED", "WAITING", "READY_TO_SUBMIT") and out["commands"] == []
        assert out["movement_authorized"] is False
    conditional = payload()
    conditional["goal"]["conditional"] = True
    assert module.validate(conditional, now=NOW + timedelta(seconds=1))["decision"] == "WAITING"


def test_the_discrepancies_are_recorded():
    assert {d["field"] for d in mp.DISCREPANCIES} >= {"goal", "goal.conditional", "authorization.scope_sha256",
                                                      "constraints", "localization", "validity", "dependencies"}


# ----------------------------------------------------------------- contract fixtures + our hand-off checks --
FIXTURES = bench.ROOT / "multiagent/fixtures/rover_contract_mission_execution_v1_cases.json"


def test_the_fixture_file_is_regenerated_identically():
    regenerated = json.loads(json.dumps(mp.contract_fixtures(SITE), sort_keys=True, default=str))
    assert regenerated == json.loads(FIXTURES.read_text())


@pytest.mark.parametrize("name", sorted(json.loads(FIXTURES.read_text())["cases"]))
def test_each_fixture_against_rover_and_our_checks(rover_side, name):
    from datetime import datetime
    module, schema = rover_side
    case = mp.contract_fixtures(SITE)["cases"][name]
    assert module.validate(case["payload"], now=mp.FIXTURE_NOW)["decision"] == case["expected_rover"]
    ours = mp.handoff_checks(case["payload"], case["request"], now=mp.FIXTURE_NOW, limits=mp.FIXTURE_LIMITS,
                             **case["inputs"])
    assert sorted({r.split(":")[0] for r in ours}) == sorted(case["expected_ours"])
    assert module.validate(case["payload"], now=mp.FIXTURE_NOW)["commands"] == []


def test_a_validated_proposal_is_not_an_authorized_execution():
    case = mp.contract_fixtures(SITE)["cases"]["complete"]
    assert mp.handoff_checks(case["payload"], case["request"], now=mp.FIXTURE_NOW, limits=mp.FIXTURE_LIMITS,
                             **case["inputs"]) == []
    # even when everything passes, the result is a submission to the protected executor, which re-checks at that
    # moment; the dry-run adapter (the only executor here) refuses execute()
    fb = rb.DryRunRoverExecutor().execute(case["request"]["navigation_plan"], case["request"]["authorization"])
    assert fb["physical_effect"] is False and str(fb["status"]).startswith("REFUSED")
