"""Deterministic reference allocation among two drones with different capabilities (offline, synthetic site)."""
import copy
from contextlib import redirect_stdout
import io
from pathlib import Path

import pytest

from inputs.qgc_plan_export import build_plan, plan_bytes, verify_plan
from models.fleet import Fleet
from models.site import Site
from multiagent.contracts import load_context
from multiagent.swarm import MAX_OBJECTIVES, Objective, SwarmProblem, evaluate_proposal, reference_allocation

CONTEXT = Path(__file__).resolve().parents[1] / "multiagent/fixtures/orchard_two_drones.context.json"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))


@pytest.fixture(scope="module")
def world():
    ctx = load_context(CONTEXT)
    site = Site.model_validate_json(Path(ctx.resolve(ctx.site_path)).read_text())
    fleet = Fleet.model_validate_json(Path(ctx.resolve(ctx.fleet_path)).read_text())
    return ctx, site, fleet


def problem(world, objectives, *, wind=0.0, battery=None, drones=None, altitude=None):
    ctx, site, fleet = world
    return SwarmProblem(site, fleet, ctx, objectives, drones or list(ctx.drones), wind, dict(battery or {}), altitude)


def quiet(fn, *a, **k):
    with redirect_stdout(io.StringIO()):
        return fn(*a, **k)


FIVE = [Objective("O1", "POI_1", "rgb"), Objective("O2", "POI_2"), Objective("O3", "POI_3", "multispectral"),
        Objective("O4", "POI_4"), Objective("O5", "POI_5")]


def test_two_drones_with_different_sensors_share_the_objectives(world):
    result = quiet(reference_allocation, problem(world, FIVE))
    assert result["status"] == "OK"
    assert {v: a["sequence"] for v, a in result["assignments"].items()} == {
        "drone_01": ["POI_1", "POI_2"], "drone_02": ["POI_3", "POI_4"]}
    for assignment in result["assignments"].values():
        assert assignment["deterministic_validation"]["mission_status"] == "FEASIBLE"
    evidence = result["evidence"]
    assert evidence["eligibility"]["O1"]["drone_02"] == ["SENSOR_MISSING: drone_02 has no rgb sensor"]
    assert evidence["eligibility"]["O3"]["drone_01"] == ["SENSOR_MISSING: drone_01 has no multispectral sensor"]
    assert evidence["chosen"]["covered"] == 4 and evidence["runner_up"]["makespan_min"] >= evidence["chosen"]["makespan_min"]


def test_an_objective_no_drone_can_reach_is_reported_with_the_site_reason(world):
    result = quiet(reference_allocation, problem(world, FIVE))
    (unassigned,) = result["unassigned"]
    assert unassigned["objective_id"] == "O5"
    assert all("TREE_ROW_1" in r for r in unassigned["reasons"]) and len(unassigned["reasons"]) == 4


def test_allocation_is_deterministic(world):
    a = quiet(reference_allocation, problem(world, FIVE))
    b = quiet(reference_allocation, problem(world, list(reversed(FIVE))))
    assert {v: x["mission_sha256"] for v, x in a["assignments"].items()} == \
           {v: x["mission_sha256"] for v, x in b["assignments"].items()}
    assert a["evidence"]["inputs_sha256"] == quiet(reference_allocation, problem(world, FIVE))["evidence"]["inputs_sha256"]


def test_each_individual_plan_is_exported_and_verified(world, tmp_path):
    ctx, site, _ = world
    result = quiet(reference_allocation, problem(world, FIVE[:4]))
    for vehicle_id, assignment in result["assignments"].items():
        plan, _ = build_plan(assignment["mission"], planned_home_amsl_m=site.vertical_reference.origin_ground_amsl_m)
        path = tmp_path / f"{vehicle_id}.plan"
        path.write_bytes(plan_bytes(plan))
        assert verify_plan(path, assignment["mission"], planned_home_amsl_m=584.0)["status"] == "FILE_MATCHES_EXPECTATIONS"


