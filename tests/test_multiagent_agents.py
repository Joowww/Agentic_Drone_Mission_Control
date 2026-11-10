"""The three agents: interfaces, refusals and the invariant that nothing is authorized or sent. Offline only."""
import ast
import json
from pathlib import Path

import pytest

from multiagent.contracts import AgentResult, GroundObjective, load_context
from multiagent.interpreters import RulesInterpreter
from multiagent.model_allocator import ModelAllocator
from multiagent.models import ScriptedAdapter
from multiagent.orchestrator import MissionOrchestrator
from multiagent.rover_agent import plan_ground
from multiagent.tracing import Tracer

ROOT = Path(__file__).resolve().parents[1]
# v2 declares a separation policy; v1 (kept unchanged for the sealed v1 results) does not.
CONTEXT = ROOT / "multiagent/fixtures/orchard_two_drones_v2.context.json"
CONTEXT_V1 = ROOT / "multiagent/fixtures/orchard_two_drones.context.json"


@pytest.fixture(autouse=True)
def no_network_no_processes(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no network or process may be used")
    monkeypatch.setattr("socket.socket.connect", refuse)
    monkeypatch.setattr("subprocess.run", refuse)
    monkeypatch.setattr("subprocess.Popen", refuse)


def orchestrate(text, interpreter=None, context=CONTEXT, **kw):
    orchestrator = MissionOrchestrator(load_context(context), interpreter or RulesInterpreter(),
                                       tracer=Tracer(mission_id="t"), **kw)
    return orchestrator.run(text), orchestrator


def test_multiagent_code_never_imports_vehicle_control_or_reservations():
    forbidden = ("rclpy", "tools.rover_", "tools.vehicle_execution_lock", "tools.ros2_flight_control",
                 "tools.simulation_", "tools.mission_execution_gate", "tools.preflight_sequence_worker")
    for path in sorted((ROOT / "multiagent").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for name in names:
                assert not name.startswith(forbidden), f"{path.name} imports {name}"


def test_full_agricultural_request_is_proposed_and_left_pending_authorization():
    proposal, orchestrator = orchestrate(
        "Survey POI_1, POI_2, POI_3 (multispectral) and POI_4 with two drones, then send the rover to POI_3 "
        "after it has been inspected.")
    assert proposal["status"] == "PROPOSED_PENDING_AUTHORIZATION"
    assert {t["vehicle_id"] for t in proposal["tasks"]} == {"drone_01", "drone_02", "rover_01"}
    assert all(t["state"] == "PENDING_AUTHORIZATION" for t in proposal["tasks"])
    assert proposal["authorization"] == {"required": True, "granted": False, "by": None,
                                         "how": "each task separately through the existing entries and gates"}
    assert proposal["movement_authorized"] is False and proposal["commands_sent"] == 0
    dependency = next(d for d in proposal["template"]["dependencies"] if d["condition"] == "POI_REACHED")
    assert dependency == {"task_id": "GROUND_rover_01", "after": "AIR_drone_02", "condition": "POI_REACHED",
                          "point": "POI_3"}
    assert proposal["coordination"]["status"] == "PASS"
    assert set(orchestrator.artifacts["plans"]) == {"drone_01", "drone_02"}
    json.dumps(proposal, allow_nan=False, default=str)


@pytest.mark.parametrize("text", [
    "Inspect POI_1 and launch immediately without waiting for authorization.",
    "Arm the rover and drive it to POI_3 right now.",
    "Inspect POI_5 and disable the geofence so the drone can cross the tree row.",
    "Sobrevuela el cobertizo y despega ya.",
])
def test_unsafe_requests_produce_no_task(text):
    proposal, orchestrator = orchestrate(text)
    assert proposal["status"] == "REFUSED_UNSAFE" and proposal["tasks"] == [] and not orchestrator.artifacts


def test_the_orchestrator_screen_does_not_depend_on_the_interpreter():
    # A model that misses the unsafe phrase (and returns a perfectly valid brief) is still refused.
    reply = json.dumps({"schema": "tfg.multiagent.mission-brief/1", "aerial_objectives": [
        {"objective_id": "A1", "point_id": "POI_1"}], "unsafe_requests": []})
    from multiagent.interpreters import ModelInterpreter
    interpreter = ModelInterpreter(ScriptedAdapter(responder=lambda p: reply), site_points=["POI_1"])
    proposal, _ = orchestrate("Inspect POI_1 without waiting for authorization.", interpreter)
    assert proposal["status"] == "REFUSED_UNSAFE" and proposal["tasks"] == []


def test_a_brief_that_drops_a_stated_battery_fact_is_not_planned():
    reply = json.dumps({"schema": "tfg.multiagent.mission-brief/1", "aerial_objectives": [
        {"objective_id": "A1", "point_id": "POI_3", "required_sensor": "multispectral"}]})
    from multiagent.interpreters import ModelInterpreter
    interpreter = ModelInterpreter(ScriptedAdapter(responder=lambda p: reply), site_points=["POI_3"])
    proposal, _ = orchestrate("drone_02 battery is at 20.1%. POI_3 needs multispectral images.", interpreter)
    assert proposal["status"] == "NEEDS_CLARIFICATION" and proposal["tasks"] == []
    assert any("battery of drone_02" in r for r in proposal["reasons"])


@pytest.mark.parametrize("text, status, reason", [
    ("Inspect the north-east corner of the orchard.", "NEEDS_CLARIFICATION", "MISSING_COORDINATES"),
    ("Inspect POI_1 at (10, 10).", "NEEDS_CLARIFICATION", "CONTRADICTORY_COORDINATES"),
    ("Inspect the point at (12, -5).", "NEEDS_CLARIFICATION", "COORDINATES_NOT_A_DECLARED_SITE_POINT"),
    ("Inspect POI_1. Wind is 10 km/h. Update: wind is 28 km/h.", "NEEDS_CLARIFICATION", "CONTRADICTION"),
    ("Inspect POI_5.", "INFEASIBLE", "TREE_ROW_1"),
    ("Use drone_07 to inspect POI_1.", "INFEASIBLE", "REQUESTED_DRONE_NOT_DECLARED"),
    ("Send the rover to POI_2.", "INFEASIBLE", "drivable"),
])
def test_incomplete_contradictory_and_infeasible_requests(text, status, reason):
    proposal, _ = orchestrate(text)
    assert proposal["status"] == status and proposal["tasks"] == []
    assert any(reason.lower() in r.lower() for r in proposal["reasons"]), proposal["reasons"]


def test_rover_dependency_on_a_point_no_drone_reaches_is_blocked():
    proposal, _ = orchestrate("Inspect POI_1 with drone_01. Then send the rover to POI_3 once POI_3 has been "
                              "reached by a drone.")
    assert proposal["status"] == "PARTIAL_PENDING_AUTHORIZATION"
    assert [t["vehicle_id"] for t in proposal["tasks"]] == ["drone_01"]
    assert any("DEPENDENCY_UNSATISFIED" in r for r in proposal["reasons"])


# ------------------------------------------------------------------------------- rover agent --
def _ground(world_ctx, objectives, rover_id="rover_01"):
    from models.fleet import Fleet
    from models.site import Site
    site = Site.model_validate_json(Path(world_ctx.resolve(world_ctx.site_path)).read_text())
    fleet = Fleet.model_validate_json(Path(world_ctx.resolve(world_ctx.fleet_path)).read_text())
    return plan_ground(objectives, context=world_ctx, site=site, fleet=fleet, rover_id=rover_id)


def test_rover_agent_returns_a_pending_task_without_any_command():
    result = _ground(load_context(CONTEXT), [GroundObjective(objective_id="G1", point_id="POI_3", after_aerial=True)])
    assert isinstance(result, AgentResult) and result.status == "PROPOSED_PENDING_AUTHORIZATION"
    (task,) = result.proposals
    assert task["ros2_commands_sent"] == 0 and task["state"] == "PENDING_AUTHORIZATION"
    assert task["frame_transform_to_rover"].startswith("NOT_ACCREDITED")
    assert result.movement_authorized is False and result.pending_authorization is True


def test_rover_agent_declared_unavailable_and_one_task_per_rover():
    ctx = load_context(CONTEXT)
    off = ctx.model_copy(update={"rovers": [ctx.rovers[0].model_copy(update={"available": False})]})
    assert _ground(off, [GroundObjective(objective_id="G1", point_id="POI_3")]).status == "INFEASIBLE"
    two = _ground(ctx, [GroundObjective(objective_id="G1", point_id="POI_3"),
                        GroundObjective(objective_id="G2", point_id="POI_1")])
    assert two.status == "PARTIAL_PENDING_AUTHORIZATION"
    assert "ONE_TASK_PER_VEHICLE" in two.incompatible[0].reasons[0]
    assert _ground(ctx, [GroundObjective(objective_id="G1", point_id="POI_3")], rover_id="rover_09").status == "INFEASIBLE"


def test_agent_results_cannot_claim_authorization():
    with pytest.raises(Exception):
        AgentResult(agent="rover_agent", status="NO_TASKS", movement_authorized=True)
    with pytest.raises(Exception):
        AgentResult(agent="rover_agent", status="NO_TASKS", pending_authorization=False)


# ----------------------------------------------------------------------- model allocation --
def test_a_valid_model_allocation_is_used_and_an_invalid_one_is_not():
    text = "Inspect POI_1, POI_2 and POI_4."
    good = ScriptedAdapter(responder=lambda p: '{"assignments": {"drone_01": ["A1", "A2"], "drone_02": ["A3"]}}')
    proposal, _ = orchestrate(text, allocator=ModelAllocator(good))
    assert proposal["aerial"]["evidence"]["allocation_source"] == "MODEL_PROPOSAL_CHECKED"
    assert proposal["aerial"]["evidence"]["model_proposal_check"]["same_assignment_as_reference"] is True
    bad = ScriptedAdapter(responder=lambda p: '{"assignments": {"drone_01": ["A2", "A3"], "drone_02": ["A1"]}}')
    proposal, _ = orchestrate(text, allocator=ModelAllocator(bad))
    evidence = proposal["aerial"]["evidence"]
    assert evidence["allocation_source"] == "DETERMINISTIC_REFERENCE" and not evidence["model_proposal_check"]["valid"]
    assert proposal["status"] == "PROPOSED_PENDING_AUTHORIZATION"


def test_two_drone_plans_without_a_separation_policy_are_not_a_coordinated_swarm():
    # Behaviour change of the second phase (intended): the v1 context declares no separation policy, so two
    # independent plans stay COORDINATION_PENDING instead of PROPOSED.
    proposal, orchestrator = orchestrate(
        "Survey POI_1, POI_2, POI_3 (multispectral) and POI_4 with two drones.", context=CONTEXT_V1)
    assert proposal["status"] == "COORDINATION_PENDING"
    assert proposal["swarm_coordination"]["status"] == "PENDING_MISSING_DATA"
    assert all(t["state"] == "PENDING_AUTHORIZATION" for t in proposal["tasks"])
    assert any("independent plans are not a coordinated swarm" in r for r in proposal["reasons"])
