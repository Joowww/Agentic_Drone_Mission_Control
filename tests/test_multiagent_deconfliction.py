"""Spatio-temporal deconfliction and scalability (1, 2, 3, 5 drones). Offline, synthetic, planning only."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path

import pytest

from multiagent import scenarios
from multiagent.contracts import OperatingContext, SeparationPolicy, load_context
from multiagent.deconfliction import ASSUMPTIONS, deconflict, timeline

FIX = Path(__file__).resolve().parents[1] / "multiagent/fixtures"
POLICY = SeparationPolicy(**scenarios.POLICY)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("offline only")
    monkeypatch.setattr("socket.socket.connect", refuse)
    monkeypatch.setattr("subprocess.run", refuse)
    monkeypatch.setattr("subprocess.Popen", refuse)


def plan(points, minutes):
    labels = ["PAD", *[f"W{i}" for i in range(1, len(points) - 1)], "PAD (return)"]
    return {"route_local": points, "labels": labels, "leg_minutes": minutes}


# Two drones whose routes cross at (0, 0) at the same moment if they start together.
CROSS_A = plan([(-20, 0), (20, 0), (-20, 0)], [0.5, 0.5])
CROSS_B = plan([(0, -20), (0, 20), (0, -20)], [0.5, 0.5])


def test_crossing_routes_at_the_same_time_conflict_and_a_start_delay_resolves_them():
    result = deconflict({"a": CROSS_A, "b": CROSS_B}, POLICY)
    assert result["initial_conflicts"] and result["status"] == "DECONFLICTED_BY_START_DELAY"
    assert result["residual_conflicts"] == []
    delays = {v: s["start_delay_s"] for v, s in result["schedule"].items()}
    assert sorted(delays.values())[0] == 0.0 and sorted(delays.values())[1] > 0
    conflict = result["initial_conflicts"][0]
    assert conflict["kind"] == "DRONE_DRONE" and conflict["min_distance_m"] < conflict["required_m"]
    assert result["assumptions"] == ASSUMPTIONS


def test_spatially_separated_routes_are_clear_without_delay():
    far = plan([(100, 100), (120, 100), (100, 100)], [0.5, 0.5])
    result = deconflict({"a": CROSS_A, "far": far}, POLICY)
    assert result["status"] == "CLEAR" and all(s["start_delay_s"] == 0 for s in result["schedule"].values())


def test_insufficient_temporal_separation_is_unresolved_under_a_tight_policy():
    tight = POLICY.model_copy(update={"max_start_delay_s": 10.0})
    result = deconflict({"a": CROSS_A, "b": CROSS_B}, tight)
    assert result["status"] == "UNRESOLVED" and result["residual_conflicts"]
    assert "no start delay <= 10.0 s" in result["reason"]


def test_mission_duration_limit_also_rejects_a_delay():
    short = POLICY.model_copy(update={"max_mission_duration_s": 100.0})
    assert deconflict({"a": CROSS_A, "b": CROSS_B}, short)["status"] == "UNRESOLVED"


def test_timing_uncertainty_widens_windows():
    exact = POLICY.model_copy(update={"timing_uncertainty_s": 0.0, "timing_uncertainty_fraction": 0.0})
    loose = POLICY.model_copy(update={"timing_uncertainty_s": 30.0})
    d_exact = deconflict({"a": CROSS_A, "b": CROSS_B}, exact)["schedule"]
    d_loose = deconflict({"a": CROSS_A, "b": CROSS_B}, loose)["schedule"]
    assert max(s["start_delay_s"] for s in d_loose.values()) > max(s["start_delay_s"] for s in d_exact.values())


def test_without_policy_or_leg_times_separation_is_pending_never_clear():
    assert deconflict({"a": CROSS_A, "b": CROSS_B}, None)["status"] == "PENDING_MISSING_DATA"
    broken = dict(CROSS_B, leg_minutes=[0.5])
    assert deconflict({"a": CROSS_A, "b": broken}, POLICY)["status"] == "PENDING_MISSING_DATA"
    assert deconflict({"a": CROSS_A}, POLICY)["status"] == "NOT_APPLICABLE"


def test_a_shared_takeoff_point_forbids_overlapping_missions():
    other = plan([(-20, 0), (-20, 30), (-20, 0)], [0.5, 0.5])
    result = deconflict({"a": CROSS_A, "b": other}, POLICY)
    assert any(c["kind"] == "SHARED_TAKEOFF_POINT" for c in result["initial_conflicts"])
    starts = sorted(s["start_delay_s"] for s in result["schedule"].values())
    a_end = timeline("a", CROSS_A["route_local"], CROSS_A["labels"], CROSS_A["leg_minutes"], POLICY)[-1].t1
    assert result["status"] == "DECONFLICTED_BY_START_DELAY" and starts[1] >= a_end


def test_required_distance_adds_uncertainties_and_extent():
    assert POLICY.required_distance_m() == pytest.approx(5.0 + 2 * 1.5 + 0.5)


# ------------------------------------------------------------- agent-level coordination --
POINTS = [("POI_1", "rgb"), ("POI_3", "thermal"), ("POI_9", "multispectral")]


def test_simultaneous_incompatible_objectives_are_separated_in_time():
    row = scenarios.run_scenario(load_context(FIX / "swarm_3.context.json"), POINTS)
    assert row["status"] == "PROPOSED_PENDING_AUTHORIZATION" and row["coordination"] == "DECONFLICTED_BY_START_DELAY"
    assert row["conflicts_initial"] > 0 and row["conflicts_residual"] == 0
    assert any(d["start_delay_s"] > 0 for d in row["per_drone"].values())


def test_replanning_drops_an_objective_when_no_delay_fits_and_says_why():
    row = scenarios.run_scenario(load_context(FIX / "swarm_3_tight.context.json"), POINTS)
    assert row["status"] == "PARTIAL_PENDING_AUTHORIZATION" and row["replanned"] is True
    assert row["coordination"] in ("CLEAR", "DECONFLICTED_BY_START_DELAY") and row["conflicts_residual"] == 0
    assert len(row["assigned"]) == 2 and "O1" in row["assigned"]
    assert any(r.startswith("COORDINATION_CONFLICT") for r in row["rejected"].values())


def test_no_policy_keeps_the_swarm_pending():
    row = scenarios.run_scenario(load_context(FIX / "swarm_2_no_policy.context.json"), [("POI_1", None), ("POI_2", None)])
    assert row["status"] == "COORDINATION_PENDING" and row["coordination"] == "PENDING_MISSING_DATA"


def test_allocation_failure_when_no_drone_can_take_anything():
    row = scenarios.run_scenario(load_context(FIX / "swarm_3.context.json"), [("POI_8", None)])
    assert row["status"] == "INFEASIBLE" and row["assigned"] == []
    assert "O1" in row["rejected"]


def _ctx(n, **drone_updates):
    value = scenarios.context_dict(n)
    for drone in value["drones"]:
        drone.update(drone_updates.get(drone["vehicle_id"], {}))
    return OperatingContext.model_validate(value)


def test_a_drone_without_battery_margin_is_not_used():
    row = scenarios.run_scenario(_ctx(3, drone_03={"battery_percent": 20.0}), [("POI_3", "thermal")])
    assert row["status"] == "INFEASIBLE"


def test_a_drone_without_the_sensor_is_not_used():
    row = scenarios.run_scenario(_ctx(2), [("POI_3", "thermal")])
    assert row["status"] == "INFEASIBLE" and "SENSOR_MISSING" in row["rejected"]["O1"]


def test_excessive_wind_excludes_the_drone():
    context = _ctx(5)
    row = scenarios.run_scenario(context, [("POI_6", "multispectral")], wind_speed_kmh=18.0)
    assert row["status"] == "INFEASIBLE"
    site, fleet = scenarios._world(context)
    from multiagent.drone_agent import plan_aerial
    with redirect_stdout(io.StringIO()):
        result, _ = plan_aerial(scenarios.objectives([("POI_6", "multispectral")]), context=context, site=site,
                                fleet=fleet, wind_speed_kmh=18.0, battery_percent={}, altitude_m=None, requested_drones=[])
    assert "WIND_ABOVE_LIMIT" in result.evidence["reference"]["eligibility"]["O1"]["drone_04"][0]


# ------------------------------------------------------------------------- scalability --
@pytest.fixture(scope="module")
def comparison():
    return scenarios.compare()


def test_scenarios_cover_one_two_three_and_five_drones(comparison):
    rows = {r["drones_declared"]: r for r in comparison["rows"]}
    assert sorted(rows) == [1, 2, 3, 5] and comparison["data_kind"] == "SYNTHETIC"
    assert [len(rows[n]["assigned"]) for n in (1, 2, 3, 5)] == sorted(len(rows[n]["assigned"]) for n in (1, 2, 3, 5))
    for row in rows.values():
        assert row["conflicts_residual"] == 0 and row["elapsed_s"] < 20


def test_three_drones(comparison):
    row = next(r for r in comparison["rows"] if r["drones_declared"] == 3)
    assert len(row["per_drone"]) == 3 and row["per_drone"]["drone_03"]["export"] == "NOT_EXPORTED"
    assert row["search_mode"] == "GREEDY" and row["optimality"] == "NOT_GUARANTEED"


def test_five_drones_respect_availability(comparison):
    row = next(r for r in comparison["rows"] if r["drones_declared"] == 5)
    assert row["drones_available"] == 4 and "drone_05" not in row["per_drone"]
    assert "NOT_AVAILABLE" in row["rejected"]["O8"]


def test_greedy_is_compared_with_the_exhaustive_reference(comparison):
    for gap in comparison["optimality_gap"]:
        assert gap["coverage_gap"] >= 0 and gap["exhaustive"]["covered"] >= gap["greedy"]["covered"]


def test_fixtures_match_the_generator():
    for name, value in scenarios.fixture_contexts().items():
        assert json.loads((FIX / name).read_text()) == value, name