def test_battery_declared_in_the_request_excludes_a_drone(world):
    objectives = [Objective("O3", "POI_3", "multispectral")]
    assert quiet(reference_allocation, problem(world, objectives))["assignments"]
    low = quiet(reference_allocation, problem(world, objectives, battery={"drone_02": 20.1}))
    assert low["assignments"] == {}
    assert any("battery" in r.lower() or "reserve" in r.lower() for r in low["unassigned"][0]["reasons"])


def test_wind_above_a_drone_limit_makes_it_ineligible(world):
    ctx, *_ = world
    weak = [ctx.drones[0], ctx.drones[1].model_copy(update={"max_wind_kmh": 8.0})]
    result = quiet(reference_allocation, problem(world, [Objective("O1", "POI_1"), Objective("O3", "POI_3", "multispectral")],
                                                 wind=9.0, drones=weak))
    assert list(result["assignments"]) == ["drone_01"]
    assert "WIND_ABOVE_LIMIT" in result["evidence"]["eligibility"]["O3"]["drone_02"][0]


def test_unavailable_drone_is_not_used(world):
    ctx, *_ = world
    drones = [ctx.drones[0].model_copy(update={"available": False}), ctx.drones[1]]
    result = quiet(reference_allocation, problem(world, [Objective("O2", "POI_2"), Objective("O4", "POI_4")], drones=drones))
    assert list(result["assignments"]) == ["drone_02"]


def test_search_bound_is_explicit(world):
    many = [Objective(f"O{i}", "POI_1") for i in range(MAX_OBJECTIVES + 1)]
    assert quiet(reference_allocation, problem(world, many))["status"] == "REFUSED"


# ---------------------------------------------------------------- model proposal interface --
def test_the_reference_itself_scores_perfectly(world):
    p = problem(world, FIVE[:4])
    reference = quiet(reference_allocation, p)
    proposal = {"assignments": {"drone_01": ["O1", "O2"], "drone_02": ["O3", "O4"]}}
    score = quiet(evaluate_proposal, p, proposal, reference)
    assert score["valid"] and score["same_assignment_as_reference"] and score["makespan_ratio"] == pytest.approx(1.0)


def test_a_valid_but_worse_proposal_scores_below_one(world):
    p = problem(world, [Objective("O1", "POI_1"), Objective("O2", "POI_2"), Objective("O4", "POI_4")])
    reference = quiet(reference_allocation, p)
    assert reference["evidence"]["chosen"]["assignment"] == {"drone_01": ["O1", "O2"], "drone_02": ["O4"]}
    worse = {"assignments": {"drone_01": ["O1", "O4"], "drone_02": ["O2"]}}
    score = quiet(evaluate_proposal, p, worse, reference)
    assert score["valid"] and score["coverage_ratio"] == 1.0
    assert score["makespan_ratio"] == pytest.approx(0.636, abs=0.01) and not score["same_assignment_as_reference"]


@pytest.mark.parametrize("proposal, needle", [
    ({"assignments": {"drone_02": ["O1"]}}, "SENSOR_MISSING"),
    ({"assignments": {"drone_01": ["O1", "O1"]}}, "DUPLICATE_OBJECTIVE"),
    ({"assignments": {"drone_01": ["O9"]}}, "UNKNOWN_OBJECTIVE"),
    ({"assignments": {"drone_09": ["O1"]}}, "UNKNOWN_DRONE"),
    ({"assignments": {"drone_01": ["O2", "O4"]}}, "TREE_ROW_1"),
    ({"assignments": "drone_01 takes everything"}, "PROPOSAL_NOT_AN_ASSIGNMENT_MAP"),
])
def test_invalid_model_proposals_are_rejected_with_reasons(world, proposal, needle):
    p = problem(world, FIVE[:4])
    score = quiet(evaluate_proposal, p, copy.deepcopy(proposal))
    assert not score["valid"] and any(needle in v for v in score["violations"])
