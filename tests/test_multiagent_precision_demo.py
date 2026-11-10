"""The integrated precision-agriculture demo (offline) and the executor contract checks. Every scenario must end in its
predeclared classification, no scenario may report execution or movement, and nothing may command a vehicle."""
from datetime import timedelta
import hashlib
import json

import pytest

from multiagent import demo, integrated_mission as im, perception as pc, precision_demo as pd, rover_executor_bridge as rb
from multiagent.mission_coordinator import Coordinator


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no network, process or vehicle")
    monkeypatch.setattr("socket.socket.connect", refuse)
    monkeypatch.setattr("subprocess.run", refuse)


RESULTS = {}


def result(name):
    if name not in RESULTS:
        RESULTS[name] = pd.run_scenario(name, quiet=True)
    return RESULTS[name]


@pytest.mark.parametrize("name", list(pd.SCENARIOS))
def test_every_scenario_ends_in_its_declared_classification_and_never_moves(name):
    r = result(name)
    assert r["classification"] == pd.SCENARIOS[name]["expect"], r["console"][-4:]
    assert r["commands_sent"] == 0 and r["physical_effect"] is False
    ladder = r["status_ladder"]
    assert not ladder["execution_authorized"] and not ladder["movement_executed"] and not ladder["mission_physically_completed"]
    assert r["coordinator"]["executing"] == [] and r["coordinator"]["commands_sent"] == 0
    # no plan -> no flight -> no image: a refused mission never renders one
    assert r["provenance"]["image"] == ("NOT_RENDERED (no plan, no flight)" if r["classification"].startswith(
        ("MISSION_REFUSED", "MISSION_NEEDS")) else "SYNTHETIC_TEST") and r["provenance"]["events"] == "TEST_FIXTURE"
    assert r["provenance"]["agents"].startswith("DETERMINISTIC_AGENT")


def test_the_positive_chain_goes_through_every_component():
    r = result("red_target")
    assert r["detection"]["status"] == "DETECTED" and r["detection"]["detections"][0]["object_class"] == "red_card"
    assert r["geometry"]["chain"] == ["synthetic_orchard_local", "drone_02/base_link", "cam_down_fixture_optical"]
    assert r["geometry"]["depth_source"] == "GROUND_PLANE_ASSUMPTION"
    assert r["observation_gate"]["status"] == "ACCEPTED" and r["observation_gate"]["target"]["matched_poi"] == "POI_3"
    assert r["coordinator"]["mission"] == "AUTHORIZATION_REQUESTED"
    assert r["coordinator"]["ground"]["G1"]["state"] == "READY_FOR_AUTHORIZATION"
    req = r["execution_request"]
    assert req["schema"] == rb.REQUEST_SCHEMA and req["authorization"] is None and req["state"] == "AWAITING_HUMAN_AUTHORIZATION"
    assert {"task_id": "GROUND_rover_01", "after": "AIR_drone_02", "condition": "POI_REACHED", "point": "POI_3"} in req["dependencies"]
    assert [p["vehicle_id"] for p in r["aerial_tasks"]] == ["drone_01", "drone_02"]


def test_negative_scenarios_stop_at_the_right_place():
    assert result("missing_depth")["geometry_refusal"][0].startswith("DEPTH_MISSING")
    assert result("missing_camera_pose")["geometry_refusal"][0].startswith("POSE_UNKNOWN")
    assert result("wrong_frame")["geometry_refusal"][0].startswith("FRAME_MISMATCH")
    assert result("ambiguous_detection")["detection"]["ambiguous"][0]["reason"] == "HUE_BETWEEN_RED_AND_YELLOW"
    blue = result("disallowed_color")["detection"]
    assert blue["status"] == "NONE" and blue["detections"] == blue["ambiguous"] == []  # blue never becomes a candidate
    assert any(r.startswith("FRESH") for r in result("stale_observation")["observation_gate"]["reasons"])
    assert result("impossible_dependency")["coordinator"]["ground"]["G1"]["state"] == "BLOCKED_NO_DRONE_TASK_AT_TARGET"
    assert result("unassigned_objective")["unassigned"][0]["objective_id"] == "A3"
    assert result("mission_cancelled")["coordinator"]["ground"]["G1"]["state"] == "CANCELLED"
    assert "DUPLICATE" in " ".join(result("duplicate_observation")["console"])
    assert result("tool_error")["coordinator"]["mission"] == "ERROR"
    loc = result("missing_localization")
    assert loc["executor"][0]["execute_called"] is False and any(r.startswith("NO_POSITION_SOURCE")
                                                                  for r in loc["executor"][0]["preconditions"])
    unauth = result("unauthorized_execution")["executor"][0]
    assert unauth["preconditions"][0].startswith("NOT_AUTHORIZED") and unauth["coordinator"] == "REFUSED"


def test_the_cli_lists_runs_and_seals_evidence(tmp_path, capsys):
    assert demo.main(["--list-scenarios"]) == 0
    assert "red_target" in capsys.readouterr().out
    assert demo.main(["--scenario", "yellow_target", "--out", str(tmp_path / "y")]) == 0
    names = {p.name for p in (tmp_path / "y").iterdir()}
    assert {"scene.png", "result.json", "scene_manifest.json", "coordinator_log.json", "SHA256SUMS"} <= names
    for line in (tmp_path / "y/SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ./")
        assert hashlib.sha256((tmp_path / "y" / name).read_bytes()).hexdigest() == digest
    assert json.loads((tmp_path / "y/scene_manifest.json").read_text())["data_kind"] == "SYNTHETIC_TEST"
    with pytest.raises(SystemExit):
        demo.main(["--scenario", "no_such_scenario"])


# ------------------------------------------------------------------------- executor contract (Part VIII) --
SITE, FLEET = im._site_fleet(im.load_context(im.CONTEXT))
NOW = pc.utc_now()


def positive():
    r = result("red_target")
    return r, r["execution_request"]


def final_proposal_and_task():
    bundle = im.plan_phase_a(pd.CONFIG, safety_policy="safety/3")
    obs = pc.fixture_observation(site=SITE, drone="drone_02", poi="POI_3", now=NOW)
    gate = pc.ground_target_from_observation(obs, site=SITE, context=bundle["context"], fleet=FLEET, now=NOW,
                                             policy=pd.POLICY, camera_ids=im.CAMERAS)
    pb = im.plan_phase_b(pd.CONFIG, bundle, gate, safety_policy="safety/3", pin_aerial=True)["proposal"]
    return pb, pb["ground"]["proposals"][0]


def test_the_request_is_versioned_complete_and_carries_no_implicit_authorization():
    _, req = positive()
    assert req["schema"] == "tfg.multiagent.rover-execution-request/1"
    for key in ("task_id", "vehicle_id", "proposal_sha256", "frame", "target", "dependencies"):
        assert req[key] not in (None, "", [])
    assert req["vehicle_id"] == "rover_01" and req["frame"] == "synthetic_orchard_local"
    assert req["authorization"] is None and req["navigation_plan"] is None  # no human set limits: nothing runnable
    assert '"human_authorized": true' not in json.dumps(req).lower()
    assert rb.validate_request(req) == ["NO_NAVIGATION_PLAN: speed and timeout were not set by a human"]


def test_the_authorization_is_bound_to_plan_vehicle_and_proposal():
    pb, task = final_proposal_and_task()
    req = rb.execution_request(task, SITE, proposal=pb, dependencies=pb["template"]["dependencies"],
                               human_limits={"max_speed_mps": 0.2, "timeout_s": 60})
    assert rb.validate_request(req) == []
    other_vehicle = rb.authorization_scope(req["navigation_plan"], proposal_sha256=pb["proposal_sha256"], vehicle_id="rover_02")
    other_proposal = rb.authorization_scope(req["navigation_plan"], proposal_sha256="0" * 64, vehicle_id="rover_01")
    assert len({req["expected_scope_sha256"], other_vehicle, other_proposal}) == 3
    executor = rb.DryRunRoverExecutor()
    state, health = executor.observe()
    from multiagent import human_authorization as ha
    other = rb.execution_request({**task, "vehicle_id": "rover_02"}, SITE, proposal=pb, dependencies=[],
                                 human_limits={"max_speed_mps": 0.2, "timeout_s": 60})
    signed_for_rover_02 = ha.record(other, operator_id="op-fixture", at=NOW, valid_for_s=300, statement="fixture")
    reasons = rb.preconditions(plan=req["navigation_plan"], authorization=signed_for_rover_02, request=req,
                               expected_scope=req["expected_scope_sha256"], capabilities=executor.capabilities(),
                               state=state, health=health, state_at=None, now=NOW)
    assert reasons[0].startswith("AUTHORIZATION_SCOPE_MISMATCH") and any(r.startswith("NO_POSITION_SOURCE") for r in reasons)
    assert any(r.startswith("ODOMETRY_STALE") for r in reasons)


def test_a_conditional_target_never_produces_movement_and_the_adapter_refuses():
    req = {"schema": rb.REQUEST_SCHEMA, "task_id": "GROUND_rover_01", "vehicle_id": "rover_01", "proposal_sha256": "x",
           "frame": "synthetic_orchard_local", "target": {"point_id": None}, "dependencies": [], "navigation_plan": None}
    assert any(p.startswith("CONDITIONAL_TARGET") for p in rb.validate_request(req))
    fb = rb.DryRunRoverExecutor().execute({"plan_id": "p"}, {"human_authorized": True})
    assert fb["status"] == "REFUSED_DRY_RUN_ONLY" and fb["physical_effect"] is False
    assert rb.DryRunRoverExecutor().stop()["physical_effect"] is False
    assert rb.validate_request({**req, "schema": "something/9"})[0].startswith("UNKNOWN_SCHEMA")


def test_cancellation_invalidates_pending_requests_and_errors_reach_the_coordinator():
    a = im.run(now=NOW)["phase_a"]
    c = Coordinator(proposal=a["proposal"], conditional_tasks=a["conditional_ground_tasks"], site=SITE,
                    context=im.load_context(im.CONTEXT), fleet=FLEET, cameras=im.CAMERAS, policy=pd.POLICY)
    ev = lambda kind, dt=0, **kw: {"type": kind, "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=dt), **kw}  # noqa: E731
    for phase in ("INTERPRETED", "AERIAL_PLANNED", "VALIDATED"):
        c.handle(ev("MISSION_PHASE", phase=phase))
    c.handle(ev("CANCEL", 1, reason="operator"))
    assert c.handle(ev("AUTHORIZATION", 2, human_authorized=True, scope_sha256="s", expected_scope="s"))["outcome"] == "REFUSED"
    fb = rb.feedback_event(rb.DryRunRoverExecutor().execute({}, {}), task_id="GROUND_rover_01", at=NOW)
    assert fb["type"] == "GROUND_TASK_REFUSED_BY_EXECUTOR"
    c2 = Coordinator(proposal=a["proposal"], conditional_tasks=a["conditional_ground_tasks"], site=SITE,
                     context=im.load_context(im.CONTEXT), fleet=FLEET, cameras=im.CAMERAS, policy=pd.POLICY)
    c2.handle(ev("EXECUTOR_FEEDBACK", 1, feedback_type="GROUND_TASK_FAILED", error="lost odometry"))
    assert c2.mission_state == "ERROR"


def test_llm_tools_expose_no_actuation_interface():
    from multiagent import agent_tools
    from multiagent.agent_tools import drone_tools, rover_tools
    names = {t.name for t in rover_tools(site=SITE, context=im.load_context(im.CONTEXT), fleet=FLEET, rover_id="rover_01",
                                         aerial_points=[], contract="v3")}
    assert not names & agent_tools.OPERATIONAL_NAMES and "execute" not in " ".join(names)
    assert not hasattr(rb, "send_command") and rb.DryRunRoverExecutor.physical_effect is False


def test_after_a_supervisor_refusal_no_other_agent_runs():
    r = result("supervisor_refuses")
    assert r["classification"] == "MISSION_REFUSED_BY_SUPERVISOR" and r["coordinator"]["mission"] == "REFUSED_BY_SUPERVISOR"
    assert r["agent_records"]["rover_phase_a"]["llm_calls"] is None  # the rover agent was never invoked (pilot M4 defect)
    assert r["detection"]["status"] == "NOT_RUN" and r["execution_request"] is None and not any(r["status_ladder"].values())


def test_the_cli_refuses_an_existing_output_directory_before_running(tmp_path, capsys):
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "evidence.txt").write_text("keep")
    for argv in (["--scenario", "red_target", "--out", str(tmp_path / "old")],
                 ["--all-scenarios", "--out", str(tmp_path / "old")]):
        with pytest.raises(SystemExit) as exc:
            demo.main(argv)
        assert exc.value.code == 2 and "never overwritten" in capsys.readouterr().err
    assert [p.name for p in (tmp_path / "old").iterdir()] == ["evidence.txt"]
    with pytest.raises(SystemExit):
        demo.main(["--scenario", "no_such_scenario"])
    assert demo.main(["--scenario", "supervisor_refuses", "--safety-policy", "safety/4"]) == 0


def test_the_phase_a_rover_tool_calls_are_kept_as_evidence(tmp_path):
    """Found in M4c-r1: the phase-A rover verifications were requested but their results were not written."""
    r = pd.run_scenario("red_target", quiet=True, out=tmp_path / "e")
    review = json.loads((tmp_path / "e/phase_a_rover_review.json").read_text())
    assert review["tool_log"] and "rover_capabilities" in {t["tool"] for t in review["tool_log"]}
    assert r["agent_records"]["rover_phase_a"]["tool_log"] == review["tool_log"]
